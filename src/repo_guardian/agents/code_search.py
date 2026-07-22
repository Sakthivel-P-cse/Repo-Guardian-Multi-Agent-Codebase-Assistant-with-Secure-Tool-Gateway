from repo_guardian.agents.base import BaseAgent
from repo_guardian.domain.agent import AgentResult
from repo_guardian.domain.task import SubTask, TaskGraph
from repo_guardian.domain.tool_call import ToolCall


class CodeSearchAgent(BaseAgent):
    def __init__(
        self, gateway, llm_client, config, result_sink=None, token_budget=None
    ) -> None:
        super().__init__(
            gateway,
            llm_client,
            config,
            "You inspect repository evidence using read-only tools and report only grounded findings.",
            result_sink,
            token_budget,
        )

    async def run(self, task: SubTask, context: TaskGraph) -> AgentResult:
        pr_number = self._config.pr_number
        calls = [
            ToolCall("get_pr", {"pr_number": pr_number}, "code_search", context.run_id),
            ToolCall("get_diff", {"pr_number": pr_number}, "code_search", context.run_id),
        ]
        results = [await self._gateway.execute(call, context) for call in calls]
        pr = results[0].output
        commit_call = ToolCall(
            "list_commits",
            {"branch": pr["head"], "limit": 10},
            "code_search",
            context.run_id,
        )
        calls.append(commit_call)
        results.append(await self._gateway.execute(commit_call, context))
        self._result_sink.extend(results)
        prompt = (
            "CODE_SEARCH_SUMMARY\n"
            f"Task: {task.description}\n"
            f"Tool results: {[(result.tool_name, result.output) for result in results]}\n"
            f"State whether PR #{pr_number} is safe to merge and cite only these results."
        )
        content = await self._ask(prompt)
        return AgentResult("code_search", content, calls, all(result.success for result in results))
