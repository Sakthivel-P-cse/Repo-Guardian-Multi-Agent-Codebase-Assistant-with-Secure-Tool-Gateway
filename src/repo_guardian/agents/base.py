from abc import ABC, abstractmethod
from typing import Any

from repo_guardian.config import Config
from repo_guardian.domain.task import RunTokenBudget, SubTask, TaskGraph, TokenBudgetExceeded
from repo_guardian.domain.tool_call import ToolResult
from repo_guardian.gateway.gateway import SecureToolGateway

GROUNDING_RULES = """Grounding rules:
1. Answer only from tool results in this conversation.
2. If you cannot find the answer in tool results, say \"I cannot determine this from the available data\".
3. Never fill gaps from general training knowledge about codebases.
4. Every specific claim must be traceable to a specific tool result."""


class BaseAgent(ABC):
    def __init__(
        self,
        gateway: SecureToolGateway,
        anthropic_client: Any,
        config: Config,
        system_prompt: str,
        result_sink: list[ToolResult] | None = None,
        token_budget: RunTokenBudget | None = None,
    ) -> None:
        self._gateway = gateway
        self._client = anthropic_client
        self._config = config
        self._system_prompt = f"{system_prompt}\n\n{GROUNDING_RULES}"
        self._result_sink = result_sink if result_sink is not None else []
        self._token_budget = token_budget or RunTokenBudget(config.max_tokens_per_run)

    @abstractmethod
    async def run(self, task: SubTask, context: TaskGraph) -> Any:
        raise NotImplementedError

    async def _ask(self, prompt: str, max_tokens: int = 600) -> str:
        if self._token_budget.remaining <= 0:
            raise TokenBudgetExceeded("Maximum token limit reached")
        response = await self._client.messages.create(
            model=self._config.model,
            max_tokens=min(max_tokens, self._token_budget.remaining),
            system=self._system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content
        text = (
            content.strip()
            if isinstance(content, str)
            else "".join(getattr(block, "text", "") for block in content).strip()
        )
        usage = getattr(response, "usage", None)
        output_tokens = getattr(usage, "output_tokens", None)
        measured = output_tokens if output_tokens is not None else max(1, len(text) // 4)
        self._token_budget.consume(min(measured, self._token_budget.remaining))
        return text
