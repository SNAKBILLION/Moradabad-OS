"""Unit tests for the intent pipeline.

Mocks GroqClient with a queue of canned responses. No network. The live
Groq integration test is in tests/integration and gated on GROQ_API_KEY.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from mos.intent import (
    InMemoryLlmCallSink,
    build_intent_from_brief,
)
from mos.intent.client import GroqApiError, GroqResponse
from mos.templates import default_registry


# --- Fake client ---------------------------------------------------------

class _FakeGroqClient:
    """Hand back a sequence of pre-canned responses or errors."""

    model = "llama-3.1-70b-versatile-fake"

    def __init__(
        self, responses: list[str | Exception]
    ) -> None:
        self._queue = list(responses)
        self.calls: list[tuple[str, str]] = []  # (system, user)

    def chat_json(self, *, system: str, user: str, temperature: float = 0.0):
        self.calls.append((system, user))
        if not self._queue:
            raise AssertionError("test exhausted fake responses")
        head = self._queue.pop(0)
        if isinstance(head, Exception):
            raise head
        return GroqResponse(content=head, raw_json={"choices": []}, model=self.model)


# --- Helpers -------------------------------------------------------------

def _valid_payload(brief_id: UUID) -> dict:
    """A DesignSpec dict that the Pydantic + template validators accept."""
    return {
        "schema_version": "1.0",
        "brief_id": str(brief_id),
        "product_family": "candle_holder",
        "template_id": "candle_holder_classic_v1",
        "dimensions": {
            "base_diameter": {"value": 80.0, "unit": "mm"},
            "neck_diameter": {"value": 50.0, "unit": "mm"},
            "height": {"value": 130.0, "unit": "mm"},
            "wall_thickness": {"value": 4.0, "unit": "mm"},
        },
        "material": {
            "alloy": "brass_70_30",
            "casting_method": "sand",
            "density_g_cm3": 8.53,
            "min_wall_mm": 3.0,
        },
        "finish": {
            "polish": "satin",
            "plating": "none",
            "lacquer": False,
            "patina": None,
        },
        "motif_refs": [],
        "quantity": 100,
        "target_unit_cost": None,
        "buyer_notes": "test",
    }


def _templates():
    return list(default_registry().values())


# --- Tests ---------------------------------------------------------------

class TestHappyPath:
    def test_first_attempt_succeeds(self):
        brief_id = uuid4()
        payload = _valid_payload(brief_id)
        client = _FakeGroqClient([json.dumps(payload)])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id,
            brief_text="hollow brass candle holder, 130mm tall",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is not None
        assert result.spec.template_id == "candle_holder_classic_v1"
        assert result.spec.brief_id == brief_id
        assert result.reason is None
        assert len(result.attempts) == 1
        assert sink.records[0].succeeded is True
        assert sink.records[0].attempt == 1


class TestRetry:
    def test_retries_on_invalid_json(self):
        brief_id = uuid4()
        payload = _valid_payload(brief_id)
        client = _FakeGroqClient(["not json at all", json.dumps(payload)])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id,
            brief_text="x",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is not None
        assert len(result.attempts) == 2
        assert sink.records[0].succeeded is False
        assert sink.records[1].succeeded is True
        # Second attempt's user prompt must include the retry feedback.
        _, user2 = client.calls[1]
        assert "REJECTED" in user2

    def test_retries_on_schema_violation(self):
        brief_id = uuid4()
        bad = _valid_payload(brief_id)
        bad["product_family"] = "not_a_real_family"
        good = _valid_payload(brief_id)
        client = _FakeGroqClient([json.dumps(bad), json.dumps(good)])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id,
            brief_text="x",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is not None
        assert len(result.attempts) == 2

    def test_retries_on_template_dimension_out_of_range(self):
        brief_id = uuid4()
        bad = _valid_payload(brief_id)
        bad["dimensions"]["height"]["value"] = 999.0  # over 250 max
        good = _valid_payload(brief_id)
        client = _FakeGroqClient([json.dumps(bad), json.dumps(good)])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id,
            brief_text="x",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is not None
        assert "outside declared range" in (sink.records[0].error or "")

    def test_gives_up_after_max_attempts(self):
        brief_id = uuid4()
        client = _FakeGroqClient(["bad", "still bad", "even worse"])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id,
            brief_text="x",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is None
        assert len(result.attempts) == 3
        assert "after 3 attempts" in (result.reason or "")
        assert all(r.succeeded is False for r in sink.records)


class TestBriefIdForcing:
    def test_overrides_llm_supplied_brief_id(self):
        """The system supplies brief_id; if the LLM hallucinates a different
        one, we overwrite it before validation. This prevents a class of
        retry-storms caused by the LLM forgetting which brief it's working on."""
        real_brief = uuid4()
        payload = _valid_payload(real_brief)
        payload["brief_id"] = str(uuid4())  # wrong
        client = _FakeGroqClient([json.dumps(payload)])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=real_brief,
            brief_text="x",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is not None
        assert result.spec.brief_id == real_brief


