from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from repo_guardian.domain.tool_call import ToolCall

AgentRole = Literal["supervisor", "code_search", "reviewer", "repo_ops", "critic"]


@dataclass(slots=True)
class AgentResult:
    role: AgentRole
    content: str
    tool_calls_made: list[ToolCall]
    grounded: bool
