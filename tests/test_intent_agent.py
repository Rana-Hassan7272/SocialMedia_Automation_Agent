"""
Test Intent Understanding Agent.
"""

import pytest
import json
from unittest.mock import Mock, patch
from src.agents.intent_agent import IntentAgent
from src.database import DatabaseManager
from src.workflow.state import create_initial_state


@pytest.fixture
def mock_db():
    return Mock(spec=DatabaseManager)


def test_system_prompt(mock_db):
    agent = IntentAgent(db_manager=mock_db)
    prompt = agent.get_system_prompt()

    assert "topic" in prompt.lower()
    assert "scope" in prompt.lower()
    assert "tone" in prompt.lower()
    assert "json" in prompt.lower()


@patch.object(IntentAgent, "invoke_llm")
def test_process_extracts_intent(mock_invoke, mock_db):
    mock_invoke.return_value = json.dumps({
        "topic": "cryptocurrency",
        "scope": "today",
        "tone": "informative",
    })

    agent = IntentAgent(db_manager=mock_db)
    state = create_initial_state("What's happening in crypto today?", 1)
    result = agent.process(state)

    assert result["topic"] == "cryptocurrency"
    assert result["scope"] == "today"
    assert result["tone"] == "informative"
    assert "error" not in result


@patch.object(IntentAgent, "invoke_llm")
def test_process_saves_to_database(mock_invoke, mock_db):
    raw = json.dumps({
        "topic": "AI regulation",
        "scope": "latest in Europe",
        "tone": "informative",
    })
    mock_invoke.return_value = raw

    agent = IntentAgent(db_manager=mock_db)
    state = create_initial_state("Get latest AI regulation news in Europe", 1)
    agent.process(state)

    mock_db.create_intent.assert_called_once_with(
        workflow_id=1,
        topic="AI regulation",
        scope="latest in Europe",
        tone="informative",
        raw_intent=raw,
    )


@patch.object(IntentAgent, "invoke_llm")
def test_process_handles_invalid_json(mock_invoke, mock_db):
    mock_invoke.return_value = "Not valid JSON"

    agent = IntentAgent(db_manager=mock_db)
    state = create_initial_state("Test query", 1)
    result = agent.process(state)

    assert "error" in result
    assert "parse" in result["error"].lower()


def test_process_with_empty_query(mock_db):
    agent = IntentAgent(db_manager=mock_db)
    state = {"workflow_id": 1, "user_query": ""}
    result = agent.process(state)

    assert "error" in result
    assert "no user query" in result["error"].lower()


@patch.object(IntentAgent, "invoke_llm")
def test_multiple_queries(mock_invoke, mock_db):
    test_cases = [
        {
            "query": "Latest tech news",
            "response": {"topic": "technology", "scope": "latest", "tone": "informative"},
        },
        {
            "query": "Political updates this week",
            "response": {"topic": "politics", "scope": "this week", "tone": "informative"},
        },
        {
            "query": "What's trending in AI?",
            "response": {"topic": "AI", "scope": "trending", "tone": "informative"},
        },
    ]

    agent = IntentAgent(db_manager=mock_db)
    for test_case in test_cases:
        mock_invoke.return_value = json.dumps(test_case["response"])
        state = create_initial_state(test_case["query"], 1)
        result = agent.process(state)

        assert result["topic"] == test_case["response"]["topic"]
        assert result["scope"] == test_case["response"]["scope"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
