from dataclasses import dataclass
from typing import Literal

from repo_guardian.domain.agent import AgentRole

TaskStatus = Literal["pending", "running", "done", "failed", "blocked"]


class TokenBudgetExceeded(RuntimeError):
    pass


@dataclass(slots=True)
class RunTokenBudget:
    max_tokens: int
    used_tokens: int = 0

    @property
    def remaining(self) -> int:
        return self.max_tokens - self.used_tokens

    def consume(self, tokens: int) -> None:
        if tokens < 0 or tokens > self.remaining:
            raise TokenBudgetExceeded("Maximum token limit reached")
        self.used_tokens += tokens


@dataclass(slots=True)
class SubTask:
    id: str
    description: str
    assigned_to: AgentRole
    status: TaskStatus = "pending"
    result: str | None = None


@dataclass(slots=True)
class TaskGraph:
    run_id: str
    original_goal: str
    subtasks: list[SubTask]
    completed: bool = False
