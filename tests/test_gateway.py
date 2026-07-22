import pytest
from mcp.server.fastmcp.exceptions import ToolError

from repo_guardian.adapters.mock_github_adapter import MockGitHubAdapter
from repo_guardian.domain.task import TaskGraph
from repo_guardian.domain.tool_call import ToolCall
from repo_guardian.gateway.credential_manager import ScopedTokenFactory
from repo_guardian.gateway.gateway import SecureToolGateway
from repo_guardian.mcp_servers.ops_server import create_ops_server


class Classifier:
    def __init__(self, tier):
        self.tier = tier

    def classify(self, call):
        return self.tier


class Credentials:
    def __init__(self):
        self.requested = []
        self.revoked = []

    def get_scoped_token(self, tier, tool_name, run_id):
        self.requested.append((tier, tool_name, run_id))
        return "token"

    def revoke_token(self, token):
        self.revoked.append(token)


class GoalChecker:
    def __init__(self, consistent=True):
        self.consistent = consistent
        self.calls = []

    async def check(self, call, graph):
        self.calls.append((call, graph))
        return self.consistent, "matches" if self.consistent else "does not match"


class Verifier:
    def __init__(self):
        self.calls = []

    async def verify(self, call, result):
        self.calls.append((call, result))
        return True, {"verified": True}


class Audit:
    def __init__(self):
        self.entries = []

    def log(self, call, tier, decision, outcome):
        self.entries.append((call.tool_name, tier, decision, outcome))


class Executor:
    def __init__(self):
        self.calls = []

    async def call_tool(self, call, token):
        self.calls.append((call, token))
        return {"ok": True}


def dependencies(tier, consistent=True):
    credentials = Credentials()
    goal = GoalChecker(consistent)
    verifier = Verifier()
    audit = Audit()
    executor = Executor()
    gateway = SecureToolGateway(
        Classifier(tier), credentials, goal, verifier, audit, executor
    )
    return gateway, credentials, goal, verifier, audit, executor


def graph():
    return TaskGraph("run-1", "Review PR #142", [])


async def test_tier3_is_blocked_without_credentials():
    gateway, credentials, goal, verifier, audit, executor = dependencies("tier3")
    result = await gateway.execute(
        ToolCall("merge_pr", {"base": "main"}, "repo_ops", "run-1"), graph()
    )
    assert result.success is False
    assert credentials.requested == []
    assert goal.calls == []
    assert executor.calls == []
    assert audit.entries[-1][2] == "blocked"


async def test_tier2_goal_mismatch_is_blocked():
    gateway, credentials, goal, verifier, audit, executor = dependencies(
        "tier2", consistent=False
    )
    result = await gateway.execute(
        ToolCall("post_comment", {}, "reviewer", "run-1"), graph()
    )
    assert result.success is False
    assert credentials.requested == []
    assert executor.calls == []
    assert audit.entries[-1][2:] == ("blocked_goal_mismatch", "does not match")


async def test_tier2_consistent_call_is_approved_verified_and_revoked():
    gateway, credentials, goal, verifier, audit, executor = dependencies("tier2")
    call = ToolCall("post_comment", {}, "reviewer", "run-1")
    result = await gateway.execute(call, graph())
    assert result.success is True
    assert result.verified is True
    assert credentials.requested == [("tier2", "post_comment", "run-1")]
    assert credentials.revoked == ["token"]
    assert len(verifier.calls) == 1
    assert audit.entries[-1][2] == "approved_logged"


async def test_tier1_is_approved_without_verification():
    gateway, credentials, goal, verifier, audit, executor = dependencies("tier1")
    result = await gateway.execute(
        ToolCall("get_pr", {}, "code_search", "run-1"), graph()
    )
    assert result.success is True
    assert result.verified is False
    assert goal.calls == []
    assert verifier.calls == []
    assert credentials.revoked == ["token"]
    assert audit.entries[-1][2] == "approved_auto"


async def test_mcp_write_tool_rejects_direct_call_without_gateway_token():
    adapter = MockGitHubAdapter()
    server = create_ops_server(adapter, ScopedTokenFactory())
    with pytest.raises(ToolError, match="Gateway authorization metadata is required"):
        await server.call_tool("merge_pr", {"pr_number": 142, "base": "main"})
    assert (await adapter.get_pr(142))["state"] == "open"
