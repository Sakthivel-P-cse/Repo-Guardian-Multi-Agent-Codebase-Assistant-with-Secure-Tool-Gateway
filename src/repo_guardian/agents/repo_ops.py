from repo_guardian.agents.base import BaseAgent
from repo_guardian.domain.agent import AgentResult
from repo_guardian.domain.task import SubTask, TaskGraph
from repo_guardian.domain.tool_call import ToolCall


class RepoOpsAgent(BaseAgent):
    def __init__(
        self, gateway, llm_client, config, result_sink=None, token_budget=None
    ) -> None:
        super().__init__(
            gateway,
            llm_client,
            config,
            "You submit explicitly planned repository operations only through the secure gateway.",
            result_sink,
            token_budget,
        )

    async def run(self, task: SubTask, context: TaskGraph) -> AgentResult:
        call = ToolCall(
            "merge_pr",
            {
                "pr_number": self._config.pr_number,
                "base": "main",
                "merge_method": "merge",
            },
            "repo_ops",
            context.run_id,
        )
        result = await self._gateway.execute(call, context)
        self._result_sink.append(result)
        content = f"merge_pr returned success={result.success} and verified={result.verified}."
        return AgentResult("repo_ops", content, [call], True)
