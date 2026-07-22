from dataclasses import dataclass

from repo_guardian.agents.base import BaseAgent
from repo_guardian.domain.tool_call import ToolResult


@dataclass(slots=True)
class CriticResult:
    passed: bool
    ungrounded_claims: list[str]


class CriticAgent(BaseAgent):
    def __init__(self, gateway, anthropic_client, config, token_budget=None) -> None:
        super().__init__(
            gateway,
            anthropic_client,
            config,
            "You identify factual claims that are not grounded in the supplied tool results.",
            token_budget=token_budget,
        )

    async def run(self, draft: str, tool_results: list[ToolResult]) -> CriticResult:
        if not tool_results:
            return CriticResult(False, [draft] if draft.strip() else ["No verifiable claims available"])
        prompt = (
            f"Here are the tool results from this run: {tool_results}\n"
            f"Here is the draft answer: {draft}\n"
            "For each specific factual claim in the draft, does it trace to one of the tool results above? "
            "List any claim that does NOT trace to a tool result. If all claims are grounded, say PASS."
        )
        response = await self._ask(prompt)
        if response.strip().upper() == "PASS":
            return CriticResult(True, [])
        claims = [
            line.lstrip("- ").strip()
            for line in response.splitlines()
            if line.lstrip("- ").strip().upper() not in {"FAIL", "FAILED"}
        ]
        return CriticResult(False, claims or [response.strip()])
