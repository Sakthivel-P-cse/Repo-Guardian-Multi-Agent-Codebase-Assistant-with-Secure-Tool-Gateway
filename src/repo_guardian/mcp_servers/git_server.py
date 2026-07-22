from mcp.server.fastmcp import Context, FastMCP

from repo_guardian.adapters.github_adapter import GitHubAdapterPort
from repo_guardian.mcp_servers import TokenValidatorPort, authorize_context


def create_git_server(
    adapter: GitHubAdapterPort, token_validator: TokenValidatorPort
) -> FastMCP:
    server = FastMCP("Repo Guardian Git")

    @server.tool()
    async def get_file(path: str, context: Context, ref: str = "HEAD") -> str:
        authorize_context(context, token_validator, "get_file")
        return await adapter.get_file(path, ref)

    @server.tool()
    async def search_code(query: str, repo: str, context: Context) -> list[dict]:
        authorize_context(context, token_validator, "search_code")
        return await adapter.search_code(query, repo)

    @server.tool()
    async def get_pr(pr_number: int, context: Context) -> dict:
        authorize_context(context, token_validator, "get_pr")
        return await adapter.get_pr(pr_number)

    @server.tool()
    async def list_commits(branch: str, context: Context, limit: int = 10) -> list[dict]:
        authorize_context(context, token_validator, "list_commits")
        return await adapter.list_commits(branch, limit)

    @server.tool()
    async def get_diff(pr_number: int, context: Context) -> str:
        authorize_context(context, token_validator, "get_diff")
        return await adapter.get_diff(pr_number)

    return server
