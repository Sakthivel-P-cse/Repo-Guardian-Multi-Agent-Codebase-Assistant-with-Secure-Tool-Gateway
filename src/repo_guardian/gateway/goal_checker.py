from typing import Any, Protocol

from repo_guardian.domain.task import RunTokenBudget, TaskGraph, TokenBudgetExceeded
from repo_guardian.domain.tool_call import ToolCall


class GoalCheckerPort(Protocol):
    async def check(self, call: ToolCall, task_graph: TaskGraph) -> tuple[bool, str]: ...


class GoalConsistencyChecker:
    def __init__(
        self,
        anthropic_client: Any,
        model: str,
        enabled: bool = True,
        token_budget: RunTokenBudget | None = None,
    ) -> None:
        self._client = anthropic_client
        self._model = model
        self._enabled = enabled
        self._token_budget = token_budget

    async def check(self, call: ToolCall, task_graph: TaskGraph) -> tuple[bool, str]:
        if not self._enabled:
            return True, "Goal consistency check disabled"
        if self._token_budget is not None and self._token_budget.remaining <= 0:
            raise TokenBudgetExceeded("Maximum token limit reached")
        prompt = (
            f"Given the user's goal: {task_graph.original_goal}. Is this tool call: "
            f"{call.tool_name}({call.parameters}) consistent with achieving that goal? "
            "Answer YES or NO and one sentence of reasoning."
        )
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=min(100, self._token_budget.remaining)
            if self._token_budget is not None
            else 100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = self._response_text(response).strip()
        if self._token_budget is not None:
            usage = getattr(response, "usage", None)
            output_tokens = getattr(usage, "output_tokens", None)
            measured = output_tokens if output_tokens is not None else max(1, len(text) // 4)
            self._token_budget.consume(min(measured, self._token_budget.remaining))
        consistent = text.upper().startswith("YES")
        return consistent, text

    @staticmethod
    def _response_text(response: Any) -> str:
        content = response.content
        if isinstance(content, str):
            return content
        return "".join(getattr(block, "text", "") for block in content)
