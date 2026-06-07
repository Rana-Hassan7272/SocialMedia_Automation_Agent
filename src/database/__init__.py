from .models import (
    Workflow,
    Intent,
    ResearchResult,
    FilteredContent,
    Insight,
    Draft,
    Feedback,
    PublishedPost,
)

__all__ = [
    "DatabaseManager",
    "Workflow",
    "Intent",
    "ResearchResult",
    "FilteredContent",
    "Insight",
    "Draft",
    "Feedback",
    "PublishedPost",
]


def __getattr__(name: str):
    if name == "DatabaseManager":
        from .db_manager import DatabaseManager
        return DatabaseManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
