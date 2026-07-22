from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from repo_guardian.domain.agent import AgentRole

RiskTier = Literal["tier1", "tier2", "tier3"]


class ResourceNotFoundError(RuntimeError):
    pass


@dataclass(slots=True)
class ToolCall:
    tool_name: str
    parameters: dict[str, Any]
    agent_role: AgentRole
    run_id: str


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    output: Any
    success: bool
    verified: bool
