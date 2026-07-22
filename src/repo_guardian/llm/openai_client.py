from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI


class OpenAIMessageClient:
    """Small compatibility layer for the project's existing message interface."""

    def __init__(self, api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self.messages = self

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None = None,
    ) -> Any:
        request: dict[str, Any] = {
            "model": model,
            "input": messages,
            "max_output_tokens": max_tokens,
        }
        if system:
            request["instructions"] = system
        response = await self._client.responses.create(**request)
        return SimpleNamespace(
            content=response.output_text,
            usage=getattr(response, "usage", None),
        )
