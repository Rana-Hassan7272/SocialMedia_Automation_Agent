from src.auth.oauth import probe_authorize_url, start_oauth_flow
from src.config import get_settings


def main():
    settings = get_settings()
    print("X OAuth 2.0 diagnostic\n")
    print("=" * 60)

    client_id = (settings.twitter_client_id or "").strip()
    callback = settings.twitter_callback_url.strip()

    print(f"\nCallback URL : {callback}")
    print(f"Client ID    : {client_id[:12]}... ({len(client_id)} chars)" if client_id else "Client ID    : MISSING")

    if not settings.is_oauth_configured():
        print("\nFAIL: Set TWITTER_CLIENT_ID and TWITTER_CLIENT_SECRET")
        return

    if len(client_id) < 20:
        print("\nWARN: Use OAuth 2.0 Client ID from User authentication settings")

    try:
        result = probe_authorize_url()
        print(f"\nAuthorize probe HTTP status: {result['http_status']}")
        print(f"Redirect URI sent: {result['redirect_uri']}")
        if result["location"]:
            print(f"Location header: {result['location'][:120]}...")
        if result["http_status"] >= 400:
            print("\nFAIL: X rejected authorize URL (400 = callback URL mismatch in portal)")
            print("Fix: set TWITTER_CALLBACK_URL with trailing slash:")
            print("  https://signaldraft.streamlit.app/")
            print("Add the same URL in X Developer Portal callback list.")
        else:
            print("\nOK: Authorize URL accepted by X (open in browser to finish login)")
            print(result["authorize_url"][:140] + "...")
    except Exception as exc:
        print(f"\nProbe failed: {exc}")
        url = start_oauth_flow()
        print(url[:140] + "...")


if __name__ == "__main__":
    main()
