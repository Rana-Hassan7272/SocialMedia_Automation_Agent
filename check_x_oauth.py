from src.auth.oauth import build_authorization_url, generate_code_verifier, generate_oauth_state
from src.config import get_settings


def main():
    settings = get_settings()
    print("X OAuth 2.0 diagnostic\n")
    print("=" * 60)

    client_id = (settings.twitter_client_id or "").strip()
    callback = settings.twitter_callback_url.rstrip("/")

    print(f"\nCallback URL : {callback}")
    print(f"Client ID    : {client_id[:8]}... ({len(client_id)} chars)" if client_id else "Client ID    : MISSING")

    if not settings.is_oauth_configured():
        print("\nFAIL: Set TWITTER_CLIENT_ID and TWITTER_CLIENT_SECRET in .env")
        print("Use OAuth 2.0 Client ID from X portal (NOT the OAuth 1.0 API Key).")
        return

    if len(client_id) < 20:
        print("\nWARN: Client ID looks too short.")
        print("TWITTER_CLIENT_ID must be OAuth 2.0 Client ID, not OAuth 1.0 API Key.")

    state = generate_oauth_state()
    verifier = generate_code_verifier()
    url = build_authorization_url(state, verifier)

    print("\nX Developer Portal must have:")
    print("  - User authentication: OAuth 2.0 ON")
    print("  - Type of App: Web App")
    print("  - App permissions: Read and write")
    print(f"  - Callback URL: {callback}")
    print(f"  - Website URL: {callback}")

    print("\nSample authorization URL (open in browser to test):")
    print(url[:120] + "...")

    print("\nIf X shows 400:")
    print("  1. Callback URL in portal must match exactly (no trailing slash)")
    print("  2. Use OAuth 2.0 Client ID + Secret (not API Key / Access Token)")
    print("  3. Enable OAuth 2.0 under User authentication settings")
    print("  4. Try incognito browser or log into x.com first")


if __name__ == "__main__":
    main()
