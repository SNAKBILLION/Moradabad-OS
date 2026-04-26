"""Unit tests for GroqClient. Uses httpx.MockTransport — no network."""

from __future__ import annotations

import json

import httpx
import pytest

from mos.intent import GroqApiError, GroqClient


def _make_client(handler) -> GroqClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, timeout=5.0)
    return GroqClient(api_key="test-key", http_client=http)


class TestGroqClient:
    def test_constructor_rejects_empty_key(self):
        with pytest.raises(ValueError):
            GroqClient(api_key="")

    def test_chat_json_happy_path(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"a": 1}'}}
                    ]
                },
            )

        client = _make_client(handler)
        resp = client.chat_json(system="sys", user="usr")
        assert resp.content == '{"a": 1}'
        assert captured["body"]["model"] == client.model
        assert (
            captured["body"]["response_format"]["type"] == "json_object"
        )
        assert captured["body"]["messages"][0]["role"] == "system"
        assert captured["body"]["messages"][1]["role"] == "user"
        assert captured["headers"]["authorization"] == "Bearer test-key"
        client.close()

    def test_4xx_raises_groq_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="invalid key")

        client = _make_client(handler)
        with pytest.raises(GroqApiError) as ei:
            client.chat_json(system="s", user="u")
        assert ei.value.status_code == 401
        client.close()

    def test_malformed_response_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        client = _make_client(handler)
        with pytest.raises(GroqApiError):
            client.chat_json(system="s", user="u")
        client.close()
