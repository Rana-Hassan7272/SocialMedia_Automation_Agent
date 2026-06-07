from unittest.mock import Mock, patch

import pytest

from src.utils.llm_provider import FallbackChatModel, should_fallback_to_groq


def test_should_fallback_on_rate_limit():
    assert should_fallback_to_groq(Exception("429 rate limit exceeded"))
    assert should_fallback_to_groq(Exception("Quota exceeded for metric"))


def test_should_not_fallback_on_invalid_key():
    assert not should_fallback_to_groq(Exception("invalid api key provided"))


@patch("src.utils.llm_provider.get_settings")
def test_fallback_to_groq_on_gemini_limit(mock_settings):
    settings = Mock()
    settings.is_google_configured.return_value = True
    settings.is_groq_configured.return_value = True
    settings.google_api_key = "google-key"
    settings.google_gemini_model = "gemini-3.1-flash-lite"
    settings.groq_api_key = "groq-key"
    settings.groq_model = "llama-3.3-70b-versatile"
    mock_settings.return_value = settings

    llm = FallbackChatModel(temperature=0.3)
    primary_response = Mock(content="from gemini")
    fallback_response = Mock(content="from groq")

    with patch.object(llm, "_invoke_google", side_effect=Exception("429 quota exceeded")), patch.object(
        llm, "_invoke_groq", return_value=fallback_response
    ) as groq_call:
        result = llm.invoke([])
        assert result.content == "from groq"
        groq_call.assert_called_once()
