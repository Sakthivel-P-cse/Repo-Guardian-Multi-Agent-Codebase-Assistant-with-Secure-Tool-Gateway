from typing import Any, Protocol
from uuid import uuid4

from mcp.server.fastmcp import Context
from mcp.shared.context import RequestContext
from mcp.types import RequestParams

from repo_guardian.adapters.github_adapter import GitHubAdapterPort
from repo_guardian.domain.tool_call import RiskTier, ToolCall


class TokenValidatorPort(Protocol):
    def get_scoped_token(self, tier: RiskTier, tool_name: str, run_id: str) -> str: ...

    def validate_token(self, token: str, tool_name: str) -> None: ...

    def revoke_token(self, token: str) -> None: ...


class MCPAuthorizationError(PermissionError):
    pass


def authorize_context(
    context: Context, token_validator: TokenValidatorPort, tool_name: str
) -> None:
    try:
        metadata = context.request_context.meta
    except (LookupError, ValueError) as error:
        raise MCPAuthorizationError("Gateway authorization metadata is required") from error
    token = getattr(metadata, "gatewayToken", None) if metadata is not None else None
    if not isinstance(token, str) or not token:
        raise MCPAuthorizationError("Gateway authorization metadata is required")
    token_validator.validate_token(token, tool_name)


class MCPToolRouter:
    def __init__(self, adapter: GitHubAdapterPort, token_validator: TokenValidatorPort) -> None:
        self._token_validator = token_validator
        from repo_guardian.mcp_servers.git_server import create_git_server
        from repo_guardian.mcp_servers.ops_server import create_ops_server
        from repo_guardian.mcp_servers.review_server import create_review_server

        git_server = create_git_server(adapter, token_validator)
        review_server = create_review_server(adapter, token_validator)
        ops_server = create_ops_server(adapter, token_validator)
        self._servers = {
            "get_file": git_server,
            "search_code": git_server,
            "get_pr": git_server,
            "list_commits": git_server,
            "get_diff": git_server,
            "post_comment": review_server,
            "add_label": review_server,
            "merge_pr": ops_server,
            "force_push": ops_server,
            "delete_branch": ops_server,
        }

    async def call_tool(self, call: ToolCall, token: str) -> Any:
        return await self._invoke(call.tool_name, call.parameters, token)

    async def read(
        self, tool_name: str, parameters: dict[str, Any], run_id: str = "verification"
    ) -> Any:
        if tool_name not in {"get_file", "search_code", "get_pr", "list_commits", "get_diff"}:
            raise PermissionError(f"{tool_name} is not read-only")
        token = self._token_validator.get_scoped_token("tier1", tool_name, run_id)
        try:
            return await self._invoke(tool_name, parameters, token)
        finally:
            self._token_validator.revoke_token(token)

    async def _invoke(
        self, tool_name: str, parameters: dict[str, Any], token: str
    ) -> Any:
        server = self._servers.get(tool_name)
        if server is None:
            raise KeyError(tool_name)
        metadata = RequestParams.Meta.model_validate({"gatewayToken": token})
        request_context = RequestContext(
            request_id=str(uuid4()),
            meta=metadata,
            session=None,
            lifespan_context=None,
        )
        context = Context(request_context=request_context, fastmcp=server)
        return await server._tool_manager.call_tool(
            tool_name, parameters, context=context, convert_result=False
        )


__all__ = ["MCPAuthorizationError", "MCPToolRouter", "authorize_context"]
