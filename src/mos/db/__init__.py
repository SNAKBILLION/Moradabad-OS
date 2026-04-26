"""Database layer: session management, ORM models, repositories.

Import from here, not from submodules. The repository layer is the only
supported way for application code to touch the database.
"""

from .models import (
    Base,
    BriefRow,
    CostSheetRow,
    DesignSpecRow,
    FeedbackRow,
    FxRateRow,
    JobRow,
    LlmCallRow,
    MetalRateRow,
    TemplateRow,
)
from .repository import (
    BriefRepository,
    CostSheetRepository,
    DesignSpecNotFoundError,
    DesignSpecRepository,
    FeedbackNotFoundError,
    FeedbackRepository,
    JobNotFoundError,
    JobRepository,
    LlmCallRepository,
    MetalRateRepository,
)
from .session import make_engine, make_session_factory, session_scope

__all__ = [
    "Base",
    "BriefRow",
    "CostSheetRow",
    "DesignSpecRow",
    "FeedbackRow",
    "FxRateRow",
    "JobRow",
    "LlmCallRow",
    "MetalRateRow",
    "TemplateRow",
    "BriefRepository",
    "CostSheetRepository",
    "DesignSpecNotFoundError",
    "DesignSpecRepository",
    "FeedbackNotFoundError",
    "FeedbackRepository",
    "JobNotFoundError",
    "JobRepository",
    "LlmCallRepository",
    "MetalRateRepository",
    "make_engine",
    "make_session_factory",
    "session_scope",
]
