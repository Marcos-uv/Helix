import tempfile
from pathlib import Path

import edge_tts


DEFAULT_VOICE = "pt-BR-FranciscaNeural"


async def generate_tts_audio(text: str) -> Path:
    if not text or not text.strip():
        raise ValueError("Texto vazio para TTS.")

    output_path = Path(tempfile.gettempdir()) / "helix_tts.mp3"

    communicate = edge_tts.Communicate(
        text=text.strip(),
        voice=DEFAULT_VOICE,
        rate="+0%",
        volume="+0%",
        pitch="+0Hz",
    )

    await communicate.save(str(output_path))

    return output_path