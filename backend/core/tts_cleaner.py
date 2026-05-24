import re

def clean_text_for_tts(text: str) -> str:
    """
    Limpa texto formatado para ser usado em TTS.

    Objetivo:
    - Manter o texto original bonito no chat.
    - Remover markdown, símbolos e links da versão falada.
    """
    if not text:
        return ""
    
    cleaned = text

    cleaned = re.sub(
        r"```[\s\S]*?```",
        " O código foi enviado no chat. ",
        cleaned,
    )

    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", " link enviado no chat ", cleaned)
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"__(.*?)__", r"\1", cleaned)
    cleaned = re.sub(r"_(.*?)_", r"\1", cleaned)
    cleaned = re.sub(r"^\s*[-*+]\s+", ". ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", ". ", cleaned, flags=re.MULTILINE)

    symbols_to_remove = ["*","#","`",">","|","~","\\","{","}","[","]",]

    for symbol in symbols_to_remove:
        cleaned = cleaned.replace(symbol, "")
    
    cleaned = cleaned.replace(" - ", ". ")
    cleaned = cleaned.replace(" — ", ". ")
    cleaned = cleaned.replace(":", ".")

    cleaned = re.sub(r"\s+", " ", cleaned)

    cleaned = re.sub(r"([.!?]){2,}", r"\1", cleaned)

    return cleaned.strip()