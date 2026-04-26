"""Tests for FeedbackRecord. The payload is a discriminated union; we check
that each payload type round-trips and that the wrong-type case is rejected."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mos.schemas import (
    CannotManufacturePayload,
    CostActualPayload,
    DfmViolationObservedPayload,
    FeedbackRecord,
    FinishDefectPayload,
    LineItemCode,
    TimeActualPayload,
    UserRole,
)
from mos.schemas.manufacturability import CheckRule


def _record(payload):
    return FeedbackRecord(
        job_id=uuid4(),
        user_role=UserRole.SUPERVISOR,
        payload=payload,
    )


class TestFeedbackPayloads:
    def test_cost_actual(self):
        r = _record(
            CostActualPayload(
                line_item_code=LineItemCode.CASTING_LABOR,
                actual_inr=55.0,
            )
        )
        assert r.payload.actual_inr == 55.0

    def test_cannot_manufacture(self):
        r = _record(CannotManufacturePayload(reason_code="undercut"))
        assert r.payload.reason_code == "undercut"

    def test_dfm_violation_observed(self):
        r = _record(
            DfmViolationObservedPayload(
                rule_id=CheckRule.MIN_WALL_THICKNESS,
                observed_value=2.3,
            )
        )
        assert r.payload.observed_value == 2.3

    def test_finish_defect(self):
        r = _record(
            FinishDefectPayload(defect_code="pitting", severity="major")
        )
        assert r.payload.severity == "major"

    def test_time_actual(self):
        r = _record(
            TimeActualPayload(process="polishing", actual_minutes=12.5)
        )
        assert r.payload.actual_minutes == 12.5


class TestFeedbackDiscriminator:
    def test_round_trip_preserves_payload_type(self):
        original = _record(
            TimeActualPayload(process="chasing", actual_minutes=18.0)
        )
        as_json = original.model_dump_json()
        rebuilt = FeedbackRecord.model_validate_json(as_json)
        assert isinstance(rebuilt.payload, TimeActualPayload)
        assert rebuilt.payload.process == "chasing"

    def test_missing_discriminator_rejected(self):
        bad = {
            "job_id": str(uuid4()),
            "user_role": UserRole.KARIGAR.value,
            "payload": {
                # no "type" field — discriminator missing
                "process": "polishing",
                "actual_minutes": 10.0,
            },
        }
        with pytest.raises(ValidationError):
            FeedbackRecord.model_validate(bad)

    def test_wrong_severity_rejected(self):
        with pytest.raises(ValidationError):
            FinishDefectPayload(defect_code="scratch", severity="catastrophic")
