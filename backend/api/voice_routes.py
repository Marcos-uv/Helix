import os
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Response, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from backend.ai.factory import _load_dotenv
from backend.core.database import get_db
from backend.core.obsidian_service import log_error_to_obsidian
from backend.core.voice_handler import generate_elevenlabs_audio, listen_and_transcribe
from backend.schemas.chat_schema import ChatRequest, TTSRequest
from backend.services.chat_service import process_chat_logic


router = APIRouter()


@router.post("/tts")
async def tts(request: TTSRequest):
    try:
        audio = await run_in_threadpool(generate_elevenlabs_audio, request.text)

        if not audio:
            return {
                "error": "ElevenLabs não configurado ou texto vazio.",
            }

        return Response(
            content=audio,
            media_type="audio/mpeg",
        )

    except Exception as e:
        print("ERRO /tts:", e)

        try:
            log_error_to_obsidian(
                error=str(e),
                context="/tts",
                user_message=request.text,
            )
        except Exception as log_exc:
            print(f"Erro ao registrar erro no Obsidian: {log_exc}")

        return {"error": str(e)}


@router.post("/voice/transcribe")
async def voice_transcribe(duration: int = 6):
    try:
        user_text = await run_in_threadpool(listen_and_transcribe, duration)

        if not user_text:
            return {
                "text": "",
                "error": "Não ouvi nada.",
            }

        if user_text.startswith("Erro:"):
            return {
                "text": "",
                "error": user_text,
            }

        return {"text": user_text}

    except Exception as e:
        print("ERRO /voice/transcribe:", e)

        try:
            log_error_to_obsidian(
                error=str(e),
                context="/voice/transcribe",
            )
        except Exception as log_exc:
            print(f"Erro ao registrar erro no Obsidian: {log_exc}")

        return {
            "text": "",
            "error": str(e),
        }


@router.post("/voice/transcribe-file")
async def voice_transcribe_file(audio: UploadFile = File(...)):
    _load_dotenv()

    audio_bytes = await audio.read()

    if not audio_bytes:
        return {
            "text": "",
            "error": "Áudio vazio.",
        }

    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    temp_path = None

    client = AsyncOpenAI(
        http_client=httpx.AsyncClient(trust_env=False),
    )

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name

        with open(temp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
                file=audio_file,
                language="pt",
            )

        return {"text": transcription.text.strip()}

    except Exception as e:
        print("ERRO /voice/transcribe-file:", e)

        try:
            log_error_to_obsidian(
                error=str(e),
                context="/voice/transcribe-file",
                user_message=audio.filename,
            )
        except Exception as log_exc:
            print(f"Erro ao registrar erro no Obsidian: {log_exc}")

        return {
            "text": "",
            "error": str(e),
        }

    finally:
        await client.close()

        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass


@router.post("/voice/chat")
async def voice_chat(duration: int = 5, db: Session = Depends(get_db)):
    try:
        user_text = await run_in_threadpool(listen_and_transcribe, duration)

        if not user_text or user_text.startswith("Erro:"):
            return {
                "error": user_text or "Não ouvi nada.",
            }

        request = ChatRequest(
            message=user_text,
            voice_mode=True,
        )

        response = await process_chat_logic(request, db)

        return {
            "user_text": user_text,
            "response": response.get("response", ""),
            "spoken": False,
        }

    except Exception as e:
        print("ERRO /voice/chat:", e)

        try:
            log_error_to_obsidian(
                error=str(e),
                context="/voice/chat",
            )
        except Exception as log_exc:
            print(f"Erro ao registrar erro no Obsidian: {log_exc}")

        return {"error": str(e)}