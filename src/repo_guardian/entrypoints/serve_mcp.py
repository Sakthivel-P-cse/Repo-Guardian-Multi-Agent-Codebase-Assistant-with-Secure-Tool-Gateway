from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import ValidationError

from repo_guardian.adapters.github_adapter import GitHubAdapter
from repo_guardian.adapters.mock_github_adapter import MockGitHubAdapter
from repo_guardian.config import Config
from repo_guardian.gateway.credential_manager import ScopedTokenFactory
from repo_guardian.mcp_servers.git_server import create_git_server
from repo_guardian.mcp_servers.ops_server import create_ops_server
from repo_guardian.mcp_servers.review_server import create_review_server


def _load_config() -> Config:
    try:
        return Config()
    except ValidationError:
        return Config(openai_api_key="demo")


def _build_app() -> FastAPI:
    config = _load_config()
    adapter = (
        GitHubAdapter(config.github_token, config.github_repo)
        if config.github_token
        else MockGitHubAdapter()
    )
    token_validator = ScopedTokenFactory()
    servers = [
        ("/git", create_git_server(adapter, token_validator)),
        ("/review", create_review_server(adapter, token_validator)),
        ("/ops", create_ops_server(adapter, token_validator)),
    ]
    apps = [(path, server.streamable_http_app()) for path, server in servers]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            for _, server in servers:
                await stack.enter_async_context(server.session_manager.run())
            yield

    app = FastAPI(lifespan=lifespan)
    for path, mcp_app in apps:
        app.mount(path, mcp_app)
    return app


def main() -> None:
    uvicorn.run(_build_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
