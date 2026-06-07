"""
Publishing Agent.
Handles human review and publishing to Twitter/X.
"""

from typing import Dict, Any, Optional
from .base_agent import BaseAgent
from ..database import DatabaseManager
from ..database.models import AuditAction, DraftStatus, FeedbackType, WorkflowStatus
from ..utils import TwitterClient
from ..utils.logging_config import get_logger
from ..workflow.state import WorkflowStep

logger = get_logger(__name__)


class PublishingAgent(BaseAgent):
    """
    Agent that handles human review and publishes to Twitter/X.
    Supports approve, reject, and request revision workflows.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        twitter_client: Optional[TwitterClient] = None,
    ):
        super().__init__(temperature=0.0)
        self.db_manager = db_manager
        self.twitter_client = twitter_client

    def get_system_prompt(self) -> str:
        return ""

    def request_human_review(self, state: Dict[str, Any]) -> Dict[str, Any]:
        draft_content = state.get("draft_content", "")
        topic = state.get("topic", "")

        logger.info(
            "workflow_id=%s human review draft_chars=%s topic=%s",
            state.get("workflow_id"),
            len(draft_content),
            topic,
        )

        state["review_requested"] = True
        state["current_step"] = WorkflowStep.HUMAN_REVIEW
        return state

    def handle_approval(
        self,
        state: Dict[str, Any],
        twitter_client: Optional[TwitterClient] = None,
    ) -> Dict[str, Any]:
        draft_content = state.get("draft_content", "")
        draft_id = state.get("draft_id")
        workflow_id = state.get("workflow_id")

        if state.get("published"):
            return state

        client = twitter_client or self.twitter_client
        if not client:
            state["error"] = "No X account connected for publishing"
            return state

        logger.info("workflow_id=%s publishing approved draft", workflow_id)

        try:
            result = client.create_tweet(draft_content)
            tweet_id = result["tweet_id"]
            tweet_url = result["tweet_url"]

            if draft_id and self.db_manager:
                with self.db_manager.get_session() as session:
                    from ..database.models import Feedback, Draft
                    feedback = Feedback(
                        draft_id=draft_id,
                        feedback_type=FeedbackType.APPROVE,
                        comments="Approved for publishing",
                    )
                    session.add(feedback)
                    draft = session.get(Draft, draft_id)
                    if draft:
                        draft.status = DraftStatus.APPROVED

                self.db_manager.create_published_post(
                    workflow_id=workflow_id,
                    draft_id=draft_id,
                    twitter_post_id=tweet_id,
                    twitter_post_url=tweet_url,
                )
                self.db_manager.update_workflow_status(
                    workflow_id=workflow_id,
                    status=WorkflowStatus.COMPLETED,
                )
                self.db_manager.create_audit_log(
                    AuditAction.POST_PUBLISHED,
                    user_id=state.get("user_id"),
                    workflow_id=workflow_id,
                    x_username=state.get("x_username"),
                    details=tweet_url,
                )
                self.db_manager.create_audit_log(
                    AuditAction.DRAFT_APPROVED,
                    user_id=state.get("user_id"),
                    workflow_id=workflow_id,
                    x_username=state.get("x_username"),
                )

            state["published"] = True
            state["tweet_id"] = tweet_id
            state["tweet_url"] = tweet_url
            state["current_step"] = WorkflowStep.PUBLISH
            return state

        except Exception as e:
            logger.error("workflow_id=%s publish failed: %s", workflow_id, e)
            state["error"] = f"Publishing failed: {str(e)}"
            if workflow_id and self.db_manager:
                self.db_manager.update_workflow_status(
                    workflow_id=workflow_id,
                    status=WorkflowStatus.FAILED,
                    error_message=str(e),
                )
            return state

    def handle_rejection(self, state: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
        draft_id = state.get("draft_id")
        workflow_id = state.get("workflow_id")

        if draft_id and self.db_manager:
            with self.db_manager.get_session() as session:
                from ..database.models import Feedback, Draft
                feedback = Feedback(
                    draft_id=draft_id,
                    feedback_type=FeedbackType.REJECT,
                    comments=reason or "Rejected",
                )
                session.add(feedback)
                draft = session.get(Draft, draft_id)
                if draft:
                    draft.status = DraftStatus.REJECTED

            self.db_manager.update_workflow_status(
                workflow_id=workflow_id,
                status=WorkflowStatus.FAILED,
                error_message=f"Draft rejected: {reason}",
            )
            self.db_manager.create_audit_log(
                AuditAction.DRAFT_REJECTED,
                user_id=state.get("user_id"),
                workflow_id=workflow_id,
                x_username=state.get("x_username"),
                details=reason or "Rejected",
            )

        state["rejected"] = True
        return state

    def handle_revision_request(self, state: Dict[str, Any], feedback: str) -> Dict[str, Any]:
        draft_id = state.get("draft_id")

        if draft_id and self.db_manager:
            with self.db_manager.get_session() as session:
                from ..database.models import Feedback
                feedback_obj = Feedback(
                    draft_id=draft_id,
                    feedback_type=FeedbackType.MODIFY,
                    comments=feedback,
                )
                session.add(feedback_obj)
            self.db_manager.create_audit_log(
                AuditAction.DRAFT_REVISION,
                user_id=state.get("user_id"),
                workflow_id=state.get("workflow_id"),
                x_username=state.get("x_username"),
                details=feedback,
            )

        state["revision_requested"] = True
        state["revision_feedback"] = feedback
        state["approved"] = False
        return state

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.request_human_review(state)
