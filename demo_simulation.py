"""
Complete End-to-End Demo (Simulation Mode).
Full pipeline without actual Twitter publishing for testing.
"""

from src.agents import (
    IntentAgent, ResearchAgent, FilteringAgent,
    SummarizationAgent, DraftingAgent
)
from src.database import DatabaseManager
from src.utils import RedditClient
from src.utils.research_client import ResearchClient
from src.workflow.state import create_initial_state

print("🚀 SOCIAL MEDIA AUTOMATION PIPELINE (Simulation Mode)\n")
print("=" * 70)

# Initialize components (no Twitter client needed)
db = DatabaseManager()
reddit_client = RedditClient()

intent_agent = IntentAgent(db_manager=db)
research_client = ResearchClient(reddit_client=reddit_client)
research_agent = ResearchAgent(db_manager=db, research_client=research_client)
filtering_agent = FilteringAgent(db_manager=db, top_k=5)
summarization_agent = SummarizationAgent(db_manager=db)
drafting_agent = DraftingAgent(db_manager=db)

# User query
query = input("\n📝 Enter your query (or press Enter for default): ").strip()
if not query:
    query = "What's happening in AI today?"

print(f"\n🎯 Query: \"{query}\"\n")
print("=" * 70)

# Create workflow
workflow = db.create_workflow(query)
workflow_id = workflow.id
state = create_initial_state(query, workflow_id)

# STEP 1: Intent Understanding
print("\n📍 STEP 1: Intent Understanding")
print("-" * 70)
state = intent_agent.process(state)
print(f"✅ Topic: {state['topic']}, Scope: {state['scope']}, Tone: {state['tone']}")

# STEP 2: Research
print("\n📍 STEP 2: Research (Reddit)")
print("-" * 70)
state = research_agent.process(state)
print(f"✅ Found {len(state.get('raw_tweets', []))} posts")

# STEP 3: Filter
print("\n📍 STEP 3: Filtering & Ranking")
print("-" * 70)
state = filtering_agent.process(state)
print(f"✅ Filtered to {len(state.get('filtered_tweets', []))} top posts")

# STEP 4: Summarize
print("\n📍 STEP 4: Summarization")
print("-" * 70)
state = summarization_agent.process(state)
print(f"✅ Generated insights")

# Show insights
print("\n📋 SUMMARY:")
print(f"   {state.get('summary', 'N/A')}")
print("\n📈 KEY TRENDS:")
for i, trend in enumerate(state.get('key_trends', [])[:3], 1):
    print(f"   {i}. {trend}")

# STEP 5: Draft
print("\n📍 STEP 5: Drafting")
print("-" * 70)
state = drafting_agent.process(state)

# Show final draft
draft = state.get('draft_content', '')
print(f"\n✅ FINAL TWEET DRAFT:")
print("=" * 70)
print(draft)
print("=" * 70)
print(f"Character count: {len(draft)}/280")

# Simulated review
print("\n📍 STEP 6: Human Review (Simulated)")
print("-" * 70)
print("✅ Draft looks good!")

print("\n📍 STEP 7: Publishing (Simulated)")
print("-" * 70)
print("✅ Would publish to Twitter/X (skipped - no API credentials)")
print("💡 To enable publishing:")
print("   1. Set Twitter app to 'Read and Write' permissions")
print("   2. Regenerate Access Token & Secret")
print("   3. Update .env file")
print("   4. Run demo_complete_pipeline.py")

print("\n" + "=" * 70)
print(f"✅ Workflow #{workflow_id} complete (simulation)")
print(f"📊 Check database for full details")
print("=" * 70)
