"""
LangGraph workflow orchestration.
Defines the complete agent workflow graph.
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Dict, Any, Optional, Tuple
from .state import WorkflowState, WorkflowStep, create_initial_state
from ..agents.intent_agent import IntentAgent
from ..agents.research_agent import ResearchAgent
from ..agents.filtering_agent import FilteringAgent
from ..agents.summarization_agent import SummarizationAgent
from ..agents.drafting_agent import DraftingAgent
from ..agents.publishing_agent import PublishingAgent
from ..database import DatabaseManager
from ..database.models import WorkflowPhase, WorkflowStatus
from ..utils import RedditClient, TwitterClient
from ..utils.research_client import ResearchClient
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

PHASE_BY_NODE = {
    "intent": WorkflowPhase.INTENT,
    "research": WorkflowPhase.RESEARCH,
    "filter": WorkflowPhase.FILTER,
    "summarize": WorkflowPhase.SUMMARIZE,
    "draft": WorkflowPhase.DRAFT,
    "review": WorkflowPhase.DRAFT_READY,
    "publish": WorkflowPhase.PUBLISHING,
}


class WorkflowGraph:
    """LangGraph-based workflow orchestration."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        reddit_client: RedditClient,
        twitter_client: Optional[TwitterClient] = None,
    ):
        self.db_manager = db_manager
        self.reddit_client = reddit_client
        self.research_client = ResearchClient(reddit_client=reddit_client)
        self.twitter_client = twitter_client
        self.checkpointer = MemorySaver()

        self.intent_agent = IntentAgent(db_manager=db_manager)
        self.research_agent = ResearchAgent(
            db_manager=db_manager,
            research_client=self.research_client,
        )
        self.filtering_agent = FilteringAgent(db_manager=db_manager, top_k=5)
        self.summarization_agent = SummarizationAgent(db_manager=db_manager)
        self.drafting_agent = DraftingAgent(db_manager=db_manager)
        self.publishing_agent = PublishingAgent(
            db_manager=db_manager,
            twitter_client=twitter_client,
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(WorkflowState)

        workflow.add_node("intent", self._intent_node)
        workflow.add_node("research", self._research_node)
        workflow.add_node("filter", self._filter_node)
        workflow.add_node("summarize", self._summarize_node)
        workflow.add_node("draft", self._draft_node)
        workflow.add_node("review", self._review_node)
        workflow.add_node("publish", self._publish_node)

        workflow.set_entry_point("intent")
        workflow.add_edge("intent", "research")
        workflow.add_edge("research", "filter")
        workflow.add_edge("filter", "summarize")
        workflow.add_edge("summarize", "draft")
        workflow.add_edge("draft", "review")
        workflow.add_conditional_edges(
            "review",
            self._should_publish,
            {
                "publish": "publish",
                "revise": "draft",
                "end": END,
            },
        )
        workflow.add_edge("publish", END)

        return workflow.compile(
            checkpointer=self.checkpointer,
            interrupt_before=["review"],
        )

    def _sync_phase(self, state: WorkflowState, node_name: str) -> None:
        workflow_id = state.get("workflow_id")
        if not workflow_id:
            return
        phase = PHASE_BY_NODE.get(node_name)
        if phase:
            self.db_manager.update_workflow_phase(workflow_id, phase)

    def _run_node(self, node_name: str, state: WorkflowState, handler) -> WorkflowState:
        logger.info("workflow_id=%s node=%s", state.get("workflow_id"), node_name)
        self._sync_phase(state, node_name)
        result = handler(state)
        if result.get("error"):
            workflow_id = result.get("workflow_id")
            if workflow_id:
                self.db_manager.update_workflow_phase(workflow_id, WorkflowPhase.FAILED)
                self.db_manager.update_workflow_status(
                    workflow_id,
                    WorkflowStatus.FAILED,
                    error_message=result["error"],
                )
        return result

    def _intent_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node("intent", state, self.intent_agent.process)

    def _research_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node("research", state, self.research_agent.process)

    def _filter_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node("filter", state, self.filtering_agent.process)

    def _summarize_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node("summarize", state, self.summarization_agent.process)

    def _draft_node(self, state: WorkflowState) -> WorkflowState:
        if state.get("revision_requested") and state.get("revision_feedback"):
            def revise_handler(current: WorkflowState) -> WorkflowState:
                updated = self.drafting_agent.create_revision(
                    current, current["revision_feedback"]
                )
                updated["revision_requested"] = False
                updated["revision_feedback"] = None
                updated["approved"] = False
                return updated
            return self._run_node("draft", state, revise_handler)
        return self._run_node("draft", state, self.drafting_agent.process)

    def _review_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node("review", state, self.publishing_agent.request_human_review)

    def _publish_node(self, state: WorkflowState) -> WorkflowState:
        self._sync_phase(state, "publish")
        twitter_client = self.twitter_client
        if not twitter_client and state.get("user_id"):
            try:
                twitter_client = TwitterClient.from_user_id(
                    state["user_id"], self.db_manager
                )
            except ValueError:
                pass
        result = self.publishing_agent.handle_approval(
            state, twitter_client=twitter_client
        )
        workflow_id = result.get("workflow_id")
        if workflow_id and result.get("published"):
            self.db_manager.update_workflow_phase(workflow_id, WorkflowPhase.PUBLISHED)
        return result

    def _should_publish(self, state: WorkflowState) -> str:
        if state.get("approved"):
            return "publish"
        if state.get("revision_requested"):
            return "revise"
        return "end"

    def _thread_config(self, thread_id: str) -> Dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def is_interrupted(self, thread_id: str) -> bool:
        snapshot = self.graph.get_state(self._thread_config(thread_id))
        return bool(snapshot.next)

    def get_state(self, thread_id: str) -> WorkflowState:
        snapshot = self.graph.get_state(self._thread_config(thread_id))
        return dict(snapshot.values)

    def start_workflow(self, user_query: str, user_id: Optional[int] = None) -> int:
        workflow = self.db_manager.create_workflow(user_query, user_id=user_id)
        return workflow.id

    def execute_until_review(
        self,
        workflow_id: int,
        user_query: str,
        user_id: Optional[int] = None,
        x_username: Optional[str] = None,
    ) -> Tuple[WorkflowState, str]:
        self.db_manager.update_workflow_status(workflow_id, WorkflowStatus.IN_PROGRESS)
        thread_id = f"wf-{workflow_id}"
        self.db_manager.update_workflow_phase(workflow_id, WorkflowPhase.INTENT, thread_id)

        initial_state = create_initial_state(
            user_query, workflow_id, user_id=user_id, x_username=x_username
        )
        config = self._thread_config(thread_id)
        state = self.graph.invoke(initial_state, config)

        if self.is_interrupted(thread_id):
            self.db_manager.update_workflow_phase(workflow_id, WorkflowPhase.DRAFT_READY, thread_id)
            self.db_manager.update_workflow_status(workflow_id, WorkflowStatus.DRAFT_READY)

        return state, thread_id

    def run_until_review(
        self,
        user_query: str,
        user_id: Optional[int] = None,
        x_username: Optional[str] = None,
    ) -> Tuple[WorkflowState, str]:
        workflow_id = self.start_workflow(user_query, user_id=user_id)
        return self.execute_until_review(
            workflow_id=workflow_id,
            user_query=user_query,
            user_id=user_id,
            x_username=x_username,
        )

    def resume(
        self,
        thread_id: str,
        updates: Dict[str, Any],
        twitter_client: Optional[TwitterClient] = None,
    ) -> WorkflowState:
        config = self._thread_config(thread_id)
        self.graph.update_state(config, updates)
        if twitter_client:
            self.publishing_agent.twitter_client = twitter_client
        return self.graph.invoke(None, config)

    def run(self, user_query: str, user_id: Optional[int] = None) -> WorkflowState:
        state, thread_id = self.run_until_review(user_query, user_id=user_id)
        if self.is_interrupted(thread_id):
            return state
        return state
