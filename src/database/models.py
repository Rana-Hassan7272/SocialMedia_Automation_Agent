"""
SQLAlchemy ORM models for Social Media Automation System.
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Integer, String, Text, DateTime, Float,
    ForeignKey, Enum as SQLEnum, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
import enum


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


def _enum(enum_cls):
    return SQLEnum(enum_cls, values_callable=lambda x: [e.value for e in x], native_enum=False)


class WorkflowStatus(str, enum.Enum):
    """Workflow execution status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DRAFT_READY = "draft_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowPhase(str, enum.Enum):
    PENDING = "pending"
    INTENT = "intent"
    RESEARCH = "research"
    FILTER = "filter"
    SUMMARIZE = "summarize"
    DRAFT = "draft"
    DRAFT_READY = "draft_ready"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AuditAction(str, enum.Enum):
    CONNECT_X = "connect_x"
    DISCONNECT_X = "disconnect_x"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_FAILED = "workflow_failed"
    DRAFT_APPROVED = "draft_approved"
    DRAFT_REJECTED = "draft_rejected"
    DRAFT_REVISION = "draft_revision"
    POST_PUBLISHED = "post_published"


class DraftStatus(str, enum.Enum):
    """Draft status."""
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class FeedbackType(str, enum.Enum):
    """User feedback type."""
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"


class User(Base):
    """X-authenticated application user."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    x_user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    x_username: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    workflows: Mapped[List["Workflow"]] = relationship("Workflow", back_populates="user")
    oauth_token: Mapped[Optional["OAuthToken"]] = relationship(
        "OAuthToken", back_populates="user", uselist=False
    )


class AppSession(Base):
    """Browser session token for Streamlit login persistence."""
    __tablename__ = "app_sessions"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class OAuthPkceSession(Base):
    """Temporary PKCE verifier storage for X OAuth callback."""
    __tablename__ = "oauth_pkce_sessions"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    code_verifier_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class OAuthToken(Base):
    """Encrypted OAuth tokens per user."""
    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="oauth_token")


class Workflow(Base):
    """Track complete workflow executions."""
    __tablename__ = "workflows"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        _enum(WorkflowStatus),
        default=WorkflowStatus.PENDING,
        nullable=False,
    )
    phase: Mapped[WorkflowPhase] = mapped_column(
        _enum(WorkflowPhase),
        default=WorkflowPhase.PENDING,
        nullable=False,
    )
    thread_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    intent: Mapped[Optional["Intent"]] = relationship(
        "Intent", back_populates="workflow", uselist=False
    )
    research_results: Mapped[List["ResearchResult"]] = relationship(
        "ResearchResult", back_populates="workflow"
    )
    filtered_content: Mapped[List["FilteredContent"]] = relationship(
        "FilteredContent", back_populates="workflow"
    )
    insights: Mapped[List["Insight"]] = relationship(
        "Insight", back_populates="workflow"
    )
    drafts: Mapped[List["Draft"]] = relationship(
        "Draft", back_populates="workflow"
    )
    published_post: Mapped[Optional["PublishedPost"]] = relationship(
        "PublishedPost", back_populates="workflow", uselist=False
    )
    user: Mapped[Optional["User"]] = relationship("User", back_populates="workflows")


class Intent(Base):
    """Store parsed user intents."""
    __tablename__ = "intents"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    tone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    raw_intent: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="intent")


class ResearchResult(Base):
    """Store research results (Reddit posts or tweets)."""
    __tablename__ = "research_results"
    __table_args__ = (
        UniqueConstraint("workflow_id", "tweet_id", name="uq_workflow_tweet"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id"), nullable=False
    )
    tweet_id: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    author_username: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    engagement_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retweets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replies: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tweet_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    workflow: Mapped["Workflow"] = relationship(
        "Workflow", back_populates="research_results"
    )
    filtered_content: Mapped[Optional["FilteredContent"]] = relationship(
        "FilteredContent", back_populates="research_result", uselist=False
    )


class FilteredContent(Base):
    """Store filtered and ranked tweets."""
    __tablename__ = "filtered_content"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id"), nullable=False
    )
    research_result_id: Mapped[int] = mapped_column(
        ForeignKey("research_results.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    workflow: Mapped["Workflow"] = relationship(
        "Workflow", back_populates="filtered_content"
    )
    research_result: Mapped["ResearchResult"] = relationship(
        "ResearchResult", back_populates="filtered_content"
    )


class Insight(Base):
    """Store summarized insights."""
    __tablename__ = "insights"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_trends: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expert_opinions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    workflow: Mapped["Workflow"] = relationship(
        "Workflow", back_populates="insights"
    )


class Draft(Base):
    """Store Twitter/X post drafts."""
    __tablename__ = "drafts"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DraftStatus] = mapped_column(
        _enum(DraftStatus),
        default=DraftStatus.DRAFT,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    workflow: Mapped["Workflow"] = relationship(
        "Workflow", back_populates="drafts"
    )
    feedback: Mapped[List["Feedback"]] = relationship(
        "Feedback", back_populates="draft"
    )
    published_post: Mapped[Optional["PublishedPost"]] = relationship(
        "PublishedPost", back_populates="draft", uselist=False
    )


class Feedback(Base):
    """Store user feedback on drafts."""
    __tablename__ = "feedback"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("drafts.id"), nullable=False
    )
    feedback_type: Mapped[FeedbackType] = mapped_column(
        _enum(FeedbackType),
        nullable=False,
    )
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    draft: Mapped["Draft"] = relationship("Draft", back_populates="feedback")


class PublishedPost(Base):
    """Store final published posts to Twitter/X."""
    __tablename__ = "published_posts"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id"), nullable=False, unique=True
    )
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("drafts.id"), nullable=False
    )
    twitter_post_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    twitter_post_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    workflow: Mapped["Workflow"] = relationship(
        "Workflow", back_populates="published_post"
    )
    draft: Mapped["Draft"] = relationship(
        "Draft", back_populates="published_post"
    )


class AuditLog(Base):
    """Security and compliance audit trail."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    workflow_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workflows.id"), nullable=True)
    x_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[AuditAction] = mapped_column(_enum(AuditAction), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
