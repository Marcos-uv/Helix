def route_message(text: str) -> dict:
    text_clean = text.strip()
    text_lower = text_clean.lower()

    if not text_clean:
        return {
            "type": "empty",
            "confidence": 1.0,
            "reason": "Mensagem vazia.",
        }

    command_starts = [
        "abra ",
        "abrir ",
        "execute ",
        "executar ",
        "crie uma nota",
        "criar nota",
        "adicione em",
        "adicionar em",
        "salve no obsidian",
        "resuma no obsidian",
        "crie no obsidian",
    ]

    memory_keywords = [
        "vamos usar",
        "decidi",
        "decidimos",
        "ficou decidido",
        "quero que o helix lembre",
        "o helix deve",
        "o helix precisa",
        "prefiro",
        "não quero",
    ]

    if any(text_lower.startswith(cmd) for cmd in command_starts):
        return {
            "type": "command",
            "confidence": 0.9,
            "reason": "Mensagem começa como comando explícito.",
        }

    if any(keyword in text_lower for keyword in memory_keywords):
        return {
            "type": "memory",
            "confidence": 0.85,
            "reason": "Mensagem parece conter decisão, preferência ou regra.",
        }

    return {
        "type": "chat",
        "confidence": 0.75,
        "reason": "Mensagem comum de conversa.",
    }