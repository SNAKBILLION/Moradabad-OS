"""Domain contracts for Moradabad AI Design + Production OS.

Every other module consumes types from here. If a type isn't re-exported
below, it isn't part of the public contract yet — don't import it from
elsewhere without adding it here first.
"""

from .common import (
    BrassAlloy,
    CastingMethod,
    Currency,
    Measurement,
    Money,
    Plating,
    PolishFinish,
    ProductFamily,
)
from .cost_sheet import (
    CostLineItem,
    CostSheet,
    CostTotals,
    FxSnapshot,
    LineItemCode,
    MetalRate,
)
from .design_spec import (
    SCHEMA_VERSION,
    DesignSpec,
    FinishSpec,
    MaterialSpec,
    MotifRef,
)
from .feedback import (
    CannotManufacturePayload,
    CostActualPayload,
    DfmViolationObservedPayload,
    FeedbackPayload,
    FeedbackRecord,
    FeedbackType,
    FinishDefectPayload,
    TimeActualPayload,
    UserRole,
)
from .job import (
    ArtifactBundle,
    Job,
    JobStatus,
    PipelineSnapshot,
    StageName,
    StageRecord,
    StageStatus,
)
from .manufacturability import (
    CheckResult,
    CheckRule,
    CheckStatus,
    ManufacturabilityReport,
)

__all__ = [
    "SCHEMA_VERSION",
    # common
    "BrassAlloy",
    "CastingMethod",
    "Currency",
    "Measurement",
    "Money",
    "Plating",
    "PolishFinish",
    "ProductFamily",
    # design_spec
    "DesignSpec",
    "FinishSpec",
    "MaterialSpec",
    "MotifRef",
    # manufacturability
    "CheckResult",
    "CheckRule",
    "CheckStatus",
    "ManufacturabilityReport",
    # cost_sheet
    "CostLineItem",
    "CostSheet",
    "CostTotals",
    "FxSnapshot",
    "LineItemCode",
    "MetalRate",
    # job
    "ArtifactBundle",
    "Job",
    "JobStatus",
    "PipelineSnapshot",
    "StageName",
    "StageRecord",
    "StageStatus",
    # feedback
    "CannotManufacturePayload",
    "CostActualPayload",
    "DfmViolationObservedPayload",
    "FeedbackPayload",
    "FeedbackRecord",
    "FeedbackType",
    "FinishDefectPayload",
    "TimeActualPayload",
    "UserRole",
]
