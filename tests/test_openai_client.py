from types import SimpleNamespace

from repo_guardian.llm.openai_client import OpenAIMessageClient


class Completions:
    def __init__(self) -> None:
        self.request = None

    async def create(self, **request):
        self.request = request

        async def chunks():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="ans"))],
                usage=None,
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="wer"))],
                usage=SimpleNamespace(completion_tokens=7),
            )

        return chunks()


async def test_translates_message_request_to_chat_completions():
    completions = Completions()
    client = OpenAIMessageClient.__new__(OpenAIMessageClient)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client.messages = client

    response = await client.messages.create(
        model="z-ai/glm-5.2",
        max_tokens=100,
        system="system rules",
        messages=[{"role": "user", "content": "question"}],
    )

    assert completions.request == {
        "model": "z-ai/glm-5.2",
        "max_tokens": 100,
        "temperature": 1,
        "top_p": 1,
        "seed": 42,
        "stream": True,
        "messages": [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "question"},
        ],
    }
    assert response.content == "answer"
    assert response.usage.output_tokens == 7
