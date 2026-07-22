from typing import Protocol

from repo_guardian.domain.task import TaskGraph, TaskStatus


class TaskRepositoryPort(Protocol):
    async def save_graph(self, graph: TaskGraph) -> None: ...

    async def get_graph(self, run_id: str) -> TaskGraph | None: ...

    async def update_subtask(
        self,
        run_id: str,
        subtask_id: str,
        status: TaskStatus,
        result: str | None,
    ) -> None: ...
