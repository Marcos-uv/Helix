import httpx

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"


async def generate_response(messages, model="llama3", options=None):
    payload = {
        "model": model or "llama3",
        "messages": messages,
        "stream": False,
    }

    if options:
        payload["options"] = options

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                OLLAMA_URL,
                json=payload
            )
            response.raise_for_status()
    except httpx.ConnectError as exc:
        raise RuntimeError(
            "Ollama nao esta rodando em http://127.0.0.1:11434. "
            "Inicie o Ollama ou configure OPENAI_API_KEY para usar GPT."
        ) from exc

    data = response.json()
    
    return data.get("message", {}).get("content", "Erro na resposta do Ollama")
