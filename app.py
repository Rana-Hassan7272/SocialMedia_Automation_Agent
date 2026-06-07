import time

import streamlit as st

from src.auth.oauth import (
    exchange_code_for_token,
    fetch_x_user_profile,
    start_oauth_flow,
    token_expires_at,
    unpack_oauth_state,
)
from src.config import get_settings
from src.database import DatabaseManager
from src.database.models import AuditAction, WorkflowPhase
from src.services import get_job_runner
from src.utils import RedditClient, TwitterClient
from src.utils.errors import AppError, friendly_error, friendly_x_login_error
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
        "sd_session": None,
        "legacy_x_mode": False,
        "thread_id": None,
        "active_workflow_id": None,
        "revision_feedback": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def restore_user_session(db: DatabaseManager):
    if st.session_state.get("user_id"):
        return
    token = st.session_state.get("sd_session") or _query_param(st.query_params, "sd_session")
    if not token:
        return
    user = db.get_app_session(token)
    if user:
        st.session_state.user_id = user.id
        st.session_state.x_username = user.x_username
        st.session_state.sd_session = token


DB_CACHE_VERSION = "oauth-v8"


@st.cache_resource
def get_db(_cache_version: str = DB_CACHE_VERSION):
    db = DatabaseManager()
    db.initialize_database()
    return db


@st.cache_resource
def get_workflow_graph(_cache_version: str = DB_CACHE_VERSION):
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


def _app_base_url() -> str:
    settings = get_settings()
    configured = settings.twitter_callback_url.strip()
    if not configured.endswith("/"):
        configured = f"{configured}/"
    try:
        headers = st.context.headers
        host = headers.get("X-Forwarded-Host") or headers.get("Host") or ""
        if host and "localhost" not in host:
            proto = headers.get("X-Forwarded-Proto", "https")
            base = f"{proto}://{host}".rstrip("/")
            return f"{base}/"
    except Exception:
        pass
    return configured


def get_twitter_client_for_user(user_id: int, db: DatabaseManager) -> TwitterClient:
    if st.session_state.get("legacy_x_mode"):
        return TwitterClient.from_legacy_env()
    return TwitterClient.from_user_id(user_id, db)


def handle_oauth_callback(db: DatabaseManager) -> bool:
    params = st.query_params
    oauth_error = _query_param(params, "error")
    if oauth_error:
        detail = _query_param(params, "error_description") or oauth_error
        st.session_state["oauth_error"] = f"X authorization failed: {detail}"
        st.query_params.clear()
        return True
    code = _query_param(params, "code")
    state = _query_param(params, "state")
    if not code or not state:
        return False
    if st.session_state.get("oauth_handled_code") == code:
        if st.session_state.get("user_id"):
            st.query_params.clear()
            return True
        st.session_state.pop("oauth_handled_code", None)
    try:
        pkce = unpack_oauth_state(state)
    except ValueError as exc:
        pkce = db.get_oauth_pkce(state)
        if not pkce:
            st.session_state["oauth_error"] = str(exc)
            st.query_params.clear()
            return True
    redirect_uri = pkce["redirect_uri"]
    st.session_state["oauth_handled_code"] = code
    try:
        with st.spinner("Completing X login — please wait..."):
            token_data = exchange_code_for_token(
                code,
                pkce["code_verifier"],
                redirect_uri=redirect_uri,
            )
            access_token = token_data["access_token"]
            profile = fetch_x_user_profile(
                access_token,
                id_token=token_data.get("id_token"),
                refresh_token=token_data.get("refresh_token"),
                allow_token_fallback=True,
            )
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
        session_token = db.create_app_session(user.id)
        st.session_state.user_id = user.id
        st.session_state.x_username = user.x_username
        st.session_state.sd_session = session_token
        st.session_state.pop("x_auth_url", None)
        st.session_state.pop("oauth_error", None)
        st.session_state.pop("oauth_handled_code", None)
        st.session_state["oauth_success"] = user.x_username
        st.query_params.clear()
        st.query_params["sd_session"] = session_token
        return True
    except Exception as exc:
        logger.exception("OAuth callback failed")
        st.session_state.pop("oauth_handled_code", None)
        st.session_state["oauth_error"] = friendly_x_login_error(exc)
        st.query_params.clear()
    return True


def disconnect_x(db: DatabaseManager):
    user_id = st.session_state.user_id
    username = st.session_state.x_username
    session_token = st.session_state.get("sd_session")
    if session_token:
        db.delete_app_session(session_token)
    if user_id:
        db.delete_user_oauth_token(user_id)
        db.create_audit_log(
            AuditAction.DISCONNECT_X,
            user_id=user_id,
            x_username=username,
        )
    st.session_state.user_id = None
    st.session_state.x_username = None
    st.session_state.sd_session = None
    st.session_state.legacy_x_mode = False
    st.session_state.thread_id = None
    st.session_state.active_workflow_id = None
    st.query_params.clear()
    st.rerun()


