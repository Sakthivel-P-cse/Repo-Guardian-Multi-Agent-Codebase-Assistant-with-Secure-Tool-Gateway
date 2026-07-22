from typing import Any, Protocol

from repo_guardian.domain.task import TaskGraph
from repo_guardian.domain.tool_call import ToolCall, ToolResult
from repo_guardian.gateway.audit import AuditLoggerPort
from repo_guardian.gateway.classifier import RiskClassifierPort
from repo_guardian.gateway.credential_manager import CredentialManagerPort
from repo_guardian.gateway.goal_checker import GoalCheckerPort
from repo_guardian.gateway.verifier import VerifierPort


class MCPToolExecutorPort(Protocol):
    async def call_tool(self, call: ToolCall, token: str) -> Any: ...


class SecureToolGateway:
    def __init__(
        self,
        classifier: RiskClassifierPort,
        credential_manager: CredentialManagerPort,
        goal_checker: GoalCheckerPort,
        verifier: VerifierPort,
        audit_logger: AuditLoggerPort,
        tool_executor: MCPToolExecutorPort | None = None,
    ) -> None:
        self.classifier = classifier
        self.credential_manager = credential_manager
        self.goal_checker = goal_checker
        self.verifier = verifier
        self.audit_logger = audit_logger
        self._tool_executor = tool_executor

    async def execute(self, call: ToolCall, task_graph: TaskGraph) -> ToolResult:
        tier = self.classifier.classify(call)
        self.audit_logger.log(call, tier, "pending", None)
        if tier == "tier3":
            self.audit_logger.log(call, tier, "blocked", None)
            return ToolResult(call.tool_name, None, False, False)
        if tier == "tier2":
            consistent, reason = await self.goal_checker.check(call, task_graph)
            if not consistent:
                self.audit_logger.log(call, tier, "blocked_goal_mismatch", reason)
                return ToolResult(call.tool_name, None, False, False)
        token = self.credential_manager.get_scoped_token(tier, call.tool_name, call.run_id)
        try:
            result = await self._call_mcp_tool(call, token)
        finally:
            self.credential_manager.revoke_token(token)
        if not isinstance(result, ToolResult):
            result = ToolResult(call.tool_name, result, True, False)
        if tier == "tier2":
            verified, _ = await self.verifier.verify(call, result)
            result = ToolResult(call.tool_name, result.output, result.success, verified)
        decision = "approved_auto" if tier == "tier1" else "approved_logged"
        self.audit_logger.log(call, tier, decision, str(result.output))
        return result

    async def _call_mcp_tool(self, call: ToolCall, token: str) -> ToolResult:
        if self._tool_executor is None:
            raise RuntimeError("No MCP tool executor configured")
        output = await self._tool_executor.call_tool(call, token)
        return ToolResult(call.tool_name, output, True, False)
