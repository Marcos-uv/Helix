from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.database import Memory


QUESTION_STARTS = (
    "o que",
    "oque",
    "qual",
    "quais",
    "como",
    "quando",
    "onde",
    "por que",
    "porque",
    "será",
    "sera",
    "posso",
    "pode",
    "devo",
    "vale",
    "tem como",
)

QUESTION_MARKERS = (
    "?",
    "me explica",
    "explique",
    "me diga",
    "você acha",
    "voce acha",
    "o que acha",
    "qual seria",
    "como seria",
    "como faço",
    "como faco",
)


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def lower_text(text: str) -> str:
    return normalize_text(text).lower()


def is_question(text: str) -> bool:
    clean = lower_text(text)

    if not clean:
        return False

    if clean.endswith("?"):
        return True

    if any(clean.startswith(start) for start in QUESTION_STARTS):
        return True

    if any(marker in clean for marker in QUESTION_MARKERS):
        return True

    return False


def is_too_weak_memory(text: str) -> bool:
    clean = lower_text(text)

    if len(clean) < 12:
        return True

    weak_phrases = {
        "sim",
        "não",
        "nao",
        "ok",
        "beleza",
        "vamos",
        "bora",
        "entendi",
        "certo",
        "deu certo",
        "funcionou",
        "voltou a funcionar",
    }

    return clean in weak_phrases


def classify_memory(text: str) -> dict | None:
    """
    Decide se uma mensagem deve virar memória.

    Retorna:
    {
        "owner_type": "user" | "project" | "system",
        "category": "...",
        "content": "...",
        "importance": 1-5,
        "source": "chat"
    }

    Ou None se não deve salvar.
    """
    original = normalize_text(text)
    clean = lower_text(text)

    if not original:
        return None

    if is_too_weak_memory(original):
        return None

    if is_question(original):
        return None

    system_rule_markers = [
        "regra do helix",
        "o helix deve sempre",
        "helix deve sempre",
        "o helix nunca deve",
        "helix nunca deve",
        "sempre pedir confirmação",
        "pedir confirmação antes",
        "não apague",
        "nao apague",
        "nunca apague",
        "não delete",
        "nao delete",
        "nunca delete",
        "não remova",
        "nao remova",
        "nunca remova",
    ]

    if any(marker in clean for marker in system_rule_markers):
        content = original

        if not clean.startswith("regra do helix"):
            content = f"Regra do Helix: {original}"

        return {
            "owner_type": "system",
            "category": "system_rule",
            "content": content,
            "importance": 5,
            "source": "chat",
        }

    project_decision_markers = [
        "decisão técnica",
        "decisao tecnica",
        "decidimos",
        "decidi",
        "vamos usar",
        "vou usar",
        "o helix usará",
        "o helix usara",
        "helix usará",
        "helix usara",
        "será usado",
        "sera usado",
        "será a memória principal",
        "sera a memoria principal",
        "continuará usando",
        "continuara usando",
        "backend do helix",
        "frontend do helix",
        "postgres",
        "postgresql",
        "fastapi",
        "obsidian",
    ]

    strong_project_context = [
        "helix",
        "backend",
        "frontend",
        "postgres",
        "postgresql",
        "fastapi",
        "obsidian",
        "banco",
        "memória",
        "memoria",
        "arquitetura",
    ]

    has_decision_marker = any(marker in clean for marker in project_decision_markers)
    has_project_context = any(marker in clean for marker in strong_project_context)

    if has_decision_marker and has_project_context:
        content = original

        if not clean.startswith("decisão técnica") and not clean.startswith("decisao tecnica"):
            content = f"Decisão técnica: {original}"

        return {
            "owner_type": "project",
            "category": "technical_decision",
            "content": content,
            "importance": 5,
            "source": "chat",
        }


    user_preference_markers = [
        "eu prefiro",
        "prefiro",
        "eu gosto",
        "gosto de",
        "não gosto",
        "nao gosto",
        "eu não quero",
        "eu nao quero",
        "não quero",
        "nao quero",
        "quero evitar",
        "não pretendo",
        "nao pretendo",
        "não tenho pretensão",
        "nao tenho pretensao",
        "meu padrão",
        "meu padrao",
    ]

    if any(marker in clean for marker in user_preference_markers):
        content = original

        if not clean.startswith("preferência do usuário") and not clean.startswith("preferencia do usuario"):
            content = f"Preferência do usuário: {original}"

        return {
            "owner_type": "user",
            "category": "user_preference",
            "content": content,
            "importance": 4,
            "source": "chat",
        }

    future_goal_markers = [
        "depois vamos",
        "mais tarde vamos",
        "futuramente",
        "no futuro",
        "quero implementar",
        "vamos implementar",
        "precisamos implementar",
        "seria bom implementar",
        "próximo passo",
        "proximo passo",
    ]

    if any(marker in clean for marker in future_goal_markers) and has_project_context:
        content = original

        if not clean.startswith("objetivo do projeto"):
            content = f"Objetivo do projeto: {original}"

        return {
            "owner_type": "project",
            "category": "project_goal",
            "content": content,
            "importance": 4,
            "source": "chat",
        }

    return None


