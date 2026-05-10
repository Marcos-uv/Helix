from backend.ai.ollama_client import generate_response
from backend.ai.provider import AIProvider

DEFAULT_MODEL = "llama3"


class OllamaProvider(AIProvider):
    async def generate(self, messages, **kwargs):
        model = kwargs.get("model") or DEFAULT_MODEL
        if str(model).startswith("gpt-"):
            model = DEFAULT_MODEL
        options = {
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 0.9),
            "num_predict": kwargs.get("num_predict", 512),
        }
        return await generate_response(messages, model=model, options=options)
