"""ManufacturabilityReport: output of the DFM check phase in the CAD layer.

A report consists of a list of CheckResults. The pipeline halts if any
CheckResult has status FAIL; WARN-level results proceed but are surfaced in
the final bundle.
"""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class CheckRule(str, Enum):
    """Identifiers for Phase 1 DFM checks.

    Adding a rule is a breaking change to any downstream consumer that
    pattern-matches on rule IDs; bump SCHEMA_VERSION in design_spec.py when
    that happens.
    """

    MIN_WALL_THICKNESS = "min_wall_thickness"
    DRAFT_ANGLE = "draft_angle"
    MAX_BOUNDING_BOX = "max_bounding_box"
    MAX_MASS = "max_mass"
    UNDERCUT_DETECTED = "undercut_detected"
    CLOSED_SHELL = "closed_shell"
    SHRINKAGE_APPLIED = "shrinkage_applied"


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: CheckRule
    status: CheckStatus
    value: float | None = None
    threshold: float | None = None
    message: str = Field(max_length=500)


class ManufacturabilityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    spec_id: UUID
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        """True iff no FAIL-level checks. WARN is allowed."""
        return not any(c.status == CheckStatus.FAIL for c in self.checks)

    @model_validator(mode="after")
    def _require_at_least_one_check(self) -> ManufacturabilityReport:
        if not self.checks:
            raise ValueError("ManufacturabilityReport must contain >= 1 check")
        return self