def normalize_for_similarity(text: str) -> set[str]:
    clean = lower_text(text)

    replacements = {
        "regra do helix": "",
        "preferência do usuário": "",
        "preferencia do usuario": "",
        "decisão técnica": "",
        "decisao tecnica": "",
        "objetivo do projeto": "",
        "sempre": "",
        "antes de": "",
        "qualquer": "",
        "arquivos": "arquivo",
        "ações": "acao",
        "açoes": "acao",
        "perigosas": "perigoso",
        "confirmação": "confirmacao",
        "apagar": "delete",
        "apague": "delete",
        "deletar": "delete",
        "delete": "delete",
    }

    for old, new in replacements.items():
        clean = clean.replace(old, new)

    stop_words = {
        "o",
        "a",
        "os",
        "as",
        "um",
        "uma",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "para",
        "por",
        "com",
        "e",
        "ou",
        "que",
        "isso",
        "esse",
        "essa",
        "meu",
        "minha",
        "seu",
        "sua",
    }

    words = {
        word.strip(".,:;!?")
        for word in clean.split()
        if len(word.strip(".,:;!?")) >= 4
        and word.strip(".,:;!?") not in stop_words
    }

    return words


def similarity_score(text_a: str, text_b: str) -> float:
    words_a = normalize_for_similarity(text_a)
    words_b = normalize_for_similarity(text_b)

    if not words_a or not words_b:
        return 0.0

    intersection = words_a.intersection(words_b)
    union = words_a.union(words_b)

    return len(intersection) / len(union)


def memory_exists(db: Session, user_id: int, content: str) -> bool:
    clean_content = normalize_text(content).lower()

    existing = (
        db.query(Memory)
        .filter(
            or_(
                Memory.user_id == user_id,
                Memory.owner_type.in_(["project", "system"]),
            )
        )
        .all()
    )

    for memory in existing:
        existing_content = normalize_text(memory.content).lower()

        if existing_content == clean_content:
            print(f"Memória igual já existe: {memory.content}")
            return True

        score = similarity_score(existing_content, clean_content)

        if score >= 0.55:
            print(
                "Memória parecida já existe. "
                f"Score={score:.2f} | existente={memory.content} | nova={content}"
            )
            return True

    return False


def save_memory_if_relevant(db: Session, user_id: int, message: str) -> Memory | None:
    memory_data = classify_memory(message)

    if not memory_data:
        return None

    content = memory_data["content"]

    if memory_exists(db, user_id, content):
        return None

    try:
        memory = Memory(
            user_id=user_id if memory_data["owner_type"] == "user" else None,
            owner_type=memory_data["owner_type"],
            category=memory_data["category"],
            content=content,
            importance=memory_data["importance"],
            source=memory_data.get("source", "chat"),
        )

        db.add(memory)
        db.commit()
        db.refresh(memory)

        return memory

    except SQLAlchemyError as exc:
        print(f"Erro ao salvar memória: {exc}")
        db.rollback()
        return None