def render_login():
    settings = get_settings()
    st.subheader("Connect your X account")
    if not settings.is_oauth_configured():
        st.error("Server missing TWITTER_CLIENT_ID and TWITTER_CLIENT_SECRET.")
        return
    if not settings.encryption_key:
        st.error("Server missing ENCRYPTION_KEY for secure token storage.")
        return

    callback_url = _app_base_url()
    st.caption(f"OAuth callback URL: `{callback_url}`")
    oauth_error = st.session_state.get("oauth_error")
    if oauth_error:
        st.error(oauth_error)
        if st.button("Clear error and start over", type="secondary"):
            for key in (
                "oauth_error",
                "x_auth_url",
                "oauth_handled_code",
                "user_id",
                "x_username",
                "sd_session",
            ):
                st.session_state.pop(key, None)
            st.query_params.clear()
            st.rerun()

    st.markdown("#### Step 1 — Log into X first")
    st.link_button("Open x.com and log in", "https://x.com", type="secondary")
    st.caption(
        "Use your **X email/username + password** on x.com. "
        "Do **not** use “Sign in with Google” — that causes FedCM console errors."
    )

    st.markdown("#### Step 2 — Authorize SignalDraft")
    if st.button("Prepare authorization link", type="primary"):
        try:
            st.session_state.pop("oauth_handled_code", None)
            st.session_state.pop("oauth_error", None)
            st.session_state["x_auth_url"] = start_oauth_flow(redirect_uri=callback_url)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    auth_url = st.session_state.get("x_auth_url")
    if not auth_url:
        st.caption("Click **Prepare authorization link** first, then open X in the new tab.")
        return

    st.markdown(
        f'<a href="{auth_url}" target="_blank" rel="noopener noreferrer" '
        f'style="display:inline-block;padding:0.65rem 1.25rem;background:#1DA1F2;'
        f'color:white;text-decoration:none;border-radius:0.45rem;font-weight:600;">'
        f"Authorize SignalDraft on X (new tab) →</a>",
        unsafe_allow_html=True,
    )

    st.markdown("#### Step 3 — Finish on the redirect tab")
    st.info(
        "On X click **Authorize app** (not only log in). "
        "X sends you back to SignalDraft in **that same tab** with "
        "**Completing X login…** then **Connected as @you**.\n\n"
        "**Ignore browser console errors** like FedCM / GSI_LOGGER — those are from "
        "X’s Google sign-in button, not SignalDraft."
    )

    with st.expander("Still stuck? Troubleshooting"):
        st.markdown(
            f"""
1. Log into [x.com](https://x.com) with **email/password** (not Google).
2. Click **Authorize SignalDraft on X** above — opens a **new tab**.
3. On the X page, if asked to log in again, use **username/password** on that page.
4. Click **Authorize** / **Allow** for SignalDraft.
5. Stay in the tab X redirects to (`{callback_url}`) — do not switch tabs.
6. Try **Chrome Incognito** or **Firefox** if Chrome blocks sign-in.
7. Callback URL in X Developer Portal must be exactly: `{callback_url}`
            """
        )
        st.code(auth_url, language=None)
        st.warning(
            "If X shows **Something went wrong** before Authorize: click **Clear error**, "
            "**Prepare authorization link** again, and use a fresh link. Do not reuse an old tab."
        )

    if settings.is_twitter_configured():
        st.divider()
        st.markdown("#### Alternative — your X account (legacy keys)")
        st.caption(
            "Skips OAuth 2.0. Add TWITTER_API_KEY, TWITTER_API_SECRET, "
            "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET to Streamlit secrets."
        )
        if st.button("Continue with legacy X keys", type="secondary"):
            try:
                client = TwitterClient.from_legacy_env()
                me = client.client.get_me(user_fields=["username"])
                username = me.data.username if me.data else "legacy_user"
                user = get_db().upsert_user(str(me.data.id), username)
                st.session_state.user_id = user.id
                st.session_state.x_username = username
                st.session_state.legacy_x_mode = True
                st.session_state.pop("oauth_error", None)
                st.rerun()
            except Exception as exc:
                st.error(friendly_x_login_error(exc))


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
                twitter_client = get_twitter_client_for_user(user_id, db)
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
    restore_user_session(db)
    handle_oauth_callback(db)
    restore_user_session(db)

    st.title("SignalDraft")
    st.caption("Hacker News + RSS research → AI draft → publish to your X account")

    oauth_success = st.session_state.pop("oauth_success", None)
    if oauth_success:
        if oauth_success == "connected_user":
            st.success("Connected to X. You can create posts below.")
        else:
            st.success(f"Connected as **@{oauth_success}**. You can create posts below.")

    if not st.session_state.user_id:
        render_login()
        return

    render_sidebar(db)

    if not get_settings().is_llm_configured():
        st.error("Server missing GOOGLE_API_KEY (primary) or GROQ_API_KEY (fallback).")

    render_main(get_workflow_graph())


if __name__ == "__main__":
    main()
