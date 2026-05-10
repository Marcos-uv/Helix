import os
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_provider():
    _load_dotenv()
    configured = os.getenv("USE_GPT", os.getenv("USER_GPT"))
    if configured is None:
        use_gpt = bool(os.getenv("OPENAI_API_KEY"))
    else:
        use_gpt = configured.strip().lower() in {"1", "true", "yes", "sim", "on"}

    if use_gpt:
        from backend.ai.gpt_provider import GPTProvider
        return GPTProvider()

    from backend.ai.ollama_provider import OllamaProvider
    return OllamaProvider()
