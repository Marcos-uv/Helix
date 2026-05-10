import httpx
from openai import AsyncOpenAI
from backend.ai.provider import AIProvider


class GPTProvider(AIProvider):
    def __init__(self):
        self.client = AsyncOpenAI(
            http_client=httpx.AsyncClient(trust_env=False)
        )

    async def generate(self, messages, **kwargs):
        response = await self.client.chat.completions.create(
            model=kwargs.get("model", "gpt-4.1-mini"),
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            top_p=kwargs.get("top_p", 0.9),
        )

        return response.choices[0].message.content
