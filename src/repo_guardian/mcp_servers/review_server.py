from mcp.server.fastmcp import Context, FastMCP

from repo_guardian.adapters.github_adapter import GitHubAdapterPort
from repo_guardian.mcp_servers import TokenValidatorPort, authorize_context


def create_review_server(
    adapter: GitHubAdapterPort, token_validator: TokenValidatorPort
) -> FastMCP:
    server = FastMCP("Repo Guardian Review")

    @server.tool()
    async def post_comment(pr_number: int, body: str, context: Context) -> dict:
        authorize_context(context, token_validator, "post_comment")
        return await adapter.post_comment(pr_number, body)

    @server.tool()
    async def add_label(pr_number: int, label: str, context: Context) -> dict:
        authorize_context(context, token_validator, "add_label")
        return await adapter.add_label(pr_number, label)

    return server
