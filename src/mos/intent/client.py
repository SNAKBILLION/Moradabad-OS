"""Groq chat-completions client.

A deliberate reduction: no SDK, no streaming, no tool-use. One synchronous
method that takes a system prompt + user prompt and returns the raw response
text. Validation, retries, and schema enforcement live at a higher layer
(see mos.intent.pipeline) where they belong.

Reasons for hand-rolling instead of using groq-python:
  - This module's surface is ~30 lines of real work; the SDK is heavier.
  - We already have httpx as a dep.
  - Fewer transitive version pins, fewer surprises.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_DEFAULT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 60.0


class GroqApiError(RuntimeError):
    """Raised for non-2xx HTTP responses from Groq."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Groq API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class GroqResponse:
    """Captured for storage. `raw_json` is the full JSON body from Groq —
    we persist it for replay + audit rather than just the extracted content."""

    content: str
    raw_json: dict
    model: str


class GroqClient:
    """Synchronous Groq chat-completions client.

    Thread-safe — the underlying httpx.Client is not recreated per call, and
    httpx.Client is documented as thread-safe for request sending.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "llama-3.1-70b-versatile",
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout_seconds)

    @property
    def model(self) -> str:
        return self._model

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
    ) -> GroqResponse:
        """One-shot chat completion with JSON response mode enforced.

        Returns the assistant message content (expected to be a JSON string)
        plus the full response body for auditing. Callers do the JSON parsing
        and schema validation themselves.
        """
        body = {
            "model": self._model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        resp = self._http.post(self._endpoint, headers=headers, json=body)
        if resp.status_code >= 400:
            raise GroqApiError(resp.status_code, resp.text[:500])
        payload = resp.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise GroqApiError(
                resp.status_code,
                f"unexpected response shape: missing choices[0].message.content ({e})",
            ) from e
        return GroqResponse(content=content, raw_json=payload, model=self._model)
