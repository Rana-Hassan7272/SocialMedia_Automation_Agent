"""
Research Agent with ReAct reasoning.
Searches Hacker News, RSS feeds, and optional Reddit.
"""

import json
from typing import Dict, Any, List
from .base_agent import BaseAgent
from ..database import DatabaseManager
from ..utils.research_client import ResearchClient
from ..workflow.state import WorkflowStep


class ResearchAgent(BaseAgent):
    """ReAct-style agent for multi-source trend research."""

    def __init__(self, db_manager: DatabaseManager, research_client: ResearchClient):
        super().__init__(temperature=0.4)
        self.db_manager = db_manager
        self.research_client = research_client

    def get_system_prompt(self) -> str:
        return """You are a research planning agent. Your job is to plan how to find trending content on a topic.

Sources available: Hacker News (tech), RSS news feeds (world/business/tech), and optionally Reddit.

Given a topic and scope, determine:
1. Relevant communities or angles (subreddit hints still help if Reddit is enabled)
2. An optimized search query
3. Time filter hint (hour/day/week) for Reddit if used

Return ONLY valid JSON:
{
    "subreddits": ["community1", "community2"],
    "search_query": "optimized search query",
    "time_filter": "day",
    "reasoning": "brief explanation"
}

Return ONLY the JSON, nothing else."""

    def _generate_research_strategy(self, topic: str, scope: str) -> Dict[str, Any]:
        prompt = f"Topic: {topic}\nScope: {scope}\n\nGenerate research strategy:"
        try:
            response = self.invoke_llm(prompt)
            strategy = json.loads(response)
            if "subreddits" not in strategy or not strategy["subreddits"]:
                strategy["subreddits"] = self.research_client.get_relevant_subreddits(topic)
            if "search_query" not in strategy:
                strategy["search_query"] = topic
            if "time_filter" not in strategy:
                strategy["time_filter"] = "day"
            return strategy
        except (json.JSONDecodeError, KeyError):
            return {
                "subreddits": self.research_client.get_relevant_subreddits(topic),
                "search_query": topic,
                "time_filter": "day",
            }

    def _search_sources(self, strategy: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return self.research_client.search_posts(
                query=strategy["search_query"],
                subreddits=strategy["subreddits"],
                limit=30,
                time_filter=strategy["time_filter"],
            )
        except Exception as e:
            print(f"   ⚠️  Research search failed: {str(e)}")
            return []

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        topic = state.get("topic", "")
        scope = state.get("scope", "latest")
        workflow_id = state.get("workflow_id")

        if not topic:
            state["error"] = "No topic provided for research"
            return state

        print(f"\n🔍 Researching: {topic} ({scope})")
        print("   💭 Thinking: Generating research strategy...")
        strategy = self._generate_research_strategy(topic, scope)
        print(f"   📝 Query: {strategy['search_query']}")
        print(f"   🔎 Searching Hacker News + RSS (+ Reddit if configured)...")
        posts = self._search_sources(strategy)
        print(f"   ✅ Found {len(posts)} items")

        sorted_posts = sorted(
            posts,
            key=lambda p: p["engagement_score"],
            reverse=True,
        )

        if workflow_id and self.db_manager:
            for post in sorted_posts:
                try:
                    self.db_manager.create_research_result(
                        workflow_id=workflow_id,
                        tweet_id=post["post_id"],
                        author=post["author"],
                        author_username=post["subreddit"],
                        content=post["content"],
                        engagement_score=post["engagement_score"],
                        likes=post["score"],
                        retweets=0,
                        replies=post["num_comments"],
                        tweet_created_at=post["created_at"],
                    )
                except Exception:
                    pass

        state["raw_tweets"] = sorted_posts
        state["current_step"] = WorkflowStep.RESEARCH
        return state
