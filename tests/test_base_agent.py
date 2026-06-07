"""
Test base agent functionality and Groq integration.
"""

import pytest
from unittest.mock import Mock, patch
from src.agents.base_agent import BaseAgent
from src.workflow.state import WorkflowState, create_initial_state


class TestAgent(BaseAgent):
    """Concrete test agent for testing BaseAgent."""
    
    def get_system_prompt(self) -> str:
        return "You are a helpful test assistant."
    
    def process(self, state):
        # Simple test implementation
        state["test_processed"] = True
        return state


def test_base_agent_initialization():
    """Test base agent initializes with Groq LLM."""
    agent = TestAgent()
    
    assert agent.llm is not None
    assert agent.temperature == 0.7
    assert agent.model_name is not None


def test_base_agent_custom_parameters():
    """Test base agent with custom parameters."""
    agent = TestAgent(
        temperature=0.5,
        max_tokens=1000
    )
    
    assert agent.temperature == 0.5
    assert agent.max_tokens == 1000


def test_get_system_prompt():
    """Test system prompt retrieval."""
    agent = TestAgent()
    prompt = agent.get_system_prompt()
    
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_process_method():
    """Test process method on state."""
    agent = TestAgent()
    state = {"workflow_id": 1, "user_query": "test"}
    
    result = agent.process(state)
    
    assert result["test_processed"] is True


@patch('src.agents.base_agent.FallbackChatModel')
def test_invoke_llm(mock_llm):
    """Test LLM invocation."""
    mock_response = Mock()
    mock_response.content = "Test response"
    mock_llm.return_value.invoke.return_value = mock_response
    mock_llm.return_value.model_label = "google:gemini-3.1-flash-lite"
    
    agent = TestAgent()
    response = agent.invoke_llm("Test message")
    
    assert response == "Test response"


def test_agent_repr():
    """Test agent string representation."""
    agent = TestAgent()
    repr_str = repr(agent)
    
    assert "TestAgent" in repr_str
    assert "model=" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
