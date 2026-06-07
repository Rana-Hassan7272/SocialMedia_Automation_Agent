"""
Workflow state management for LangGraph.
Defines the state that flows through the agent workflow.
"""

from typing import TypedDict, Optional, List, Dict, Any, Union
from enum import Enum


class WorkflowStep(str, Enum):
    START = "start"
    INTENT_UNDERSTANDING = "intent_understanding"
    RESEARCH = "research"
    FILTER = "filter"
    SUMMARIZE = "summarize"
    DRAFT = "draft"
    HUMAN_REVIEW = "human_review"
    PUBLISH = "publish"
    END = "end"


class WorkflowState(TypedDict, total=False):
    workflow_id: int
    user_id: Optional[int]
    x_username: Optional[str]
    current_step: WorkflowStep
    user_query: str
    topic: Optional[str]
    scope: Optional[str]
    tone: Optional[str]
    raw_tweets: Optional[List[Dict[str, Any]]]
    filtered_tweets: Optional[List[Dict[str, Any]]]
    summary: Optional[str]
    key_trends: Optional[Union[str, List[str]]]
    expert_opinions: Optional[List[str]]
    draft_content: Optional[str]
    draft_id: Optional[int]
    draft_version: int
    feedback_type: Optional[str]
    feedback_comments: Optional[str]
    approved: bool
    revision_requested: bool
    revision_feedback: Optional[str]
    review_requested: bool
    rejected: bool
    published: bool
    tweet_id: Optional[str]
    tweet_url: Optional[str]
    error: Optional[str]


def create_initial_state(
    user_query: str,
    workflow_id: int,
    user_id: Optional[int] = None,
    x_username: Optional[str] = None,
) -> WorkflowState:
    return WorkflowState(
        workflow_id=workflow_id,
        user_id=user_id,
        x_username=x_username,
        current_step=WorkflowStep.START,
        user_query=user_query,
        draft_version=0,
        published=False,
        approved=False,
        revision_requested=False,
        rejected=False,
    )
