import json
import time

import streamlit as st
import streamlit.components.v1 as components

from src.auth.oauth import (
    exchange_code_for_token,
    fetch_x_user_profile,
    start_oauth_flow,
    token_expires_at,
)
from src.config import get_settings
from src.database import DatabaseManager
from src.database.models import AuditAction, WorkflowPhase
from src.services import get_job_runner
from src.utils import RedditClient, TwitterClient
from src.utils.errors import AppError, friendly_error
from src.utils.logging_config import get_logger, setup_logging
from src.utils.rate_limiter import RateLimiter
from src.utils.sanitize import sanitize_feedback, sanitize_user_query
from src.workflow.graph import WorkflowGraph

setup_logging()
logger = get_logger(__name__)

PHASE_LABELS = {
    WorkflowPhase.PENDING.value: "Pending",
    WorkflowPhase.INTENT.value: "Understanding intent",
    WorkflowPhase.RESEARCH.value: "Researching Reddit",
    WorkflowPhase.FILTER.value: "Filtering content",
    WorkflowPhase.SUMMARIZE.value: "Summarizing insights",
    WorkflowPhase.DRAFT.value: "Drafting tweet",
    WorkflowPhase.DRAFT_READY.value: "Draft ready for review",
    WorkflowPhase.PUBLISHING.value: "Publishing",
    WorkflowPhase.PUBLISHED.value: "Published",
    WorkflowPhase.FAILED.value: "Failed",
    WorkflowPhase.CANCELLED.value: "Cancelled",
}

PRIVACY_TEXT = (
    "SignalDraft stores your X OAuth tokens encrypted, workflow queries, drafts, "
    "and audit events needed to run the service. We do not sell your data. "
    "Disconnect X anytime to remove stored tokens from this app."
)
TERMS_TEXT = (
    "By using SignalDraft you confirm you own the connected X account, accept that "
    "AI-generated drafts may be inaccurate, and agree to review content before publishing. "
    "You are responsible for posts published from your account."
)


