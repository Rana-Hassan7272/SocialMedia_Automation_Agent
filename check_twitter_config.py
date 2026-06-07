from src.config import get_settings


def main():
    settings = get_settings()
    print("X / Twitter configuration check\n")
    print("=" * 60)

    print("\n1. OAuth 2.0 (Streamlit multi-user app)")
    oauth_fields = {
        "TWITTER_CLIENT_ID": settings.twitter_client_id,
        "TWITTER_CLIENT_SECRET": settings.twitter_client_secret,
        "TWITTER_CALLBACK_URL": settings.twitter_callback_url,
        "ENCRYPTION_KEY": settings.encryption_key,
    }
    for name, value in oauth_fields.items():
        if value and len(str(value)) > 3:
            print(f"   OK  {name}")
        else:
            print(f"   MISSING  {name}")

    print(f"\n   OAuth ready: {settings.is_oauth_configured() and bool(settings.encryption_key)}")
    if settings.twitter_client_id and len(settings.twitter_client_id.strip()) < 20:
        print("   WARN: TWITTER_CLIENT_ID looks like OAuth 1.0 API Key.")
        print("         Use OAuth 2.0 Client ID from X portal User authentication settings.")
    print(f"   Callback: {settings.twitter_callback_url}")

    print("\n2. Legacy single-account keys (CLI demos)")
    legacy = {
        "API Key": settings.twitter_api_key,
        "API Secret": settings.twitter_api_secret,
        "Access Token": settings.twitter_access_token,
        "Access Token Secret": settings.twitter_access_token_secret,
    }
    for name, value in legacy.items():
        if value and len(value) > 5:
            print(f"   OK  {name}")
        else:
            print(f"   MISSING  {name}")

    print(f"\n   Legacy ready: {settings.is_twitter_configured()}")

    print("\n3. LLM")
    print(f"   {'OK' if settings.is_google_configured() else 'MISSING'}  GOOGLE_API_KEY (primary, {settings.google_gemini_model})")
    print(f"   {'OK' if settings.is_groq_configured() else 'MISSING'}  GROQ_API_KEY (fallback)")

    print("\n" + "=" * 60)
    print("\nStreamlit app:  streamlit run app.py")
    print("Generate ENCRYPTION_KEY:  python generate_encryption_key.py")


if __name__ == "__main__":
    main()
