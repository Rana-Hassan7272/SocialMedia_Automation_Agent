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

DEMO_URL = "https://tinyurl.com/signaldraft"
LIVE_URL = "https://signaldraft.streamlit.app/"
GITHUB_URL = "https://github.com/Rana-Hassan7272/SocialMedia_Automation_Agent"
CONTACT_EMAIL = "ssc.shahbaz.2004@gmail.com"

PHASE_LABELS = {
    WorkflowPhase.PENDING.value: "Starting",
    WorkflowPhase.INTENT.value: "Understanding your topic",
    WorkflowPhase.RESEARCH.value: "Researching Hacker News & RSS",
    WorkflowPhase.FILTER.value: "Filtering best signals",
    WorkflowPhase.SUMMARIZE.value: "Summarizing insights",
    WorkflowPhase.DRAFT.value: "Writing your draft",
    WorkflowPhase.DRAFT_READY.value: "Ready for your review",
    WorkflowPhase.PUBLISHING.value: "Publishing to X",
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


def inject_styles():
    st.markdown(
        """
        <style>
        .sd-hero {
            padding: 1.5rem 0 0.5rem 0;
        }
        .sd-tagline {
            font-size: 1.15rem;
            color: #9FB3C8;
            margin-bottom: 1.25rem;
        }
        .sd-card {
            background: linear-gradient(135deg, #151B24 0%, #1A2332 100%);
            border: 1px solid #243044;
            border-radius: 14px;
            padding: 1.1rem 1.25rem;
            margin-bottom: 0.85rem;
        }
        .sd-card h4 {
            margin: 0 0 0.35rem 0;
            color: #F4F7FB;
        }
        .sd-card p {
            margin: 0;
            color: #9FB3C8;
            font-size: 0.95rem;
        }
        .sd-pill {
            display: inline-block;
            background: #1DA1F2;
            color: white;
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            margin-right: 0.4rem;
            margin-bottom: 0.4rem;
        }
        .sd-access {
            background: #122033;
            border: 1px solid #1DA1F2;
            border-radius: 12px;
            padding: 1rem 1.2rem;
            margin: 1rem 0 1.25rem 0;
        }
        .sd-connect-btn a {
            display: inline-block;
            padding: 0.7rem 1.4rem;
            background: #1DA1F2;
            color: white !important;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
        }
        div[data-testid="stStatusWidget"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
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


DB_CACHE_VERSION = "live-v1"


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
        st.session_state["oauth_error"] = "X authorization was cancelled. Try again when ready."
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
            st.session_state["oauth_error"] = friendly_x_login_error(exc)
            st.query_params.clear()
            return True
    redirect_uri = pkce["redirect_uri"]
    st.session_state["oauth_handled_code"] = code
    try:
        with st.spinner("Connecting your X account…"):
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


def render_hero():
    st.markdown('<div class="sd-hero">', unsafe_allow_html=True)
    st.title("SignalDraft")
    st.markdown(
        '<p class="sd-tagline">Turn live news into publish-ready X posts — researched, drafted, '
        "and posted only after you approve.</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<span class="sd-pill">Live</span>'
        '<span class="sd-pill">Human-in-the-loop</span>'
        '<span class="sd-pill">Multi-agent AI</span>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_features():
    features = [
        ("Research", "Scans Hacker News and RSS for real-time signals on your topic."),
        ("Draft", "Gemini writes a concise, on-brand tweet from what matters most."),
        ("Review", "You approve, revise, or reject — nothing posts without you."),
        ("Publish", "One click sends the approved draft to your connected X account."),
    ]
    cols = st.columns(2)
    for idx, (title, body) in enumerate(features):
        with cols[idx % 2]:
            st.markdown(
                f'<div class="sd-card"><h4>{title}</h4><p>{body}</p></div>',
                unsafe_allow_html=True,
            )


def render_demo_and_access():
    st.markdown("### See it in action")
    st.link_button("Watch full demo", DEMO_URL, type="primary", use_container_width=False)
    st.caption("End-to-end flow: research → AI draft → human approval → post to X.")

    st.markdown(
        """
        <div class="sd-access">
        <strong>Invite-only access</strong><br>
        The app is live and fully built. X API is <em>pay-as-you-go</em> — new accounts need
        billing enabled on the X Developer Portal before posting works.
        <br><br>
        Want to use SignalDraft? Email <a href="mailto:ssc.shahbaz.2004@gmail.com">ssc.shahbaz.2004@gmail.com</a>
        and I will enable your account.
        </div>
        """,
        unsafe_allow_html=True,
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.link_button("Email for access", f"mailto:{CONTACT_EMAIL}", type="primary")
    with col_b:
        st.link_button("GitHub", GITHUB_URL, type="secondary")


def render_login():
    settings = get_settings()
    if not settings.is_oauth_configured() or not settings.encryption_key:
        st.info("Sign-in is being configured. Watch the demo above or contact us for access.")
        return

    st.markdown("### Connect your X account")
    oauth_error = st.session_state.get("oauth_error")
    if oauth_error:
        st.error(oauth_error)
        if st.button("Try again", type="secondary"):
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

    callback_url = _app_base_url()
    if st.button("Connect to X", type="primary", use_container_width=True):
        try:
            st.session_state.pop("oauth_handled_code", None)
            st.session_state.pop("oauth_error", None)
            st.session_state["x_auth_url"] = start_oauth_flow(redirect_uri=callback_url)
            st.rerun()
        except Exception:
            st.error("Could not start X login. Please try again.")

    auth_url = st.session_state.get("x_auth_url")
    if auth_url:
        st.markdown(
            f'<div class="sd-connect-btn"><a href="{auth_url}" target="_blank" '
            f'rel="noopener noreferrer">Authorize on X →</a></div>',
            unsafe_allow_html=True,
        )
        st.caption("Log into X, click Authorize, then return here to finish.")

    if settings.is_twitter_configured():
        if st.button("Continue with pre-enabled account", type="secondary"):
            try:
                client = TwitterClient.from_legacy_env()
                me = client.client.get_me(user_fields=["username"])
                username = me.data.username if me.data else "user"
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
    status_slot.info(f"**{label}** — agents are working on your request.")
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
        st.success("Your draft is ready for review.")
        st.rerun()
    elif workflow.phase == WorkflowPhase.FAILED:
        st.session_state.active_workflow_id = None
        st.error("We could not finish this request. Try a different topic.")
    else:
        st.session_state.active_workflow_id = None


def render_review(workflow_graph: WorkflowGraph, thread_id: str):
    state = workflow_graph.get_state(thread_id)
    draft = state.get("draft_content", "")
    st.subheader("Review your draft")
    st.text_area("Tweet preview", value=draft, height=140, disabled=True)
    st.caption(f"{len(draft)} / 280 characters")

    if state.get("summary"):
        with st.expander("What the agents found"):
            st.write(state.get("summary"))
            trends = state.get("key_trends") or []
            if isinstance(trends, str):
                st.write(trends)
            else:
                for trend in trends:
                    st.write(f"• {trend}")

    col1, col2, col3 = st.columns(3)
    db = get_db()
    user_id = st.session_state.user_id
    limiter = RateLimiter(db)

    with col1:
        if st.button("Approve & publish", type="primary", use_container_width=True):
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
                st.warning("Draft was not published.")

    with col2:
        feedback = st.text_input("Revision notes", key="revision_feedback", placeholder="Make it shorter…")
        if st.button("Request revision", use_container_width=True):
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
        if st.button("Reject", use_container_width=True):
            workflow_graph.resume(
                thread_id,
                {"approved": False, "revision_requested": False, "rejected": True},
            )
            st.session_state.thread_id = None
            st.info("Draft discarded.")
            st.rerun()


def render_main(workflow_graph: WorkflowGraph):
    settings = get_settings()
    db = get_db()
    limiter = RateLimiter(db)
    user_id = st.session_state.user_id

    st.subheader("Create a post")
    query = st.text_input(
        "What should we research?",
        placeholder="e.g. Latest breakthroughs in AI agents",
        max_chars=500,
        label_visibility="collapsed",
    )
    st.caption("Enter a topic — agents will research, draft, and pause for your approval.")

    status_slot = st.empty()
    if st.session_state.active_workflow_id:
        poll_background_job(
            db,
            workflow_graph,
            get_job_runner(workflow_graph, db),
            st.session_state.active_workflow_id,
            status_slot,
        )

    if st.button("Start research & draft", type="primary", use_container_width=True):
        try:
            clean_query = sanitize_user_query(query)
            if not settings.is_llm_configured():
                st.error("AI service is not available right now. Please try again later.")
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
        st.divider()
        render_review(workflow_graph, st.session_state.thread_id)

    workflows = db.get_user_workflows(user_id, limit=5)
    if workflows:
        with st.expander("Recent requests"):
            for wf in workflows:
                phase = PHASE_LABELS.get(wf.phase.value, wf.phase.value)
                st.write(f"**{wf.user_query[:70]}** — {phase}")


def render_sidebar(db: DatabaseManager):
    username = st.session_state.x_username
    display = username if username and username != "connected_user" else "your account"
    with st.sidebar:
        st.markdown(f"**@{display}**")
        st.caption("Connected to X")
        if st.button("Disconnect", use_container_width=True):
            disconnect_x(db)
        st.divider()
        st.link_button("Full demo", DEMO_URL, use_container_width=True)
        with st.expander("Privacy"):
            st.write(PRIVACY_TEXT)
        with st.expander("Terms"):
            st.write(TERMS_TEXT)


def main():
    st.set_page_config(
        page_title="SignalDraft",
        page_icon="🐦",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    inject_styles()
    init_session()
    db = get_db()
    restore_user_session(db)
    handle_oauth_callback(db)
    restore_user_session(db)

    oauth_success = st.session_state.pop("oauth_success", None)
    if oauth_success:
        if oauth_success == "connected_user":
            st.success("Connected to X. You're ready to create posts.")
        else:
            st.success(f"Connected as @{oauth_success}. You're ready to create posts.")

    if not st.session_state.user_id:
        render_hero()
        render_features()
        st.divider()
        render_demo_and_access()
        st.divider()
        render_login()
        return

    render_sidebar(db)
    st.title("SignalDraft")
    st.caption("Research → draft → approve → publish")

    if not get_settings().is_llm_configured():
        st.warning("AI drafting is temporarily unavailable.")

    render_main(get_workflow_graph())


if __name__ == "__main__":
    main()
