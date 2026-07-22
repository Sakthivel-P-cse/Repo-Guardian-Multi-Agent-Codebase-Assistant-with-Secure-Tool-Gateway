from typing import Any, Protocol

from repo_guardian.domain.tool_call import ResourceNotFoundError, ToolCall, ToolResult
from repo_guardian.gateway.audit import AuditLoggerPort


class VerificationError(RuntimeError):
    pass


class StateReaderPort(Protocol):
    async def read(
        self, tool_name: str, parameters: dict[str, Any], run_id: str
    ) -> Any: ...


class VerifierPort(Protocol):
    async def verify(self, call: ToolCall, result: ToolResult) -> tuple[bool, dict[str, Any]]: ...


class OutcomeVerifier:
    def __init__(self, state_reader: StateReaderPort, audit_logger: AuditLoggerPort) -> None:
        self._state_reader = state_reader
        self._audit_logger = audit_logger

    async def verify(self, call: ToolCall, result: ToolResult) -> tuple[bool, dict[str, Any]]:
        actual = await self._actual_state(call, result)
        verified = self._matches(call, result, actual)
        if not verified:
            self._audit_logger.log(call, "tier2", "blocked", repr(actual))
            raise VerificationError(f"Could not verify outcome for {call.tool_name}")
        return True, actual

    async def _actual_state(self, call: ToolCall, result: ToolResult) -> dict[str, Any]:
        if call.tool_name in {"post_comment", "add_label", "merge_pr"}:
            state = await self._state_reader.read(
                "get_pr", {"pr_number": call.parameters["pr_number"]}, call.run_id
            )
            return dict(state)
        if call.tool_name == "delete_branch":
            try:
                await self._state_reader.read(
                    "list_commits",
                    {"branch": call.parameters["branch"], "limit": 1},
                    call.run_id,
                )
            except ResourceNotFoundError:
                return {"deleted": True}
            return {"deleted": False}
        return dict(result.output) if isinstance(result.output, dict) else {"output": result.output}

    @staticmethod
    def _matches(call: ToolCall, result: ToolResult, actual: dict[str, Any]) -> bool:
        if not result.success:
            return False
        if call.tool_name == "post_comment":
            return any(
                comment.get("body") == call.parameters.get("body")
                for comment in actual.get("comments", [])
            )
        if call.tool_name == "add_label":
            return call.parameters.get("label") in actual.get("labels", [])
        if call.tool_name == "merge_pr":
            return actual.get("state") == "merged"
        if call.tool_name == "delete_branch":
            return actual.get("deleted") is True
        return True
