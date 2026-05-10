import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from backend.core.database import Memory
from backend.core.obsidian_service import save_memory_to_obsidian


MEMORY_KEYWORDS = [
    "vamos usar",
    "decidi",
    "decidimos",
    "ficou decidido",
    "quero que",
    "o helix deve",
    "o helix precisa",
    "prefiro",
    "não quero",
    "depois vamos",
    "mais tarde",
    "anote",
    "lembre",
    "salve",
]


STOP_WORDS = {
    "que", "o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das",
    "para", "como", "com", "no", "na", "nos", "nas", "foi", "ficou", "decidido",
    "vamos", "usar", "usaremos", "projeto"
}


def normalize_text(text: str) -> str:
    text = text.lower().strip()

    replacements = {
        "postgresql": "postgres",
        "banco de dados": "banco",
        "memória": "memoria",
        "principal": "central",
        "hilex": "helix",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z0-9áàâãéèêíóôõúç\s]", "", text)
    text = re.sub(r"\s+", " ", text)

    words = [
        word for word in text.split()
        if word not in STOP_WORDS and len(word) > 2
    ]

    return " ".join(words)


def refine_memory_content(text: str, category: str) -> str:
    clean_text = text.strip()
    lower_text = clean_text.lower()

    if category == "technical_decision":
        clean_text = re.sub(
            r"^(ficou decidido que|decidimos que|decidi que|vamos usar|usaremos|o helix usará|o helix vai usar)\s+",
            "",
            clean_text,
            flags=re.IGNORECASE,
        )

        if "postgres" in lower_text and "helix" in lower_text:
            return "O Helix usará PostgreSQL como memória principal do projeto."

        if "obsidian" in lower_text and ("cérebro" in lower_text or "cerebro" in lower_text):
            return "O Helix usará o Obsidian como cérebro organizado do projeto."

        if "frontend" in lower_text and "camadas" in lower_text:
            return "O frontend do Helix será reconstruído futuramente em camadas."

        if "backend" in lower_text:
            clean_text = clean_text.strip()

            if clean_text:
                clean_text = clean_text[0].upper() + clean_text[1:]

            return clean_text

        clean_text = clean_text.strip()

        if clean_text:
            clean_text = clean_text[0].upper() + clean_text[1:]

        return clean_text

    if category == "system_rule":
        clean_text = re.sub(
            r"^(quero que|o helix deve|o helix precisa)\s+",
            "",
            clean_text,
            flags=re.IGNORECASE,
        )

        clean_text = clean_text.strip()

        if clean_text:
            clean_text = clean_text[0].lower() + clean_text[1:]

        return f"Regra do Helix: {clean_text}"

    if category == "user_preference":
        clean_text = clean_text.strip()

        if clean_text:
            clean_text = clean_text[0].lower() + clean_text[1:]

        return f"Preferência do usuário: {clean_text}"

    if category == "project":
        clean_text = clean_text.strip()

        if clean_text:
            clean_text = clean_text[0].upper() + clean_text[1:]

        return f"Informação do projeto Helix: {clean_text}"

    return clean_text


def similarity(a: str, b: str) -> float:
    normalized_a = normalize_text(a)
    normalized_b = normalize_text(b)

    if not normalized_a or not normalized_b:
        return 0

    sequence_score = SequenceMatcher(None, normalized_a, normalized_b).ratio()

    words_a = set(normalized_a.split())
    words_b = set(normalized_b.split())

    intersection = len(words_a & words_b)
    union = len(words_a | words_b)

    word_score = intersection / union if union else 0

    return max(sequence_score, word_score)


def find_similar_memory(
    db: Session,
    content: str,
    threshold: float = 0.55,
) -> Memory | None:
    memories = db.query(Memory).all()

    for memory in memories:
        score = similarity(content, memory.content)

        if score >= threshold:
            return memory

    return None


def classify_memory(text: str) -> dict:
    clean_text = text.strip()
    lower_text = clean_text.lower()

    if not clean_text:
        return {
            "should_save": False,
            "category": "ignore",
            "owner_type": "temporary",
            "importance": 0,
            "content": "",
        }

    should_save = any(keyword in lower_text for keyword in MEMORY_KEYWORDS)

    if not should_save:
        return {
            "should_save": False,
            "category": "ignore",
            "owner_type": "temporary",
            "importance": 0,
            "content": clean_text,
        }

    category = "general"
    owner_type = "user"
    importance = 3

    if "helix" in lower_text:
        category = "project"
        owner_type = "project"
        importance = 5

    if "prefiro" in lower_text or "não quero" in lower_text:
        category = "user_preference"
        owner_type = "user"
        importance = 4

    if (
        "vamos usar" in lower_text
        or "decidi" in lower_text
        or "decidimos" in lower_text
        or "ficou decidido" in lower_text
    ):
        category = "technical_decision"
        owner_type = "project"
        importance = 5

    if "o helix deve" in lower_text or "o helix precisa" in lower_text:
        category = "system_rule"
        owner_type = "system"
        importance = 5

    refined_content = refine_memory_content(clean_text, category)

    return {
        "should_save": True,
        "category": category,
        "owner_type": owner_type,
        "importance": importance,
        "content": refined_content,
    }

def should_sync_to_obsidian(
        category: str,
        owner_type: str,
        importance: int,
) -> bool:
    if importance >= 5:
        return True
    
    if category in ["Technical_decision", "system_rule"]:
        return True
    
    if owner_type in ["project, system"] and importance >= 4:
        return True
    
    return False

def save_memory_if_relevant(
    db: Session,
    user_id: int,
    text: str,
) -> Memory | None:
    classification = classify_memory(text)

    if not classification["should_save"]:
        return None

    similar_memory = find_similar_memory(db, classification["content"])

    if similar_memory:
        if classification["importance"] > similar_memory.importance:
            similar_memory.importance = classification["importance"]

        db.commit()
        db.refresh(similar_memory)

        return similar_memory

    memory = Memory(
        user_id=user_id if classification["owner_type"] == "user" else None,
        owner_type=classification["owner_type"],
        category=classification["category"],
        content=classification["content"],
        importance=classification["importance"],
    )

    db.add(memory)
    db.commit()
    db.refresh(memory)

    if should_sync_to_obsidian(
        category=memory.category,
        owner_type=memory.owner_type,
        importance=memory.importance,
    ):
        try:
            save_memory_to_obsidian(
                content=memory.content,
                category=memory.category,
                owner_type=memory.owner_type,
                importance=memory.importance,
            )
        except Exception as exc:
            print(f"Erro ao salvar memória no Obsidian: {exc}")

    return memory


def load_relevant_memories(
    db: Session,
    user_id: int,
    limit: int = 8,
) -> list[str]:
    memories = (
        db.query(Memory)
        .filter(
            (Memory.user_id == user_id)
            | (Memory.owner_type.in_(["project", "system"]))
        )
        .order_by(Memory.importance.desc(), Memory.created_at.desc())
        .limit(limit)
        .all()
    )

    return [memory.content for memory in memories]