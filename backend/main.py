from pathlib import Path

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.api.system_routes import router as system_router
from backend.api.obsidian_routes import router as obsidian_router
from backend.api.memory_routes import router as memory_router
from backend.api.voice_routes import router as voice_router
from backend.api.dev_environment_routes import router as dev_environment_router

from backend.core.database import get_db, init_db
from backend.core.obsidian_service import (
    ensure_obsidian_structure,
    log_error_to_obsidian,
    log_event_to_obsidian,
)
from fastapi.responses import FileResponse
from backend.core.tts_edge import generate_tts_audio

from backend.schemas.chat_schema import ChatRequest
from backend.services.chat_service import process_chat_logic
from pydantic import BaseModel
from backend.api import app_registry_routes
from backend.models.known_app import KnownApp


app = FastAPI()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"ERRO GLOBAL: {exc}")

    try:
        log_error_to_obsidian(
            error=str(exc),
            context=f"{request.method} {request.url.path}",
        )
    except Exception as log_exc:
        print(f"Erro ao registrar erro global no Obsidian: {log_exc}")

    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "response": "Erro interno no Helix.",
        },
    )


app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount(
        "/app",
        StaticFiles(directory=FRONTEND_DIR, html=True),
        name="frontend",
    )


@app.on_event("startup")
def startup():
    init_db()

    try:
        ensure_obsidian_structure()

        log_event_to_obsidian(
            event="Backend iniciado.",
            context="startup",
            details="FastAPI iniciou e verificou a estrutura do Obsidian.",
        )

    except Exception as exc:
        print(f"Erro ao registrar evento de startup no Obsidian: {exc}")


@app.get("/")
def home():
    return {
        "message": "Helix backend rodando!",
        "app": "/app",
        "status": "/status",
    }


@app.get("/status")
def status():
    return {
        "status": "ok",
    }


app.include_router(system_router)
app.include_router(obsidian_router)
app.include_router(memory_router)
app.include_router(voice_router)
app.include_router(dev_environment_router)

app.include_router(app_registry_routes.router)

@app.post("/chat")
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    return await process_chat_logic(request, db)

class VoiceText(BaseModel):
    text: str
@app.post("/tts")
async def tts(request: VoiceText):
    try:
        audio_path = await generate_tts_audio(request.text)

        return FileResponse(
            path=str(audio_path),
            media_type="audio/mpeg",
            filename="helix_tts.mp3",
        )

    except Exception as e:
        print(f"ERRO NO /tts EDGE-TTS: {e}")
        return {
            "error": "Falha ao gerar áudio com edge-tts.",
            "detail": str(e),
        }