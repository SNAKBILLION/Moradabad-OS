"""Intent pipeline: brief text -> validated DesignSpec.

Flow:
  1. Build system and user prompts from template registry + brief.
  2. Call Groq, record the raw request/response regardless of outcome.
  3. Parse JSON. On failure, retry up to MAX_ATTEMPTS with a feedback hint.
  4. Validate against DesignSpec schema. On failure, same retry path.
  5. After MAX_ATTEMPTS failures, return None. Caller puts job in
     AWAITING_REVIEW.

This module does NOT mutate the database; the LLM-call logger is injected so
tests can use an in-memory sink and production uses a repository-backed sink.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import ValidationError

from mos.intent.client import GroqApiError, GroqClient, GroqResponse
from mos.intent.prompt import (
    PROMPT_VERSION,
    build_system_prompt,
    build_user_prompt,
    prompt_hash,
    retry_feedback,
)
from mos.schemas import DesignSpec
from mos.templates import Template

MAX_ATTEMPTS = 3
MAX_RESPONSE_CHARS = 64 * 1024  # bound parser cost; DesignSpec JSON is < 4 KB


@dataclass(frozen=True)
class LlmCallRecord:
    """One row in the llm_calls log. Written append-only."""

    call_id: UUID
    brief_id: UUID
    prompt_version: str
    prompt_hash: str
    model: str
    attempt: int  # 1-indexed
    succeeded: bool
    error: str | None
    system_prompt: str
    user_prompt: str
    raw_response: str
    created_at: datetime


@runtime_checkable
class LlmCallSink(Protocol):
    def record(self, call: LlmCallRecord) -> None: ...


class InMemoryLlmCallSink:
    """Default sink for unit tests — keeps records in a list."""

    def __init__(self) -> None:
        self.records: list[LlmCallRecord] = []

    def record(self, call: LlmCallRecord) -> None:
        self.records.append(call)


@dataclass(frozen=True)
class IntentResult:
    """Outcome of running the intent pipeline on a brief.

    spec is None when every attempt failed; caller routes the job to
    AWAITING_REVIEW. Either way, `attempts` contains all LLM-call records for
    the run (persisted by the caller).
    """

    spec: DesignSpec | None
    attempts: list[LlmCallRecord]
    reason: str | None  # human-readable reason when spec is None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_against_template(
    spec: DesignSpec, templates: list[Template]
) -> None:
    """Extra check the Pydantic validator can't do alone: if template_id is
    set, the dimensions must match the chosen template's param schema
    exactly, and each value must be within declared range.

    Raises ValidationError-compatible ValueError so retry logic can treat it
    uniformly with pydantic failures.
    """
    if spec.template_id is None:
        return
    by_id = {t.template_id: t for t in templates}
    template = by_id.get(spec.template_id)
    if template is None:
        raise ValueError(
            f"template_id {spec.template_id!r} is not in the registry"
        )
    template_family = getattr(template, "product_family", None)
    if (
        template_family is not None
        and template_family != spec.product_family.value
    ):
        raise ValueError(
            f"product_family {spec.product_family.value!r} does not match "
            f"template {spec.template_id} (expects {template_family!r})"
        )
    declared_params = {p.name: p for p in template.param_schema}
    given = {name: m.value for name, m in spec.dimensions.items()}

    missing = set(declared_params) - set(given)
    if missing:
        raise ValueError(
            f"template {spec.template_id} missing dimensions: {sorted(missing)}"
        )
    extra = set(given) - set(declared_params)
    if extra:
        raise ValueError(
            f"template {spec.template_id} rejects unknown dimensions: "
            f"{sorted(extra)}"
        )
    for name, value in given.items():
        p = declared_params[name]
        if not math.isfinite(value):
            raise ValueError(
                f"dimension {name}={value} is not a finite number"
            )
        if value < p.min_mm or value > p.max_mm:
            raise ValueError(
                f"dimension {name}={value}mm outside declared range "
                f"[{p.min_mm}, {p.max_mm}]"
            )


def build_intent_from_brief(
    *,
    brief_id: UUID,
    brief_text: str,
    templates: list[Template],
    client: GroqClient,
    sink: LlmCallSink,
) -> IntentResult:
    """Run the LLM intent pipeline against a brief.

    Returns IntentResult with .spec populated on success, or None with a
    reason on terminal failure. Every attempt is recorded via `sink`.
    """
    system = build_system_prompt(templates)
    base_user = build_user_prompt(
        brief_id=str(brief_id), brief_text=brief_text
    )
    p_hash = prompt_hash(system, base_user)

    attempts: list[LlmCallRecord] = []
    last_output = ""
    last_error: str | None = None

    user_prompt = base_user
    for attempt_num in range(1, MAX_ATTEMPTS + 1):
        try:
            response: GroqResponse = client.chat_json(
                system=system, user=user_prompt
            )
            raw = response.content
        except GroqApiError as e:
            record = LlmCallRecord(
                call_id=uuid4(),
                brief_id=brief_id,
                prompt_version=PROMPT_VERSION,
                prompt_hash=p_hash,
                model=client.model,
                attempt=attempt_num,
                succeeded=False,
                error=str(e),
                system_prompt=system,
                user_prompt=user_prompt,
                raw_response="",
                created_at=_now(),
            )
            sink.record(record)
            attempts.append(record)
            last_error = str(e)
            # 4xx (auth, bad request, rate limit) won't fix on retry — bail.
            # 5xx may be transient — let the loop retry until MAX_ATTEMPTS.
            transient = 500 <= e.status_code < 600
            if not transient or attempt_num >= MAX_ATTEMPTS:
                return IntentResult(
                    spec=None,
                    attempts=attempts,
                    reason=f"Groq API error on attempt {attempt_num}: {e}",
                )
            # Transient: continue without modifying user_prompt — there's no
            # LLM output to feed back into retry_feedback.
            continue

        # Parse + validate.
        spec, err = _parse_and_validate(raw, brief_id, templates)
        record = LlmCallRecord(
            call_id=uuid4(),
            brief_id=brief_id,
            prompt_version=PROMPT_VERSION,
            prompt_hash=p_hash,
            model=response.model,
            attempt=attempt_num,
            succeeded=spec is not None,
            error=err,
            system_prompt=system,
            user_prompt=user_prompt,
            raw_response=raw,
            created_at=_now(),
        )
        sink.record(record)
        attempts.append(record)

        if spec is not None:
            return IntentResult(spec=spec, attempts=attempts, reason=None)

        # Loop guard: identical output to previous attempt means the retry
        # prompt isn't moving the model. Bail rather than burn quota.
        if attempt_num > 1 and raw == last_output:
            return IntentResult(
                spec=None,
                attempts=attempts,
                reason=(
                    f"LLM returned identical output on attempt {attempt_num}; "
                    f"aborting. Last error: {err}"
                ),
            )

        # Prepare for retry.
        last_output = raw
        last_error = err
        user_prompt = base_user + retry_feedback(err or "unknown", last_output)

    return IntentResult(
        spec=None,
        attempts=attempts,
        reason=(
            f"validation failed after {MAX_ATTEMPTS} attempts; "
            f"last error: {last_error}"
        ),
    )


def _parse_and_validate(
    raw: str, brief_id: UUID, templates: list[Template]
) -> tuple[DesignSpec | None, str | None]:
    """Return (spec, None) on success or (None, error_message) on failure."""
    if len(raw) > MAX_RESPONSE_CHARS:
        return None, (
            f"response exceeds {MAX_RESPONSE_CHARS} chars "
            f"(got {len(raw)}); refusing to parse"
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"response is not valid JSON: {e}"
    if not isinstance(data, dict):
        return None, "response JSON must be an object at top level"
    # Force the brief_id to match the system-supplied value, regardless of
    # what the LLM emitted. This avoids "hallucinated brief_id" failures.
    data["brief_id"] = str(brief_id)
    # Drop any LLM-supplied spec_id so a fresh UUID is generated. The LLM
    # never chooses primary keys.
    data.pop("spec_id", None)
    try:
        spec = DesignSpec.model_validate(data)
    except ValidationError as e:
        # Strip the noisy `input` field — without this, the retry prompt
        # grows unboundedly because each error embeds the prior input.
        clean = [
            {k: v for k, v in err_.items() if k != "input"}
            for err_ in e.errors()[:3]
        ]
        return None, f"schema validation failed: {clean}"
    try:
        _validate_against_template(spec, templates)
    except ValueError as e:
        return None, f"template validation failed: {e}"
    return spec, None
