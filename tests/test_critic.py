from types import SimpleNamespace

from repo_guardian.agents.critic import CriticAgent
from repo_guardian.config import Config
from repo_guardian.domain.task import RunTokenBudget
from repo_guardian.domain.tool_call import ToolResult


class Messages:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(content=[SimpleNamespace(text=self.response)])


class Client:
    def __init__(self, response):
        self.messages = Messages(response)


def critic(response):
    return CriticAgent(object(), Client(response), Config(openai_api_key="test"))


async def test_all_grounded_claims_pass():
    result = await critic("PASS").run(
        "PR #142 is open.", [ToolResult("get_pr", {"state": "open"}, True, False)]
    )
    assert result.passed is True
    assert result.ungrounded_claims == []


async def test_specific_ungrounded_claim_fails():
    claim = "PR #142 has full test coverage."
    result = await critic(f"- {claim}").run(
        f"PR #142 is open. {claim}",
        [ToolResult("get_pr", {"state": "open"}, True, False)],
    )
    assert result.passed is False
    assert result.ungrounded_claims == [claim]


async def test_zero_tool_results_fails():
    draft = "PR #142 is safe to merge."
    result = await critic("PASS").run(draft, [])
    assert result.passed is False
    assert result.ungrounded_claims == [draft]


async def test_shared_token_budget_caps_model_request():
    client = Client("PASS")
    agent = CriticAgent(
        object(),
        client,
        Config(openai_api_key="test", max_tokens_per_run=1),
        RunTokenBudget(1),
    )
    await agent.run(
        "PR #142 is open.", [ToolResult("get_pr", {"state": "open"}, True, False)]
    )
    assert client.messages.requests[0]["max_tokens"] == 1
