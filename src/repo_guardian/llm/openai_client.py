from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI


class OpenAIMessageClient:
    """Compatibility layer for OpenAI-style Chat Completions providers."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.messages = self

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None = None,
    ) -> Any:
        request_messages = []
        if system:
            request_messages.append({"role": "system", "content": system})
        request_messages.extend(messages)
        stream = await self._client.chat.completions.create(
            model=model,
            messages=request_messages,
            max_tokens=max_tokens,
            temperature=1,
            top_p=1,
            seed=42,
            stream=True,
        )
        content = []
        output_tokens = None
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                output_tokens = getattr(usage, "completion_tokens", output_tokens)
            if not chunk.choices:
                continue
            text = chunk.choices[0].delta.content
            if text:
                content.append(text)
        return SimpleNamespace(
            content="".join(content),
            usage=SimpleNamespace(output_tokens=output_tokens),
        )
