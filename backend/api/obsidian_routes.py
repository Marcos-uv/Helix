from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.database import get_db, Memory
from backend.core.memory_service import (
    should_sync_to_obsidian,
)
from backend.core.obsidian_service import (
    OBSIDIAN_VAULT_PATH,
    HELIX_BRAIN_DIR,
    HELIX_LOGS_DIR,
    BRAIN_FOLDERS,
    LOGS_FOLDERS,
    ensure_obsidian_structure,
    log_event_to_obsidian,
    search_obsidian_notes,
    read_obsidian_note_by_path,
    save_memory_to_obsidian,
    scan_loose_obsidian_notes,
    move_obsidian_note,
    find_possible_duplicate_notes,
    move_note_to_trash,
)
from backend.core.system_monitor import run_automatic_pc_checkup
from backend.services.dashboard_service import update_helix_dashboard
from sqlalchemy.orm import Session
from fastapi import Depends


router = APIRouter()


class OrganizeNoteRequest(BaseModel):
    path: str
    destination_folder: str


class TrashNoteRequest(BaseModel):
    path: str
    confirm: bool = False
    reason: str = "Possível duplicata confirmada pelo usuário."


@router.get("/obsidian/status")
def obsidian_status():
    try:
        ensure_obsidian_structure()

        brain_folders_status = {}

        for folder in BRAIN_FOLDERS:
            folder_path = HELIX_BRAIN_DIR / folder
            brain_folders_status[folder] = {
                "exists": folder_path.exists(),
                "notes_count": len(list(folder_path.glob("*.md")))
                if folder_path.exists()
                else 0,
            }

        logs_folders_status = {}

        for folder in LOGS_FOLDERS:
            folder_path = HELIX_LOGS_DIR / folder
            logs_folders_status[folder] = {
                "exists": folder_path.exists(),
                "notes_count": len(list(folder_path.glob("*.md")))
                if folder_path.exists()
                else 0,
            }

        brain_root_notes = (
            len(list(HELIX_BRAIN_DIR.glob("*.md")))
            if HELIX_BRAIN_DIR.exists()
            else 0
        )

        logs_root_notes = (
            len(list(HELIX_LOGS_DIR.glob("*.md")))
            if HELIX_LOGS_DIR.exists()
            else 0
        )

        try:
            log_event_to_obsidian(
                event="Status do Obsidian consultado.",
                context="/obsidian/status",
                details="O Helix verificou a estrutura do vault.",
            )
        except Exception as log_exc:
            print(f"Erro ao registrar evento no Obsidian: {log_exc}")

        return {
            "vault_path": str(OBSIDIAN_VAULT_PATH),
            "vault_exists": OBSIDIAN_VAULT_PATH.exists(),
            "helix_brain_exists": HELIX_BRAIN_DIR.exists(),
            "helix_logs_exists": HELIX_LOGS_DIR.exists(),
            "brain_root_notes": brain_root_notes,
            "logs_root_notes": logs_root_notes,
            "brain_folders": brain_folders_status,
            "logs_folders": logs_folders_status,
        }

    except Exception as e:
        return {
            "error": str(e),
            "vault_path": str(OBSIDIAN_VAULT_PATH),
        }


@router.get("/obsidian/search")
def obsidian_search(query: str, limit: int = 10, scope: str = "brain"):
    try:
        results = search_obsidian_notes(
            query=query,
            limit=limit,
            scope=scope,
        )

        return {
            "query": query,
            "scope": scope,
            "count": len(results),
            "results": results,
        }

    except Exception as e:
        return {
            "error": str(e),
            "query": query,
            "scope": scope,
        }


@router.get("/obsidian/read")
def obsidian_read(path: str):
    try:
        return read_obsidian_note_by_path(path)

    except Exception as e:
        return {
            "found": False,
            "error": str(e),
            "path": path,
        }


@router.get("/obsidian/scan-loose")
def obsidian_scan_loose(limit: int = 50):
    try:
        result = scan_loose_obsidian_notes(limit=limit)

        try:
            log_event_to_obsidian(
                event="Scanner de notas soltas executado.",
                context="/obsidian/scan-loose",
                details=f"Notas encontradas: {result['count']}",
            )
        except Exception as log_exc:
            print(f"Erro ao registrar evento do scanner: {log_exc}")

        return result

    except Exception as e:
        return {
            "error": str(e),
        }


