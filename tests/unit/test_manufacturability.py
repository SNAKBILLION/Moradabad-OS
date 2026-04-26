"""Tests for ManufacturabilityReport."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from mos.schemas import (
    CheckResult,
    CheckRule,
    CheckStatus,
    ManufacturabilityReport,
)

from .builders import make_manufacturability_report


class TestManufacturabilityReport:
    def test_all_pass(self):
        r = make_manufacturability_report()
        assert r.passed is True

    def test_fail_check_fails_overall(self):
        r = ManufacturabilityReport(
            spec_id=uuid4(),
            checks=[
                CheckResult(
                    rule_id=CheckRule.MIN_WALL_THICKNESS,
                    status=CheckStatus.FAIL,
                    value=1.0,
                    threshold=3.0,
                    message="wall 1mm < 3mm minimum",
                ),
            ],
        )
        assert r.passed is False

    def test_warn_does_not_fail(self):
        r = ManufacturabilityReport(
            spec_id=uuid4(),
            checks=[
                CheckResult(
                    rule_id=CheckRule.DRAFT_ANGLE,
                    status=CheckStatus.WARN,
                    value=1.0,
                    threshold=1.5,
                    message="draft 1deg is below recommended 1.5deg",
                ),
            ],
        )
        assert r.passed is True

    def test_empty_check_list_rejected(self):
        with pytest.raises(ValidationError):
            ManufacturabilityReport(spec_id=uuid4(), checks=[])
