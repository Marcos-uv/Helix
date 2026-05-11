from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.database import get_db, Memory, get_or_create_user
from backend.core.memory_service import (
    save_memory_if_relevant,
    update_memory,
    delete_memory,
)


router = APIRouter(
    prefix="/memories",
    tags=["Memories"],
)


class MemoryCreateRequest(BaseModel):
    content: str
    user_name: str = "marcos"
    owner_type: str = "user"
    category: str = "general"
    importance: int = Field(default=3, ge=1, le=5)
    source: str = "manual"


class MemoryUpdateRequest(BaseModel):
    content: Optional[str] = None
    owner_type: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    source: Optional[str] = None


def memory_to_dict(memory: Memory) -> dict:
    return {
        "id": memory.id,
        "user_id": memory.user_id,
        "owner_type": memory.owner_type,
        "category": memory.category,
        "content": memory.content,
        "importance": memory.importance,
        "source": memory.source,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "last_used_at": memory.last_used_at,
    }


@router.get("")
def list_memories(db: Session = Depends(get_db)):
    memories = (
        db.query(Memory)
        .order_by(
            Memory.importance.desc(),
            Memory.created_at.desc(),
        )
        .all()
    )

    return {
        "count": len(memories),
        "memories": [
            memory_to_dict(memory)
            for memory in memories
        ],
    }


@router.get("/{memory_id}")
def get_memory(memory_id: int, db: Session = Depends(get_db)):
    memory = db.query(Memory).filter(Memory.id == memory_id).first()

    if not memory:
        raise HTTPException(
            status_code=404,
            detail="Memória não encontrada.",
        )

    return memory_to_dict(memory)


@router.post("")
def create_memory(
    request: MemoryCreateRequest,
    db: Session = Depends(get_db),
):
    content = request.content.strip()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="O conteúdo da memória não pode estar vazio.",
        )

    user = get_or_create_user(db, request.user_name)

    owner_type = request.owner_type.strip().lower()
    category = request.category.strip().lower()
    source = request.source.strip().lower()

    if owner_type not in ["user", "project", "system"]:
        raise HTTPException(
            status_code=400,
            detail="owner_type deve ser: user, project ou system.",
        )

    memory = Memory(
        user_id=user.id if owner_type == "user" else None,
        owner_type=owner_type,
        category=category or "general",
        content=content,
        importance=request.importance,
        source=source or "manual",
    )

    db.add(memory)
    db.commit()
    db.refresh(memory)

    return {
        "status": "created",
        "memory": memory_to_dict(memory),
    }


@router.post("/auto")
def create_memory_auto(
    request: MemoryCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Tenta classificar automaticamente uma memória usando save_memory_if_relevant.
    Útil para testar o filtro inteligente.
    """
    user = get_or_create_user(db, request.user_name)

    memory = save_memory_if_relevant(
        db=db,
        user_id=user.id,
        message=request.content,
    )

    if not memory:
        return {
            "status": "ignored",
            "reason": "A mensagem não foi considerada uma memória relevante.",
        }

    return {
        "status": "created",
        "memory": memory_to_dict(memory),
    }


@router.put("/{memory_id}")
def edit_memory(
    memory_id: int,
    request: MemoryUpdateRequest,
    db: Session = Depends(get_db),
):
    memory = update_memory(
        db=db,
        memory_id=memory_id,
        content=request.content,
        owner_type=request.owner_type,
        category=request.category,
        importance=request.importance,
        source=request.source,
    )

    if not memory:
        raise HTTPException(
            status_code=404,
            detail="Memória não encontrada ou não foi possível atualizar.",
        )

    return {
        "status": "updated",
        "memory": memory_to_dict(memory),
    }


@router.delete("/{memory_id}")
def remove_memory(
    memory_id: int,
    db: Session = Depends(get_db),
):
    deleted = delete_memory(db, memory_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Memória não encontrada.",
        )

    return {
        "status": "deleted",
        "memory_id": memory_id,
    }