@router.post("/obsidian/organize-note")
def obsidian_organize_note(request: OrganizeNoteRequest):
    try:
        result = move_obsidian_note(
            relative_path=request.path,
            destination_folder=request.destination_folder,
        )

        try:
            log_event_to_obsidian(
                event="Nota organizada no Obsidian.",
                context="/obsidian/organize-note",
                details=(
                    f"Origem: {request.path} | "
                    f"Destino: {request.destination_folder} | "
                    f"Movida: {result.get('moved')}"
                ),
            )
        except Exception as log_exc:
            print(f"Erro ao registrar evento de organização: {log_exc}")

        return result

    except Exception as e:
        return {
            "moved": False,
            "error": str(e),
        }


@router.get("/obsidian/duplicates")
def obsidian_duplicates(path: str, threshold: float = 0.72, limit: int = 5):
    try:
        result = find_possible_duplicate_notes(
            relative_path=path,
            threshold=threshold,
            limit=limit,
        )

        try:
            log_event_to_obsidian(
                event="Verificação de duplicata executada.",
                context="/obsidian/duplicates",
                details=(
                    f"Origem: {path} | "
                    f"Possível duplicata: {result.get('possible_duplicate')}"
                ),
            )
        except Exception as log_exc:
            print(f"Erro ao registrar evento de duplicata: {log_exc}")

        return result

    except Exception as e:
        return {
            "found": False,
            "error": str(e),
            "source": path,
        }


@router.post("/obsidian/trash-note")
def obsidian_trash_note(request: TrashNoteRequest):
    if not request.confirm:
        return {
            "moved": False,
            "error": "Confirmação obrigatória. Envie confirm=true para mover para a lixeira.",
            "path": request.path,
        }

    try:
        return move_note_to_trash(
            relative_path=request.path,
            reason=request.reason,
        )

    except Exception as e:
        return {
            "moved": False,
            "error": str(e),
            "path": request.path,
        }


@router.post("/obsidian/dashboard/update")
def obsidian_dashboard_update():
    try:
        checkup = run_automatic_pc_checkup(
            drive_path="C:/",
            low_free_space_gb=30,
        )

        dashboard_path = update_helix_dashboard(checkup)

        if not dashboard_path:
            return {
                "updated": False,
                "error": "Não foi possível atualizar o dashboard.",
            }

        try:
            log_event_to_obsidian(
                event="Dashboard Helix atualizado.",
                context="/obsidian/dashboard/update",
                details=f"Dashboard atualizado em: {dashboard_path}",
            )
        except Exception as log_exc:
            print(f"Erro ao registrar atualização do dashboard: {log_exc}")

        return {
            "updated": True,
            "dashboard_path": str(dashboard_path),
            "status": checkup.get("status"),
            "summary": checkup.get("summary"),
        }

    except Exception as e:
        return {
            "updated": False,
            "error": str(e),
        }


@router.post("/memories/sync-obsidian")
def sync_memories_to_obsidian(db: Session = Depends(get_db)):
    try:
        memories = db.query(Memory).order_by(
            Memory.importance.desc(),
            Memory.created_at.desc(),
        ).all()

        synced = []
        skipped = []
        errors = []

        for memory in memories:
            should_sync = should_sync_to_obsidian(
                category=memory.category,
                owner_type=memory.owner_type,
                importance=memory.importance,
            )

            if not should_sync:
                skipped.append(
                    {
                        "id": memory.id,
                        "reason": "Memória não atende aos critérios de sincronização.",
                        "content": memory.content,
                    }
                )
                continue

            try:
                note_path = save_memory_to_obsidian(
                    content=memory.content,
                    category=memory.category,
                    owner_type=memory.owner_type,
                    importance=memory.importance,
                )

                synced.append(
                    {
                        "id": memory.id,
                        "content": memory.content,
                        "note_path": str(note_path) if note_path else None,
                    }
                )

            except Exception as exc:
                errors.append(
                    {
                        "id": memory.id,
                        "content": memory.content,
                        "error": str(exc),
                    }
                )

        try:
            log_event_to_obsidian(
                event="Memórias sincronizadas com o Obsidian.",
                context="/memories/sync-obsidian",
                details=(
                    f"Sincronizadas: {len(synced)} | "
                    f"Ignoradas: {len(skipped)} | "
                    f"Erros: {len(errors)}"
                ),
            )
        except Exception as log_exc:
            print(f"Erro ao registrar evento de sincronização: {log_exc}")

        return {
            "synced_count": len(synced),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
        }

    except Exception as e:
        return {
            "error": str(e),
        }