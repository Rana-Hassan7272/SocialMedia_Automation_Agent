"""
Database manager for Social Media Automation System.
Handles database initialization, connections, and CRUD operations.
"""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from contextlib import contextmanager
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from .models import (
    Base, User, OAuthToken, AppSession, OAuthPkceSession, Workflow, Intent, ResearchResult,
    FilteredContent, Insight, Draft, Feedback, PublishedPost, AuditLog,
    WorkflowStatus, WorkflowPhase, DraftStatus, FeedbackType, AuditAction,
)
from ..config import get_settings
from ..auth.encryption import decrypt_value, encrypt_value
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


def _safe_db_log_url(database_url: str) -> str:
    if "@" in database_url:
        return database_url.split("@", 1)[1]
    return database_url


class DatabaseManager:
    """Manages database operations for the social media automation system."""
    
    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize database manager.
        
        Args:
            database_url: SQLAlchemy database URL. If None, uses settings.
        """
        settings = get_settings()
        self.database_url = database_url or settings.get_database_url()
        engine_kwargs = {"echo": settings.log_level == "DEBUG"}
        if self.database_url.startswith("postgresql"):
            engine_kwargs["pool_pre_ping"] = True
            engine_kwargs["pool_recycle"] = 300
        self.engine = create_engine(self.database_url, **engine_kwargs)
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=self.engine,
        )
        
    def initialize_database(self):
        """Create all tables in the database."""
        Base.metadata.create_all(bind=self.engine)
        logger.info("Database initialized at: %s", _safe_db_log_url(self.database_url))

    def drop_all_tables(self):
        """Drop all tables (use with caution!)."""
        Base.metadata.drop_all(bind=self.engine)
        logger.warning("All database tables dropped")
    
    @contextmanager
    def get_session(self):
        """
        Context manager for database sessions.
        
        Yields:
            Session: SQLAlchemy session
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    # ========================================
    # Workflow Operations
    # ========================================
    
    def create_workflow(
        self,
        user_query: str,
        user_id: Optional[int] = None,
    ) -> Workflow:
        """
        Create a new workflow.
        
        Args:
            user_query: User's original query
            user_id: Optional authenticated user ID
            
        Returns:
            Created Workflow object
        """
        with self.get_session() as session:
            workflow = Workflow(
                user_query=user_query,
                user_id=user_id,
                status=WorkflowStatus.PENDING,
                phase=WorkflowPhase.PENDING,
            )
            session.add(workflow)
            session.flush()
            session.refresh(workflow)
            # Expunge from session so it can be used after session closes
            session.expunge(workflow)
            return workflow
    
    def get_workflow(self, workflow_id: int) -> Optional[Workflow]:
        """Get workflow by ID."""
        with self.get_session() as session:
            workflow = session.get(Workflow, workflow_id)
            if workflow:
                session.expunge(workflow)
            return workflow
    
    def update_workflow_status(
        self,
        workflow_id: int,
        status: WorkflowStatus,
        error_message: Optional[str] = None
    ) -> Workflow:
        """Update workflow status."""
        with self.get_session() as session:
            workflow = session.get(Workflow, workflow_id)
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")
            
            workflow.status = status
            if error_message:
                workflow.error_message = error_message
            if status == WorkflowStatus.COMPLETED:
                workflow.completed_at = datetime.utcnow()
            
            session.flush()
            session.refresh(workflow)
            session.expunge(workflow)
            return workflow
    
    def get_all_workflows(self, limit: int = 100) -> List[Workflow]:
        """Get all workflows, most recent first."""
        with self.get_session() as session:
            stmt = select(Workflow).order_by(Workflow.created_at.desc()).limit(limit)
            return list(session.scalars(stmt).all())

    def count_user_workflows_today(self, user_id: int) -> int:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.get_session() as session:
            stmt = select(Workflow).where(
                Workflow.user_id == user_id,
                Workflow.created_at >= today_start,
            )
            return len(list(session.scalars(stmt).all()))

    # ========================================
    # User & OAuth Operations
    # ========================================

    def save_oauth_pkce(
        self,
        state: str,
        code_verifier: str,
        redirect_uri: Optional[str] = None,
    ) -> None:
        if redirect_uri is None:
            redirect_uri = get_settings().twitter_callback_url.rstrip("/")
        cutoff = datetime.utcnow() - timedelta(minutes=15)
        payload = json.dumps({"v": code_verifier, "r": redirect_uri.rstrip("/")})
        with self.get_session() as session:
            stale = select(OAuthPkceSession).where(OAuthPkceSession.created_at < cutoff)
            for row in session.scalars(stale).all():
                session.delete(row)
            session.add(
                OAuthPkceSession(
                    state=state,
                    code_verifier_encrypted=encrypt_value(payload),
                )
            )

    def get_oauth_pkce(self, state: str) -> Optional[Dict[str, str]]:
        with self.get_session() as session:
            row = session.get(OAuthPkceSession, state)
            if not row:
                return None
            try:
                payload = json.loads(decrypt_value(row.code_verifier_encrypted))
                return {
                    "code_verifier": payload["v"],
                    "redirect_uri": payload.get("r", ""),
                }
            except (ValueError, KeyError, json.JSONDecodeError):
                verifier = decrypt_value(row.code_verifier_encrypted)
                return {"code_verifier": verifier, "redirect_uri": ""}

    def delete_oauth_pkce(self, state: str) -> None:
        with self.get_session() as session:
            row = session.get(OAuthPkceSession, state)
            if row:
                session.delete(row)

    def create_app_session(self, user_id: int, days: int = 30) -> str:
        import secrets
        token = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(days=days)
        with self.get_session() as session:
            session.add(AppSession(token=token, user_id=user_id, expires_at=expires))
        return token

    def get_app_session(self, token: str) -> Optional[User]:
        with self.get_session() as session:
            row = session.get(AppSession, token)
            if not row or row.expires_at < datetime.utcnow():
                return None
            user = session.get(User, row.user_id)
            if user:
                session.expunge(user)
            return user

    def delete_app_session(self, token: str) -> None:
        with self.get_session() as session:
            row = session.get(AppSession, token)
            if row:
                session.delete(row)

    def upsert_user(self, x_user_id: str, x_username: str) -> User:
        with self.get_session() as session:
            stmt = select(User).where(User.x_user_id == x_user_id)
            user = session.scalar(stmt)
            if user:
                user.x_username = x_username
                user.last_login_at = datetime.utcnow()
            else:
                user = User(
                    x_user_id=x_user_id,
                    x_username=x_username,
                    last_login_at=datetime.utcnow(),
                )
                session.add(user)
            session.flush()
            session.refresh(user)
            session.expunge(user)
            return user

    def get_user(self, user_id: int) -> Optional[User]:
        with self.get_session() as session:
            user = session.get(User, user_id)
            if user:
                session.expunge(user)
            return user

    def save_oauth_token(
        self,
        user_id: int,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> OAuthToken:
        with self.get_session() as session:
            stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
            token_row = session.scalar(stmt)
            if token_row:
                token_row.access_token_encrypted = encrypt_value(access_token)
                token_row.refresh_token_encrypted = (
                    encrypt_value(refresh_token) if refresh_token else None
                )
                token_row.expires_at = expires_at
                token_row.updated_at = datetime.utcnow()
            else:
                token_row = OAuthToken(
                    user_id=user_id,
                    access_token_encrypted=encrypt_value(access_token),
                    refresh_token_encrypted=(
                        encrypt_value(refresh_token) if refresh_token else None
                    ),
                    expires_at=expires_at,
                )
                session.add(token_row)
            session.flush()
            session.refresh(token_row)
            session.expunge(token_row)
            return token_row

    def get_user_oauth_tokens(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self.get_session() as session:
            user = session.get(User, user_id)
            if not user or not user.oauth_token:
                return None
            token_row = user.oauth_token
            result = {
                "access_token": decrypt_value(token_row.access_token_encrypted),
                "refresh_token": (
                    decrypt_value(token_row.refresh_token_encrypted)
                    if token_row.refresh_token_encrypted
                    else None
                ),
                "expires_at": token_row.expires_at,
                "x_username": user.x_username,
                "x_user_id": user.x_user_id,
            }
            return result

    def delete_user_oauth_token(self, user_id: int) -> None:
        with self.get_session() as session:
            stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
            token_row = session.scalar(stmt)
            if token_row:
                session.delete(token_row)

    def get_user_workflows(self, user_id: int, limit: int = 20) -> List[Workflow]:
        with self.get_session() as session:
            stmt = (
                select(Workflow)
                .where(Workflow.user_id == user_id)
                .order_by(Workflow.created_at.desc())
                .limit(limit)
            )
            workflows = list(session.scalars(stmt).all())
            for workflow in workflows:
                session.expunge(workflow)
            return workflows

    def update_workflow_phase(
        self,
        workflow_id: int,
        phase: WorkflowPhase,
        thread_id: Optional[str] = None,
    ) -> None:
        with self.get_session() as session:
            workflow = session.get(Workflow, workflow_id)
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")
            workflow.phase = phase
            if thread_id:
                workflow.thread_id = thread_id
            if phase == WorkflowPhase.DRAFT_READY:
                workflow.status = WorkflowStatus.DRAFT_READY
            elif phase == WorkflowPhase.PUBLISHED:
                workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.utcnow()
            elif phase == WorkflowPhase.FAILED:
                workflow.status = WorkflowStatus.FAILED
            elif phase in {
                WorkflowPhase.INTENT,
                WorkflowPhase.RESEARCH,
                WorkflowPhase.FILTER,
                WorkflowPhase.SUMMARIZE,
                WorkflowPhase.DRAFT,
                WorkflowPhase.PUBLISHING,
            }:
                workflow.status = WorkflowStatus.IN_PROGRESS

    def create_audit_log(
        self,
        action: AuditAction,
        user_id: Optional[int] = None,
        workflow_id: Optional[int] = None,
        x_username: Optional[str] = None,
        details: Optional[str] = None,
    ) -> AuditLog:
        with self.get_session() as session:
            entry = AuditLog(
                action=action,
                user_id=user_id,
                workflow_id=workflow_id,
                x_username=x_username,
                details=details,
            )
            session.add(entry)
            session.flush()
            session.refresh(entry)
            session.expunge(entry)
            logger.info(
                "audit action=%s user_id=%s workflow_id=%s x_username=%s",
                action.value,
                user_id,
                workflow_id,
                x_username,
            )
            return entry

    def get_user_audit_logs(self, user_id: int, limit: int = 20) -> List[AuditLog]:
        with self.get_session() as session:
            stmt = (
                select(AuditLog)
                .where(AuditLog.user_id == user_id)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
            logs = list(session.scalars(stmt).all())
            for entry in logs:
                session.expunge(entry)
            return logs

    # ========================================
    # Intent Operations
    # ========================================
    
    def create_intent(
        self,
        workflow_id: int,
        topic: str,
        scope: str,
        raw_intent: str,
        tone: Optional[str] = None
    ) -> Intent:
        """Create a new intent."""
        with self.get_session() as session:
            intent = Intent(
                workflow_id=workflow_id,
                topic=topic,
                scope=scope,
                tone=tone,
                raw_intent=raw_intent
            )
            session.add(intent)
            session.flush()
            session.refresh(intent)
            session.expunge(intent)
            return intent
    
    def get_intent_by_workflow(self, workflow_id: int) -> Optional[Intent]:
        """Get intent for a workflow."""
        with self.get_session() as session:
            stmt = select(Intent).where(Intent.workflow_id == workflow_id)
            return session.scalar(stmt)
    
    # ========================================
    # Research Result Operations
    # ========================================
    
    def create_research_result(
        self,
        workflow_id: int,
        tweet_id: str,
        author: str,
        author_username: str,
        content: str,
        engagement_score: int,
        likes: int,
        retweets: int,
        replies: int,
        tweet_created_at: datetime
    ) -> ResearchResult:
        """Create a new research result (tweet)."""
        with self.get_session() as session:
            result = ResearchResult(
                workflow_id=workflow_id,
                tweet_id=tweet_id,
                author=author,
                author_username=author_username,
                content=content,
                engagement_score=engagement_score,
                likes=likes,
                retweets=retweets,
                replies=replies,
                tweet_created_at=tweet_created_at
            )
            session.add(result)
            session.flush()
            session.refresh(result)
            session.expunge(result)
            return result
    
    def get_research_results_by_workflow(
        self,
        workflow_id: int
    ) -> List[ResearchResult]:
        """Get all research results for a workflow."""
        with self.get_session() as session:
            stmt = select(ResearchResult).where(
                ResearchResult.workflow_id == workflow_id
            ).order_by(ResearchResult.engagement_score.desc())
            return list(session.scalars(stmt).all())
    
    # ========================================
    # Filtered Content Operations
    # ========================================
    
    def create_filtered_content(
        self,
        workflow_id: int,
        research_result_id: int,
        rank: int,
        relevance_score: float
    ) -> FilteredContent:
        """Create filtered content entry."""
        with self.get_session() as session:
            filtered = FilteredContent(
                workflow_id=workflow_id,
                research_result_id=research_result_id,
                rank=rank,
                relevance_score=relevance_score
            )
            session.add(filtered)
            session.flush()
            session.refresh(filtered)
            session.expunge(filtered)
            return filtered
    
    def get_filtered_content_by_workflow(
        self,
        workflow_id: int
    ) -> List[FilteredContent]:
        """Get filtered content for a workflow, ordered by rank."""
        with self.get_session() as session:
            stmt = select(FilteredContent).where(
                FilteredContent.workflow_id == workflow_id
            ).order_by(FilteredContent.rank)
            rows = list(session.scalars(stmt).all())
            for row in rows:
                session.expunge(row)
            return rows
    
    # ========================================
    # Insight Operations
    # ========================================
    
    def create_insight(
        self,
        workflow_id: int,
        summary: str,
        key_trends: Optional[str] = None,
        expert_opinions: Optional[str] = None
    ) -> Insight:
        """Create a new insight."""
        with self.get_session() as session:
            insight = Insight(
                workflow_id=workflow_id,
                summary=summary,
                key_trends=key_trends,
                expert_opinions=expert_opinions
            )
            session.add(insight)
            session.flush()
            session.refresh(insight)
            return insight
    
    def get_insights_by_workflow(self, workflow_id: int) -> List[Insight]:
        """Get all insights for a workflow."""
        with self.get_session() as session:
            stmt = select(Insight).where(
                Insight.workflow_id == workflow_id
            ).order_by(Insight.created_at.desc())
            return list(session.scalars(stmt).all())
    
    # ========================================
    # Draft Operations
    # ========================================
    
    def create_draft(
        self,
        workflow_id: int,
        content: str,
        version: int = 1,
        status: DraftStatus = DraftStatus.DRAFT
    ) -> Draft:
        """Create a new draft."""
        with self.get_session() as session:
            draft = Draft(
                workflow_id=workflow_id,
                version=version,
                content=content,
                status=status
            )
            session.add(draft)
            session.flush()
            session.refresh(draft)
            session.expunge(draft)
            return draft
    
    def update_draft_status(
        self,
        draft_id: int,
        status: DraftStatus
    ) -> Draft:
        """Update draft status."""
        with self.get_session() as session:
            draft = session.get(Draft, draft_id)
            if not draft:
                raise ValueError(f"Draft {draft_id} not found")
            
            draft.status = status
            session.flush()
            session.refresh(draft)
            return draft
    
    def get_drafts_by_workflow(self, workflow_id: int) -> List[Draft]:
        """Get all drafts for a workflow, ordered by version."""
        with self.get_session() as session:
            stmt = select(Draft).where(
                Draft.workflow_id == workflow_id
            ).order_by(Draft.version.desc())
            drafts = list(session.scalars(stmt).all())
            for draft in drafts:
                session.expunge(draft)
            return drafts
    
    def get_latest_draft(self, workflow_id: int) -> Optional[Draft]:
        """Get the latest draft for a workflow."""
        drafts = self.get_drafts_by_workflow(workflow_id)
        return drafts[0] if drafts else None
    
    # ========================================
    # Feedback Operations
    # ========================================
    
    def create_feedback(
        self,
        draft_id: int,
        feedback_type: FeedbackType,
        comments: Optional[str] = None
    ) -> Feedback:
        """Create user feedback."""
        with self.get_session() as session:
            feedback = Feedback(
                draft_id=draft_id,
                feedback_type=feedback_type,
                comments=comments
            )
            session.add(feedback)
            session.flush()
            session.refresh(feedback)
            session.expunge(feedback)
            return feedback
    
    def get_feedback_by_draft(self, draft_id: int) -> List[Feedback]:
        """Get all feedback for a draft."""
        with self.get_session() as session:
            stmt = select(Feedback).where(
                Feedback.draft_id == draft_id
            ).order_by(Feedback.created_at.desc())
            return list(session.scalars(stmt).all())
    
    # ========================================
    # Published Post Operations
    # ========================================
    
    def create_published_post(
        self,
        workflow_id: int,
        draft_id: int,
        twitter_post_id: Optional[str] = None,
        twitter_post_url: Optional[str] = None
    ) -> PublishedPost:
        """Create a published post record."""
        with self.get_session() as session:
            post = PublishedPost(
                workflow_id=workflow_id,
                draft_id=draft_id,
                twitter_post_id=twitter_post_id,
                twitter_post_url=twitter_post_url
            )
            session.add(post)
            session.flush()
            session.refresh(post)
            return post
    
    def get_published_post_by_workflow(
        self,
        workflow_id: int
    ) -> Optional[PublishedPost]:
        """Get published post for a workflow."""
        with self.get_session() as session:
            stmt = select(PublishedPost).where(
                PublishedPost.workflow_id == workflow_id
            )
            return session.scalar(stmt)
    
    def get_all_published_posts(self, limit: int = 100) -> List[PublishedPost]:
        """Get all published posts, most recent first."""
        with self.get_session() as session:
            stmt = select(PublishedPost).order_by(
                PublishedPost.published_at.desc()
            ).limit(limit)
            return list(session.scalars(stmt).all())
