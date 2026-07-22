from mcp.server.fastmcp import Context, FastMCP

from repo_guardian.adapters.github_adapter import GitHubAdapterPort
from repo_guardian.mcp_servers import TokenValidatorPort, authorize_context


def create_ops_server(
    adapter: GitHubAdapterPort, token_validator: TokenValidatorPort
) -> FastMCP:
    server = FastMCP("Repo Guardian Operations")

    @server.tool()
    async def merge_pr(
        pr_number: int, base: str, context: Context, merge_method: str = "merge"
    ) -> dict:
        authorize_context(context, token_validator, "merge_pr")
        return await adapter.merge_pr(pr_number, base, merge_method)

    @server.tool()
    async def force_push(branch: str, commit_sha: str, context: Context) -> dict:
        authorize_context(context, token_validator, "force_push")
        return await adapter.force_push(branch, commit_sha)

    @server.tool()
    async def delete_branch(branch: str, context: Context) -> dict:
        authorize_context(context, token_validator, "delete_branch")
        return await adapter.delete_branch(branch)

    return server