class TestNullTemplate:
    def test_accepts_template_id_null(self):
        """LLM saying 'no template fits' is a valid terminal output."""
        brief_id = uuid4()
        payload = _valid_payload(brief_id)
        payload["template_id"] = None
        payload["dimensions"] = {}
        client = _FakeGroqClient([json.dumps(payload)])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id,
            brief_text="something we don't have a template for",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is not None
        assert result.spec.template_id is None
        assert result.spec.dimensions == {}


class TestApiErrorBailsOut:
    def test_groq_error_does_not_retry(self):
        """Auth / rate-limit errors don't fix themselves on retry; bail
        immediately so we don't burn quota."""
        brief_id = uuid4()
        client = _FakeGroqClient([GroqApiError(401, "bad key")])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id,
            brief_text="x",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is None
        assert "Groq API error on attempt 1" in (result.reason or "")
        assert len(result.attempts) == 1


class TestNonObjectJson:
    def test_top_level_array_rejected(self):
        brief_id = uuid4()
        client = _FakeGroqClient([json.dumps([1, 2, 3]), json.dumps([])])
        # Three rejections needed to fully exhaust attempts.
        client = _FakeGroqClient(
            [json.dumps([1]), json.dumps([2]), json.dumps([3])]
        )
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id,
            brief_text="x",
            templates=_templates(),
            client=client,
            sink=sink,
        )
        assert result.spec is None
        assert "object at top level" in (sink.records[0].error or "")


class TestRepeatGuard:
    def test_identical_repeat_aborts_early(self):
        brief_id = uuid4()
        same_bad = "not json"
        client = _FakeGroqClient([same_bad, same_bad, same_bad])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id, brief_text="x",
            templates=_templates(), client=client, sink=sink,
        )
        assert result.spec is None
        assert "identical output" in (result.reason or "")
        # Bailed on second identical response — only 2 attempts recorded.
        assert len(result.attempts) == 2


class TestSizeGuard:
    def test_oversized_response_rejected(self):
        brief_id = uuid4()
        # 65 KB > MAX_RESPONSE_CHARS (64 KB).
        huge = "{" + ("a" * (65 * 1024)) + "}"
        client = _FakeGroqClient([huge, huge, huge])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id, brief_text="x",
            templates=_templates(), client=client, sink=sink,
        )
        assert result.spec is None
        assert "exceeds" in (sink.records[0].error or "")


class TestProductFamilyMismatch:
    def test_family_must_match_template(self):
        brief_id = uuid4()
        bad = _valid_payload(brief_id)
        bad["product_family"] = "bowl"  # template is candle_holder
        good = _valid_payload(brief_id)
        client = _FakeGroqClient([json.dumps(bad), json.dumps(good)])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id, brief_text="x",
            templates=_templates(), client=client, sink=sink,
        )
        assert result.spec is not None
        assert "does not match template" in (sink.records[0].error or "")


class TestNonFiniteDimensions:
    def test_infinity_rejected(self):
        brief_id = uuid4()
        bad = _valid_payload(brief_id)
        bad["dimensions"]["height"]["value"] = float("inf")
        # Use allow_nan=True so the encoder emits "Infinity" — the same
        # surface a misbehaving LLM would produce.
        bad_json = json.dumps(bad, allow_nan=True)
        client = _FakeGroqClient([bad_json, bad_json, bad_json])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id, brief_text="x",
            templates=_templates(), client=client, sink=sink,
        )
        assert result.spec is None
        assert "not a finite number" in (sink.records[0].error or "")


class TestSpecIdNotLlmControlled:
    def test_llm_supplied_spec_id_is_dropped(self):
        brief_id = uuid4()
        llm_spec_id = uuid4()
        payload = _valid_payload(brief_id)
        payload["spec_id"] = str(llm_spec_id)
        client = _FakeGroqClient([json.dumps(payload)])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id, brief_text="x",
            templates=_templates(), client=client, sink=sink,
        )
        assert result.spec is not None
        assert result.spec.spec_id != llm_spec_id


class TestTransient5xxRetries:
    def test_500_retries_until_max(self):
        brief_id = uuid4()
        client = _FakeGroqClient([
            GroqApiError(503, "service unavailable"),
            GroqApiError(503, "still unavailable"),
            GroqApiError(503, "give up now"),
        ])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id, brief_text="x",
            templates=_templates(), client=client, sink=sink,
        )
        assert result.spec is None
        assert len(result.attempts) == 3  # all three attempts spent

    def test_4xx_does_not_retry(self):
        brief_id = uuid4()
        client = _FakeGroqClient([
            GroqApiError(401, "bad key"),
            GroqApiError(401, "still bad"),
        ])
        sink = InMemoryLlmCallSink()
        result = build_intent_from_brief(
            brief_id=brief_id, brief_text="x",
            templates=_templates(), client=client, sink=sink,
        )
        assert result.spec is None
        assert len(result.attempts) == 1
