"""
Base agent class for all workflow agents.
Provides LLM integration with Google Gemini primary and Groq fallback.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from ..config import get_settings
from ..utils.llm_provider import FallbackChatModel
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """
    Abstract base class for all agents in the workflow.
    Uses Google Gemini as primary LLM and Groq as fallback.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ):
        settings = get_settings()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.llm = FallbackChatModel(
            temperature=temperature,
            max_tokens=max_tokens,
            groq_model=model or settings.groq_model,
            google_model=settings.google_gemini_model,
        )
        self.model_name = self.llm.model_label

    @abstractmethod
    def get_system_prompt(self) -> str:
        pass

    @abstractmethod
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        pass

    def invoke_llm(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        system = system_prompt or self.get_system_prompt()
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user_message),
        ]
        try:
            logger.debug("%s invoking LLM (%s)", self.__class__.__name__, self.model_name)
            response = self.llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error("%s LLM failed: %s", self.__class__.__name__, e)
            raise RuntimeError(f"LLM invocation failed: {str(e)}") from e

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model_name})"
