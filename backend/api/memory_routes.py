from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.database import get_db, Memory


router = APIRouter()


@router.get("/memories")
def get_memories(db: Session = Depends(get_db)):
    try:
        memories = db.query(Memory).order_by(
            Memory.importance.desc(),
            Memory.created_at.desc(),
        ).all()

        return {
            "count": len(memories),
            "memories": [
                {
                    "id": memory.id,
                    "user_id": memory.user_id,
                    "owner_type": memory.owner_type,
                    "category": memory.category,
                    "content": memory.content,
                    "importance": memory.importance,
                    "created_at": memory.created_at,
                }
                for memory in memories
            ],
        }

    except Exception as e:
        return {
            "error": str(e),
        }


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    try:
        memory = db.query(Memory).filter(Memory.id == memory_id).first()

        if not memory:
            return {
                "delete": False,
                "message": "Memória não encontrada.",
            }

        db.delete(memory)
        db.commit()

        return {
            "delete": True,
            "message": f"Memória {memory_id} apagada com sucesso.",
        }

    except Exception as e:
        db.rollback()

        return {
            "delete": False,
            "error": str(e),
        }