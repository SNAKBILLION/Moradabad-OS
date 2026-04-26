"""FeedbackRecord: append-only floor feedback.

Phase 1 does not use feedback to auto-tune anything — this is data capture for
future calibration. The five types map to the five things we expect the floor
to report: actual cost per line item, unmanufacturable designs, observed DFM
violations our rules missed, finish defects, and actual process times.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .cost_sheet import LineItemCode
from .manufacturability import CheckRule


class UserRole(str, Enum):
    FACTORY_OWNER = "factory_owner"
    SUPERVISOR = "supervisor"
    KARIGAR = "karigar"
    QC = "qc"


class FeedbackType(str, Enum):
    COST_ACTUAL = "cost_actual"
    CANNOT_MANUFACTURE = "cannot_manufacture"
    DFM_VIOLATION_OBSERVED = "dfm_violation_observed"
    FINISH_DEFECT = "finish_defect"
    TIME_ACTUAL = "time_actual"


# --- Typed payloads per feedback type -----------------------------------

class CostActualPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal[FeedbackType.COST_ACTUAL] = FeedbackType.COST_ACTUAL
    line_item_code: LineItemCode
    actual_inr: float = Field(ge=0)


class CannotManufacturePayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal[FeedbackType.CANNOT_MANUFACTURE] = (
        FeedbackType.CANNOT_MANUFACTURE
    )
    reason_code: str = Field(min_length=1, max_length=64)
    # Short free-form code owned by the floor — e.g. "undercut", "too_thin",
    # "handle_weld_fails". We accumulate these and promote to an enum later.


class DfmViolationObservedPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal[FeedbackType.DFM_VIOLATION_OBSERVED] = (
        FeedbackType.DFM_VIOLATION_OBSERVED
    )
    rule_id: CheckRule
    observed_value: float


class FinishDefectPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal[FeedbackType.FINISH_DEFECT] = FeedbackType.FINISH_DEFECT
    defect_code: str = Field(min_length=1, max_length=64)
    severity: Literal["minor", "major", "reject"]


class TimeActualPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal[FeedbackType.TIME_ACTUAL] = FeedbackType.TIME_ACTUAL
    process: str = Field(min_length=1, max_length=64)
    actual_minutes: float = Field(ge=0)


FeedbackPayload = (
    CostActualPayload
    | CannotManufacturePayload
    | DfmViolationObservedPayload
    | FinishDefectPayload
    | TimeActualPayload
)


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    feedback_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    user_role: UserRole
    payload: FeedbackPayload = Field(discriminator="type")
    notes_text: str = Field(default="", max_length=2000)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
