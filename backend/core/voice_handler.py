import os
import subprocess
import tempfile
import threading
import asyncio
from pathlib import Path

import pyttsx3
import speech_recognition as sr

from backend.core.tts_edge import generate_tts_audio


recognizer = sr.Recognizer()
_speech_lock = threading.Lock()

_coqui_tts = None


# =========================
# 🔧 LOAD .ENV MANUAL
# =========================
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"

    if not env_path.exists():
        print("⚠️ .env não encontrado:", env_path)
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


def _env_enabled(name: str, default: bool = True) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


# =========================
# 🔊 PLAYER DE ÁUDIO
# =========================
def _play_audio_file(audio_path: str) -> None:
    script = """
Add-Type -AssemblyName PresentationCore
$player = New-Object System.Windows.Media.MediaPlayer
$player.Open([System.Uri]::new($args[0]))

while (-not $player.NaturalDuration.HasTimeSpan) {
    Start-Sleep -Milliseconds 50
}

$player.Play()
$duration = $player.NaturalDuration.TimeSpan.TotalMilliseconds
Start-Sleep -Milliseconds ([int]($duration + 250))
$player.Close()
"""

    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
            audio_path,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# =========================
# 🔊 EDGE TTS
# =========================
def _speak_with_edge_tts(text: str) -> bool:
    _load_dotenv()

    if not _env_enabled("EDGE_TTS_ENABLED", True):
        print("⚠️ Edge TTS desativado pelo .env")
        return False

    clean_text = " ".join(str(text).split())

    if not clean_text:
        return False

    try:
        audio_path = asyncio.run(generate_tts_audio(clean_text))

        if not audio_path or not Path(audio_path).exists():
            print("❌ Edge TTS não gerou arquivo de áudio")
            return False

        _play_audio_file(str(audio_path))

        try:
            Path(audio_path).unlink(missing_ok=True)
        except OSError:
            pass

        print("✅ Voz usada: Edge TTS")
        return True

    except Exception as e:
        print(f"❌ Erro Edge TTS: {e}")
        return False


# =========================
# 🔊 COQUI TTS OFFLINE
# =========================
def _get_coqui_tts():
    global _coqui_tts

    if _coqui_tts is not None:
        return _coqui_tts

    from TTS.api import TTS

    model_name = os.getenv("COQUI_MODEL", "tts_models/pt/cv/vits")

    print(f"⏳ Carregando Coqui TTS: {model_name}")
    _coqui_tts = TTS(model_name=model_name, progress_bar=False)
    print("✅ Coqui TTS carregado")

    return _coqui_tts


def _speak_with_coqui(text: str) -> bool:
    _load_dotenv()

    if not _env_enabled("COQUI_ENABLED", False):
        print("⚠️ Coqui desativado pelo .env")
        return False

    clean_text = " ".join(str(text).split())

    if not clean_text:
        return False

    try:
        tts = _get_coqui_tts()

        audio_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        audio_file.close()

        tts.tts_to_file(
            text=clean_text,
            file_path=audio_file.name,
        )

        _play_audio_file(audio_file.name)

        try:
            Path(audio_file.name).unlink(missing_ok=True)
        except OSError:
            pass

        print("✅ Voz usada: Coqui TTS")
        return True

    except Exception as e:
        print(f"❌ Erro Coqui TTS: {e}")
        return False


# =========================
# 🔊 PYTTSX3 FALLBACK FINAL
# =========================
def _get_tts_engine():
    engine = pyttsx3.init()
    engine.setProperty("rate", 185)
    engine.setProperty("volume", 0.95)

    for voice in engine.getProperty("voices"):
        voice_text = f"{voice.name} {voice.id}".lower()

        if (
            "brazil" in voice_text
            or "brasil" in voice_text
            or "portuguese" in voice_text
            or "pt-br" in voice_text
            or "pt" in voice_text
        ):
            engine.setProperty("voice", voice.id)
            break

    return engine


def _speak_with_pyttsx3(text: str) -> None:
    engine = _get_tts_engine()
    engine.say(text)
    engine.runAndWait()
    engine.stop()


# =========================
# 🎤 FUNÇÃO PRINCIPAL DE FALA
# =========================
def speak_text(text: str) -> None:
    clean_text = " ".join(str(text).split())

    if not clean_text:
        return

    print(f"🗣️ {clean_text}")

    def run():
        try:
            with _speech_lock:
                if _speak_with_edge_tts(clean_text):
                    return

                print("⚠️ Edge TTS indisponível. Tentando Coqui TTS...")
                if _speak_with_coqui(clean_text):
                    return

                print("⚠️ Coqui indisponível. Usando voz local pyttsx3...")
                _speak_with_pyttsx3(clean_text)

        except Exception as e:
            print(f"❌ Erro geral no TTS: {e}")

            try:
                _speak_with_pyttsx3(clean_text)
            except Exception as fallback_error:
                print(f"❌ Erro no fallback pyttsx3: {fallback_error}")

    threading.Thread(target=run, daemon=True).start()


# =========================
# 🎧 STT MICROFONE
# =========================
def listen_and_transcribe(duration: int = 5) -> str:
    try:
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.6
        recognizer.non_speaking_duration = 0.35

        with sr.Microphone() as source:
            print("🎧 Ouvindo...")
            recognizer.adjust_for_ambient_noise(source, duration=0.4)

            audio = recognizer.listen(
                source,
                timeout=duration,
                phrase_time_limit=duration,
            )

        text = recognizer.recognize_google(audio, language="pt-BR")
        print(f"📝 Você disse: {text}")
        return text

    except sr.WaitTimeoutError:
        return "Não ouvi nada"

    except sr.UnknownValueError:
        return "Não entendi o áudio"

    except Exception as e:
        return f"Erro: {str(e)}"


# =========================
# 🎧 STT ARQUIVO DE ÁUDIO
# =========================
def transcribe_audio_file(file_path: str) -> str:
    try:
        with sr.AudioFile(file_path) as source:
            audio = recognizer.record(source)

        text = recognizer.recognize_google(audio, language="pt-BR")
        print(f"📝 Transcrição do arquivo: {text}")
        return text

    except sr.UnknownValueError:
        return "Não entendi o áudio"

    except Exception as e:
        return f"Erro: {str(e)}"