def init_session():
    defaults = {
        "user_id": None,
        "x_username": None,
        "thread_id": None,
        "active_workflow_id": None,
        "revision_feedback": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_resource
def get_db():
    db = DatabaseManager()
    db.initialize_database()
    return db


@st.cache_resource
def get_workflow_graph():
    return WorkflowGraph(
        db_manager=get_db(),
        reddit_client=RedditClient(),
        twitter_client=None,
    )


def _query_param(params, name: str):
    value = params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def handle_oauth_callback(db: DatabaseManager):
    params = st.query_params
    code = _query_param(params, "code")
    state = _query_param(params, "state")
    if not code or not state:
        return
    try:
        verifier = db.consume_oauth_pkce(state)
        if not verifier:
            st.error("OAuth session expired or invalid. Click Connect with X again.")
            st.query_params.clear()
            return
        token_data = exchange_code_for_token(code, verifier, state=state)
        access_token = token_data["access_token"]
        profile = fetch_x_user_profile(access_token)
        user = db.upsert_user(profile["x_user_id"], profile["x_username"])
        db.save_oauth_token(
            user_id=user.id,
            access_token=access_token,
            refresh_token=token_data.get("refresh_token"),
            expires_at=token_expires_at(token_data.get("expires_in")),
        )
        db.create_audit_log(
            AuditAction.CONNECT_X,
            user_id=user.id,
            x_username=user.x_username,
        )
        st.session_state.user_id = user.id
        st.session_state.x_username = user.x_username
        st.session_state.pop("x_auth_url", None)
        st.query_params.clear()
        st.rerun()
    except Exception as exc:
        logger.exception("OAuth callback failed")
        st.error(f"X login failed: {friendly_error(exc)}")
        st.query_params.clear()


def disconnect_x(db: DatabaseManager):
    user_id = st.session_state.user_id
    username = st.session_state.x_username
    if user_id:
        db.delete_user_oauth_token(user_id)
        db.create_audit_log(
            AuditAction.DISCONNECT_X,
            user_id=user_id,
            x_username=username,
        )
    st.session_state.user_id = None
    st.session_state.x_username = None
    st.session_state.thread_id = None
    st.session_state.active_workflow_id = None
    st.rerun()


def render_login():
    settings = get_settings()
    st.subheader("Connect your X account")
    st.write(
        "Sign in with X to authorize this app. Posts are published only to **your** account after you approve a draft."
    )
    if not settings.is_oauth_configured():
        st.error("Server missing TWITTER_CLIENT_ID and TWITTER_CLIENT_SECRET.")
        return
    if not settings.encryption_key:
        st.error("Server missing ENCRYPTION_KEY for secure token storage.")
        return
    if st.button("Connect with X", type="primary"):
        try:
            auth_url, oauth_state, code_verifier = start_oauth_flow()
            get_db().save_oauth_pkce(oauth_state, code_verifier)
            st.session_state["x_auth_url"] = auth_url
            components.html(
                f"<script>window.top.location.href = {json.dumps(auth_url)};</script>",
                height=0,
                width=0,
            )
        except Exception as exc:
            st.error(friendly_error(exc))

    pending_auth = st.session_state.get("x_auth_url")
    if pending_auth:
        st.link_button("Open X authorization", pending_auth, type="primary")
        st.caption("Opens X in your browser. After approving, you return here automatically.")


def render_workflow_status(db: DatabaseManager, workflow_id: int, status_slot):
    workflow = db.get_workflow(workflow_id)
    if not workflow:
        return None
    label = PHASE_LABELS.get(workflow.phase.value, workflow.phase.value)
    status_slot.info(f"Workflow #{workflow_id}: **{label}**")
    return workflow


def poll_background_job(db, workflow_graph, job_runner, workflow_id: int, status_slot):
    workflow = render_workflow_status(db, workflow_id, status_slot)
    if not workflow:
        return

    future = job_runner.get_future(workflow_id)
    if future and not future.done():
        time.sleep(1.5)
        st.rerun()
        return

    if future and future.done():
        try:
            future.result()
        except Exception as exc:
            st.session_state.active_workflow_id = None
            st.error(friendly_error(exc))
            return

    if workflow.phase == WorkflowPhase.DRAFT_READY and workflow.thread_id:
        st.session_state.thread_id = workflow.thread_id
        st.session_state.active_workflow_id = None
        st.success("Draft ready for your review.")
        st.rerun()
    elif workflow.phase == WorkflowPhase.FAILED:
        st.session_state.active_workflow_id = None
        st.error(workflow.error_message or "Workflow failed.")
    else:
        st.session_state.active_workflow_id = None


def render_review(workflow_graph: WorkflowGraph, thread_id: str):
    state = workflow_graph.get_state(thread_id)
    draft = state.get("draft_content", "")
    st.subheader("Draft review")
    st.text_area("Tweet preview", value=draft, height=140, disabled=True)
    st.caption(f"{len(draft)}/280 characters")

    if state.get("summary"):
        with st.expander("Research summary"):
            st.write(state.get("summary"))
            trends = state.get("key_trends") or []
            if isinstance(trends, str):
                st.write(trends)
            else:
                for trend in trends:
                    st.write(f"- {trend}")

    col1, col2, col3 = st.columns(3)
    db = get_db()
    user_id = st.session_state.user_id
    limiter = RateLimiter(db)

    with col1:
        if st.button("Approve & publish", type="primary"):
            try:
                limiter.check_publish_limit(user_id)
                twitter_client = TwitterClient.from_user_id(user_id, db)
            except AppError as exc:
                st.error(exc.user_message)
                return
            except ValueError as exc:
                st.error(str(exc))
                return
            result = workflow_graph.resume(
                thread_id,
                {"approved": True, "revision_requested": False},
                twitter_client=twitter_client,
            )
            st.session_state.thread_id = None
            if result.get("published"):
                st.success("Published to your X account.")
                st.link_button("View post", result.get("tweet_url", ""))
            elif result.get("error"):
                st.error(friendly_error(Exception(result["error"])))
            else:
                st.warning("Workflow ended without publishing.")

    with col2:
        feedback = st.text_input("Revision feedback", key="revision_feedback")
        if st.button("Request revision"):
            try:
                clean_feedback = sanitize_feedback(feedback)
            except AppError as exc:
                st.warning(exc.user_message)
            else:
                workflow_graph.resume(
                    thread_id,
                    {
                        "revision_requested": True,
                        "revision_feedback": clean_feedback,
                        "approved": False,
                    },
                )
                st.rerun()

    with col3:
        if st.button("Reject"):
            workflow_graph.resume(
                thread_id,
                {"approved": False, "revision_requested": False, "rejected": True},
            )
            st.session_state.thread_id = None
            st.info("Draft rejected.")
            st.rerun()


def render_main(workflow_graph: WorkflowGraph):
    settings = get_settings()
    db = get_db()
    limiter = RateLimiter(db)
    user_id = st.session_state.user_id

    st.subheader("Create a post")
    query = st.text_input(
        "What should we research?",
        placeholder="What's happening in AI today?",
        max_chars=500,
    )

    status_slot = st.empty()
    if st.session_state.active_workflow_id:
        poll_background_job(
            db,
            workflow_graph,
            get_job_runner(workflow_graph, db),
            st.session_state.active_workflow_id,
            status_slot,
        )

    if st.button("Run agent pipeline", type="primary"):
        try:
            clean_query = sanitize_user_query(query)
            if not settings.is_llm_configured():
                st.error("No LLM configured. Set GOOGLE_API_KEY and/or GROQ_API_KEY.")
                return
            limiter.check_workflow_limit(user_id)
            limiter.check_llm_limit(user_id)
            workflow_id = workflow_graph.start_workflow(clean_query, user_id=user_id)
            db.create_audit_log(
                AuditAction.WORKFLOW_STARTED,
                user_id=user_id,
                workflow_id=workflow_id,
                x_username=st.session_state.x_username,
                details=clean_query[:200],
            )
            get_job_runner(workflow_graph, db).submit(
                workflow_id=workflow_id,
                user_query=clean_query,
                user_id=user_id,
                x_username=st.session_state.x_username,
            )
            st.session_state.active_workflow_id = workflow_id
            st.session_state.thread_id = None
            st.rerun()
        except AppError as exc:
            st.error(exc.user_message)
        except Exception as exc:
            st.error(friendly_error(exc))

    if st.session_state.thread_id and workflow_graph.is_interrupted(st.session_state.thread_id):
        render_review(workflow_graph, st.session_state.thread_id)

    with st.expander("Your recent workflows"):
        workflows = db.get_user_workflows(user_id, limit=10)
        if not workflows:
            st.write("No workflows yet.")
        for wf in workflows:
            phase = PHASE_LABELS.get(wf.phase.value, wf.phase.value)
            st.write(f"#{wf.id} — {wf.user_query[:80]} — **{phase}** / {wf.status.value}")

    with st.expander("Audit log"):
        logs = db.get_user_audit_logs(user_id, limit=15)
        if not logs:
            st.write("No audit events yet.")
        for entry in logs:
            st.write(
                f"{entry.created_at:%Y-%m-%d %H:%M} — **{entry.action.value}**"
                + (f" — {entry.details}" if entry.details else "")
            )


def render_sidebar(db: DatabaseManager):
    settings = get_settings()
    with st.sidebar:
        st.write(f"Connected as **@{st.session_state.x_username}**")
        if settings.is_postgres():
            st.caption("Database: Neon PostgreSQL")
        else:
            st.caption("Database: SQLite (dev fallback)")
        if st.button("Disconnect X"):
            disconnect_x(db)
        with st.expander("Privacy"):
            st.write(PRIVACY_TEXT)
        with st.expander("Terms of use"):
            st.write(TERMS_TEXT)
        st.caption("HTTPS is enforced by your hosting provider in production.")


def main():
    st.set_page_config(page_title="SignalDraft", page_icon="🐦", layout="centered")
    init_session()
    db = get_db()
    handle_oauth_callback(db)

    st.title("SignalDraft")
    st.caption("Hacker News + RSS research → AI draft → publish to your X account")

    if not st.session_state.user_id:
        render_login()
        return

    render_sidebar(db)

    if not get_settings().is_llm_configured():
        st.error("Server missing GOOGLE_API_KEY (primary) or GROQ_API_KEY (fallback).")

    render_main(get_workflow_graph())


if __name__ == "__main__":
    main()
