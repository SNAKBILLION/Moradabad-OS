"""Unit tests for FeedbackRecord <-> FeedbackRow conversion helpers.

Pure functions, no DB. Full CRUD round-trips against Postgres live in
tests/integration/test_feedback_api.py.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from mos.db.repository import _feedback_to_row, _row_to_feedback
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


def _record(payload, role: UserRole = UserRole.SUPERVISOR) -> FeedbackRecord:
    return FeedbackRecord(
        job_id=uuid4(),
        user_role=role,
        payload=payload,
        notes_text="test note",
    )


@pytest.mark.parametrize(
    "payload",
    [
        CostActualPayload(
            line_item_code=LineItemCode.CASTING_LABOR, actual_inr=55.0
        ),
        CannotManufacturePayload(reason_code="undercut"),
        DfmViolationObservedPayload(
            rule_id=CheckRule.MIN_WALL_THICKNESS, observed_value=2.3
        ),
        FinishDefectPayload(defect_code="pitting", severity="major"),
        TimeActualPayload(process="polishing", actual_minutes=12.5),
    ],
    ids=["cost", "cannot_mfg", "dfm", "finish", "time"],
)
class TestFeedbackConversion:
    def test_round_trip_preserves_payload(self, payload):
        original = _record(payload)
        row = _feedback_to_row(original)
        # Storage-side fields must be set correctly so queries can find rows.
        assert row.feedback_id == original.feedback_id
        assert row.job_id == original.job_id
        assert row.user_role == original.user_role.value
        assert row.feedback_type == original.payload.type.value

        rebuilt = _row_to_feedback(row)
        assert rebuilt == original

    def test_payload_serialized_as_jsonable_dict(self, payload):
        row = _feedback_to_row(_record(payload))
        # JSONB column expects a dict, not a Pydantic model. Verify it's
        # already converted to the JSON-mode dict at the repository boundary.
        assert isinstance(row.payload, dict)
        assert row.payload["type"] == payload.type.value


class TestFeedbackUserRoles:
    @pytest.mark.parametrize(
        "role",
        [
            UserRole.FACTORY_OWNER,
            UserRole.SUPERVISOR,
            UserRole.KARIGAR,
            UserRole.QC,
        ],
    )
    def test_each_role_round_trips(self, role: UserRole):
        original = _record(
            TimeActualPayload(process="x", actual_minutes=1.0), role=role
        )
        rebuilt = _row_to_feedback(_feedback_to_row(original))
        assert rebuilt.user_role == role
