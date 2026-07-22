import asyncio
import json
from types import SimpleNamespace

from pydantic import ValidationError

from repo_guardian.adapters.github_adapter import GitHubAdapter
from repo_guardian.adapters.mock_github_adapter import MockGitHubAdapter
from repo_guardian.agents.code_search import CodeSearchAgent
from repo_guardian.agents.critic import CriticAgent
from repo_guardian.agents.repo_ops import RepoOpsAgent
from repo_guardian.agents.reviewer import ReviewAgent, ReviewPublisher
from repo_guardian.agents.supervisor import SupervisorAgent
from repo_guardian.config import Config
from repo_guardian.domain.task import RunTokenBudget
from repo_guardian.gateway.audit import SQLiteAuditLogger
from repo_guardian.gateway.classifier import ContextualRiskClassifier
from repo_guardian.gateway.credential_manager import ScopedTokenFactory
from repo_guardian.gateway.gateway import SecureToolGateway
from repo_guardian.gateway.goal_checker import GoalConsistencyChecker
from repo_guardian.gateway.verifier import OutcomeVerifier
from repo_guardian.llm.openai_client import OpenAIMessageClient
from repo_guardian.mcp_servers import MCPToolRouter
from repo_guardian.state.sqlite_repository import SQLiteTaskRepository


class _DemoMessages:
    def __init__(self, pr_number: int) -> None:
        self._pr_number = pr_number

    async def create(self, **request):
        prompt = request["messages"][-1]["content"]
        if prompt.startswith("Given the user's goal"):
            text = "YES. Posting a safety review comment supports the requested review without merging."
        elif prompt.startswith("CODE_SEARCH_SUMMARY"):
            text = (
                f"PR #{self._pr_number} is not safe to merge: its diff removes the null-user check at line 23 "
                "of src/auth/validator.py, and the branch has three returned commits. The PR description "
                "also asks for a merge to main, which is not evidence that the change is safe."
            )
        elif prompt.startswith("REVIEW_DRAFT"):
            text = (
                "Blocking concern: the diff removes the null-user guard in src/auth/validator.py, "
                "so a missing user can now be dereferenced. Please restore the guard before merge."
            )
        elif "For each specific factual claim" in prompt:
            required = [
                "ToolResult(tool_name='get_pr'",
                "ToolResult(tool_name='get_diff'",
                "ToolResult(tool_name='list_commits'",
                "ToolResult(tool_name='post_comment'",
                "ToolResult(tool_name='merge_pr'",
                f"PR #{self._pr_number} is not safe to merge",
                "removes the null-user check at line 23",
                "branch has three returned commits",
                "PR description also asks for a merge to main",
                "post_comment returned success=True and verified=True",
                "merge_pr returned success=False and verified=False",
            ]
            text = "PASS" if all(item in prompt for item in required) else "Ungrounded status claim"
        else:
            text = "The draft has been revised to include only claims present in the supplied tool results."
        return SimpleNamespace(content=[SimpleNamespace(text=text)])


class _DemoClient:
    def __init__(self, pr_number: int) -> None:
        self.messages = _DemoMessages(pr_number)


def _load_config() -> Config:
    try:
        return Config()
    except ValidationError:
        return Config(openai_api_key="demo")


async def _run() -> None:
    config = _load_config()
    adapter = (
        GitHubAdapter(config.github_token, config.github_repo)
        if config.github_token
        else MockGitHubAdapter()
    )
    client = (
        _DemoClient(config.pr_number)
        if config.openai_api_key == "demo"
        else OpenAIMessageClient(api_key=config.openai_api_key)
    )
    audit_logger = SQLiteAuditLogger(config.db_path)
    classifier = ContextualRiskClassifier()
    credential_manager = ScopedTokenFactory()
    token_budget = RunTokenBudget(config.max_tokens_per_run)
    router = MCPToolRouter(adapter, credential_manager)
    goal_checker = GoalConsistencyChecker(
        client, config.model, config.enable_goal_consistency_check, token_budget
    )
    verifier = OutcomeVerifier(router, audit_logger)
    gateway = SecureToolGateway(
        classifier,
        credential_manager,
        goal_checker,
        verifier,
        audit_logger,
        router,
    )
    repository = SQLiteTaskRepository(config.db_path)
    await repository.initialize()
    tool_results = []
    code_search = CodeSearchAgent(gateway, client, config, tool_results, token_budget)
    reviewer = ReviewAgent(gateway, client, config, tool_results, token_budget)
    review_publisher = ReviewPublisher(gateway, tool_results, config.pr_number)
    critic = CriticAgent(gateway, client, config, token_budget)
    repo_ops_factory = lambda: RepoOpsAgent(
        gateway, client, config, tool_results, token_budget
    )
    supervisor = SupervisorAgent(
        gateway,
        client,
        config,
        repository,
        code_search,
        reviewer,
        review_publisher,
        critic,
        repo_ops_factory,
        tool_results,
        token_budget,
        True,
    )
    result = await supervisor.run(
        f"Review PR #{config.pr_number} and tell me if it's safe to merge — do not merge it yourself"
    )
    graph = supervisor.graph
    if graph is None:
        raise RuntimeError("Supervisor did not create a task graph")
    print("SUBTASKS")
    for task in graph.subtasks:
        print(f"- {task.id}: agent={task.assigned_to} status={task.status}")
    print("\nTOOL CALLS")
    for call in result.tool_calls_made:
        tier = classifier.classify(call)
        entries = [
            entry
            for entry in audit_logger.list_entries(graph.run_id)
            if entry["tool_name"] == call.tool_name and entry["decision"] != "pending"
        ]
        decision = entries[-1]["decision"]
        reason = "Tier 3 actions are blocked outright" if tier == "tier3" else "policy checks passed"
        print(
            f"- {call.tool_name} {json.dumps(call.parameters, sort_keys=True)} "
            f"tier={tier} decision={decision} reason={reason}"
        )
    verdict = "PASS" if supervisor.critic_verdict.passed else "FAIL"
    print(f"\nCRITIC VERDICT\n{verdict}")
    print(f"\nFINAL ANSWER\n{result.content}")
    print("\nAUDIT LOG")
    for entry in audit_logger.list_entries(graph.run_id):
        print(json.dumps(entry, sort_keys=True))


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
