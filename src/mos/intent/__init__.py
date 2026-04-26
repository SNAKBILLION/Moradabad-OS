"""Intent layer: brief text -> validated DesignSpec via LLM.

Public surface:
  - build_intent_from_brief : the main entry point
  - GroqClient              : HTTP client (constructor takes api_key, model)
  - InMemoryLlmCallSink     : for tests; use LlmCallRepository in prod
  - IntentResult            : return type (spec | None, attempts, reason)

Internal:
  - prompt.py   : prompt assembly, versioned
  - client.py   : httpx-backed Groq client
  - pipeline.py : validation + retry loop
"""

from __future__ import annotations

from .client import GroqApiError, GroqClient, GroqResponse
from .pipeline import (
    MAX_ATTEMPTS,
    InMemoryLlmCallSink,
    IntentResult,
    LlmCallRecord,
    LlmCallSink,
    build_intent_from_brief,
)
from .prompt import (
    PROMPT_VERSION,
    build_system_prompt,
    build_user_prompt,
    prompt_hash,
)

__all__ = [
    "MAX_ATTEMPTS",
    "PROMPT_VERSION",
    "GroqApiError",
    "GroqClient",
    "GroqResponse",
    "InMemoryLlmCallSink",
    "IntentResult",
    "LlmCallRecord",
    "LlmCallSink",
    "build_intent_from_brief",
    "build_system_prompt",
    "build_user_prompt",
    "prompt_hash",
]
