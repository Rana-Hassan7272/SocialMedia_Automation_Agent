from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Dict, Optional

from ..database import DatabaseManager
from ..database.models import AuditAction, WorkflowPhase, WorkflowStatus
from ..utils.errors import friendly_error
from ..utils.logging_config import get_logger
from ..workflow.graph import WorkflowGraph

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)
_runner: Optional["PipelineJobRunner"] = None
_lock = Lock()


class PipelineJobRunner:
    def __init__(self, workflow_graph: WorkflowGraph, db_manager: DatabaseManager):
        self.workflow_graph = workflow_graph
        self.db = db_manager
        self._jobs: Dict[int, Future] = {}

    def submit(
        self,
        workflow_id: int,
        user_query: str,
        user_id: int,
        x_username: Optional[str],
    ) -> Future:
        with _lock:
            if workflow_id in self._jobs and not self._jobs[workflow_id].done():
                return self._jobs[workflow_id]
            future = _executor.submit(
                self._execute,
                workflow_id,
                user_query,
                user_id,
                x_username,
            )
            self._jobs[workflow_id] = future
            return future

    def is_running(self, workflow_id: int) -> bool:
        future = self._jobs.get(workflow_id)
        return bool(future and not future.done())

    def get_future(self, workflow_id: int) -> Optional[Future]:
        return self._jobs.get(workflow_id)

    def _execute(
        self,
        workflow_id: int,
        user_query: str,
        user_id: int,
        x_username: Optional[str],
    ) -> str:
        logger.info("workflow_id=%s started in background", workflow_id)
        try:
            _, thread_id = self.workflow_graph.execute_until_review(
                workflow_id=workflow_id,
                user_query=user_query,
                user_id=user_id,
                x_username=x_username,
            )
            return thread_id
        except Exception as exc:
            logger.exception("workflow_id=%s failed: %s", workflow_id, exc)
            self.db.update_workflow_phase(workflow_id, WorkflowPhase.FAILED)
            self.db.update_workflow_status(
                workflow_id,
                WorkflowStatus.FAILED,
                error_message=str(exc),
            )
            self.db.create_audit_log(
                AuditAction.WORKFLOW_FAILED,
                user_id=user_id,
                workflow_id=workflow_id,
                x_username=x_username,
                details=friendly_error(exc),
            )
            raise


def get_job_runner(workflow_graph: WorkflowGraph, db_manager: DatabaseManager) -> PipelineJobRunner:
    global _runner
    if _runner is None:
        _runner = PipelineJobRunner(workflow_graph, db_manager)
    return _runner