def load_relevant_memories(
    db: Session,
    user_id: int,
    limit: int = 8,
) -> list[str]:
    try:
        memories = (
            db.query(Memory)
            .filter(
                or_(
                    Memory.user_id == user_id,
                    Memory.owner_type.in_(["project", "system"]),
                )
            )
            .order_by(
                Memory.importance.desc(),
                Memory.created_at.desc(),
            )
            .limit(limit)
            .all()
        )

        now = datetime.utcnow()

        result = []

        for memory in memories:
            memory.last_used_at = now
            result.append(memory.content)

        db.commit()

        return result

    except SQLAlchemyError as exc:
        print(f"Erro ao carregar memórias relevantes: {exc}")
        db.rollback()
        return []


def update_memory(
    db: Session,
    memory_id: int,
    content: str | None = None,
    owner_type: str | None = None,
    category: str | None = None,
    importance: int | None = None,
    source: str | None = None,
) -> Memory | None:
    try:
        memory = db.query(Memory).filter(Memory.id == memory_id).first()

        if not memory:
            return None

        changed = False

        if content is not None:
            clean_content = content.strip()

            if clean_content:
                memory.content = clean_content
                changed = True

        if owner_type is not None:
            clean_owner_type = owner_type.strip().lower()

            if clean_owner_type in ["user", "project", "system"]:
                memory.owner_type = clean_owner_type
                memory.user_id = memory.user_id if clean_owner_type == "user" else None
                changed = True

        if category is not None:
            clean_category = category.strip().lower()

            if clean_category:
                memory.category = clean_category
                changed = True

        if importance is not None:
            if 1 <= importance <= 5:
                memory.importance = importance
                changed = True

        if source is not None:
            clean_source = source.strip().lower()

            if clean_source:
                memory.source = clean_source
                changed = True

        if changed:
            memory.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(memory)

        return memory

    except SQLAlchemyError as exc:
        print(f"Erro ao atualizar memória: {exc}")
        db.rollback()
        return None


def delete_memory(db: Session, memory_id: int) -> bool:
    try:
        memory = db.query(Memory).filter(Memory.id == memory_id).first()

        if not memory:
            return False

        db.delete(memory)
        db.commit()

        return True

    except SQLAlchemyError as exc:
        print(f"Erro ao deletar memória: {exc}")
        db.rollback()
        return False


def should_sync_to_obsidian(memory: Memory) -> bool:
    """
    Decide se uma memória deve ser sincronizada/salva no Obsidian.

    Regras:
    - Memórias importantes de sistema e projeto devem ir para o Obsidian.
    - Preferências importantes do usuário também podem ir.
    - Memórias fracas ou gerais não precisam ir.
    """
    if not memory:
        return False

    if memory.importance >= 5:
        return True

    if memory.owner_type in ["project", "system"]:
        return True

    if memory.category in [
        "technical_decision",
        "system_rule",
        "project_goal",
        "user_preference",
    ] and memory.importance >= 4:
        return True

    return False


def build_memory_markdown(memory: Memory) -> str:
    """
    Gera um Markdown simples para salvar uma memória no Obsidian.
    """
    created_at = memory.created_at.isoformat() if memory.created_at else "desconhecido"
    updated_at = memory.updated_at.isoformat() if getattr(memory, "updated_at", None) else "desconhecido"

    return f"""# Memória Helix #{memory.id}

## Conteúdo

{memory.content}

## Metadados

- ID: {memory.id}
- Tipo: {memory.owner_type}
- Categoria: {memory.category}
- Importância: {memory.importance}
- Fonte: {getattr(memory, "source", "chat")}
- Criado em: {created_at}
- Atualizado em: {updated_at}
"""