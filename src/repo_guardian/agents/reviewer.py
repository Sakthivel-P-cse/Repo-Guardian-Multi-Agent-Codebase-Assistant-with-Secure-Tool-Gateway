from repo_guardian.agents.base import BaseAgent
from repo_guardian.domain.agent import AgentResult
from repo_guardian.domain.task import SubTask, TaskGraph
from repo_guardian.domain.tool_call import ToolCall


class ReviewPublisher:
    def __init__(self, gateway, result_sink, pr_number: int) -> None:
        self._gateway = gateway
        self._result_sink = result_sink
        self._pr_number = pr_number

    async def publish(self, body: str, context: TaskGraph):
        call = ToolCall(
            "post_comment",
            {"pr_number": self._pr_number, "body": body},
            "reviewer",
            context.run_id,
        )
        result = await self._gateway.execute(call, context)
        self._result_sink.append(result)
        return call, result


class ReviewAgent(BaseAgent):
    def __init__(
        self, gateway, llm_client, config, result_sink=None, token_budget=None
    ) -> None:
        super().__init__(
            gateway,
            llm_client,
            config,
            "You draft concise review feedback from supervisor-approved evidence before posting it.",
            result_sink,
            token_budget,
        )

    async def run(self, task: SubTask, context: TaskGraph) -> AgentResult:
        evidence = next(
            (subtask.result for subtask in context.subtasks if subtask.assigned_to == "code_search"),
            None,
        )
        draft = await self._ask(
            "REVIEW_DRAFT\n"
            f"Supervisor-approved task: {task.description}\n"
            f"Evidence: {evidence}\n"
            "Draft one review comment that does not approve or merge the pull request."
        )
        return AgentResult("reviewer", draft, [], evidence is not None)
