from .state import WorkflowState, WorkflowStep, create_initial_state

__all__ = [
    "WorkflowState",
    "WorkflowStep",
    "create_initial_state",
    "WorkflowGraph",
]


def __getattr__(name: str):
    if name == "WorkflowGraph":
        from .graph import WorkflowGraph
        return WorkflowGraph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
