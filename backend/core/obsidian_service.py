from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher
import re


OBSIDIAN_VAULT_PATH = Path(r"C:\Users\Marcos\OneDrive\Documentos\Helix Vault")

HELIX_BRAIN_DIR = OBSIDIAN_VAULT_PATH / "Helix Brain"
HELIX_LOGS_DIR = OBSIDIAN_VAULT_PATH / "Helix Logs"

BRAIN_FOLDERS = [
    "Memorias",
    "Decisoes",
    "Regras",
    "Ideias",
    "Arquitetura",
    "Usuarios",
]

LOGS_FOLDERS = [
    "Conversas",
    "Comandos",
    "Erros",
    "Eventos",
]


def ensure_obsidian_structure() -> None:
    HELIX_BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    HELIX_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    for folder in BRAIN_FOLDERS:
        (HELIX_BRAIN_DIR / folder).mkdir(parents=True, exist_ok=True)

    for folder in LOGS_FOLDERS:
        (HELIX_LOGS_DIR / folder).mkdir(parents=True, exist_ok=True)


def sanitize_filename(title: str) -> str:
    title = title.strip()
    title = re.sub(r'[\\/:*?"<>|]', "", title)
    title = re.sub(r"\s+", " ", title)
    return title[:120]


def generate_note_title(content: str, category: str) -> str:
    text = content.strip()
    lower = text.lower()

    if category == "technical_decision":
        if ("postgres" in lower and "memória" in lower) or (
            "postgres" in lower and "memoria" in lower
        ):
            return "PostgreSQL como memória principal"

        if "obsidian" in lower and ("cérebro" in lower or "cerebro" in lower):
            return "Obsidian como cérebro organizado do Helix"

        if "frontend" in lower:
            return "Reconstrução do frontend do Helix"

        if "backend" in lower:
            return "Decisão sobre backend do Helix"

        clean = text
        clean = clean.replace("Decisão técnica:", "").strip()
        clean = clean.replace("O Helix usará", "").strip()
        clean = clean.replace("O Helix vai usar", "").strip()

        return sanitize_filename(clean[:80])

    if category == "system_rule":
        if "apagar" in lower and "arquivo" in lower:
            return "Confirmar antes de apagar arquivos"

        if "comando" in lower and (
            "confirmação" in lower or "confirmacao" in lower
        ):
            return "Confirmação para comandos sensíveis"

        clean = text
        clean = clean.replace("Regra do Helix:", "").strip()

        return sanitize_filename(clean[:80])

    if category == "user_preference":
        clean = text.replace("Preferência do usuário:", "").strip()
        return sanitize_filename(f"Preferência - {clean[:60]}")

    return sanitize_filename(text[:80])


def append_to_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as file:
        file.write(content)


def write_file_if_missing(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)


def build_yaml(
    note_type: str,
    category: str,
    importance: int,
    source: str = "helix",
    status: str = "active",
    related: list[str] | None = None,
) -> str:
    created = datetime.now().strftime("%Y-%m-%d")

    related = related or []

    yaml = [
        "---",
        f"type: {note_type}",
        f"category: {category}",
        f"importance: {importance}",
        f"status: {status}",
        f"source: {source}",
        f"created: {created}",
    ]

    if related:
        yaml.append("related:")
        for item in related:
            yaml.append(f'  - "[[{item}]]"')

    yaml.append("---")

    return "\n".join(yaml)


def build_related_section(related: list[str]) -> str:
    if not related:
        return ""

    links = "\n".join([f"- [[{item}]]" for item in related])

    return f"""
## Relacionado

{links}
"""


def create_or_update_note(
    folder: Path,
    title: str,
    content: str,
    note_type: str,
    category: str,
    importance: int,
    related: list[str] | None = None,
) -> Path:
    ensure_obsidian_structure()

    safe_title = sanitize_filename(title)
    note_path = folder / f"{safe_title}.md"

    related = related or []

    yaml = build_yaml(
        note_type=note_type,
        category=category,
        importance=importance,
        related=related,
    )

    related_section = build_related_section(related)

    note_content = f"""{yaml}

# {safe_title}

{content.strip()}

{related_section}
"""

    write_file_if_missing(note_path, note_content)

    return note_path


def append_index_link(
    index_path: Path,
    note_title: str,
    description: str,
) -> None:
    ensure_obsidian_structure()

    today = datetime.now().strftime("%Y-%m-%d")
    line = f"\n- {today} — [[{note_title}]] — {description.strip()}\n"

    if index_path.exists():
        current = index_path.read_text(encoding="utf-8")

        if f"[[{note_title}]]" in current:
            return

    append_to_file(index_path, line)


def save_decision_note(content: str, importance: int = 5) -> Path:
    title = generate_note_title(content, "technical_decision")

    related = [
        "Memória Principal",
        "Arquitetura do Helix",
        "Decisões Técnicas",
    ]

    note_path = create_or_update_note(
        folder=HELIX_BRAIN_DIR / "Decisoes",
        title=title,
        content=content,
        note_type="decision",
        category="technical_decision",
        importance=importance,
        related=related,
    )

    append_index_link(
        index_path=HELIX_BRAIN_DIR / "Decisões Técnicas.md",
        note_title=note_path.stem,
        description=content,
    )

    append_index_link(
        index_path=HELIX_BRAIN_DIR / "Memória Principal.md",
        note_title=note_path.stem,
        description=content,
    )

    return note_path


def save_system_rule_note(content: str, importance: int = 5) -> Path:
    title = generate_note_title(content, "system_rule")

    related = [
        "Regras do Sistema",
        "Memória Principal",
    ]

    note_path = create_or_update_note(
        folder=HELIX_BRAIN_DIR / "Regras",
        title=title,
        content=content,
        note_type="system_rule",
        category="safety",
        importance=importance,
        related=related,
    )

    append_index_link(
        index_path=HELIX_BRAIN_DIR / "Regras do Sistema.md",
        note_title=note_path.stem,
        description=content,
    )

    append_index_link(
        index_path=HELIX_BRAIN_DIR / "Memória Principal.md",
        note_title=note_path.stem,
        description=content,
    )

    return note_path


def save_memory_to_obsidian(
    content: str,
    category: str,
    owner_type: str,
    importance: int,
) -> Path | None:
    ensure_obsidian_structure()

    if category == "technical_decision":
        return save_decision_note(content, importance)

    if category == "system_rule":
        return save_system_rule_note(content, importance)

    title = sanitize_filename(content[:80])

    related = [
        "Memória Principal",
    ]

    note_path = create_or_update_note(
        folder=HELIX_BRAIN_DIR / "Memorias",
        title=title,
        content=content,
        note_type=owner_type,
        category=category,
        importance=importance,
        related=related,
    )

    append_index_link(
        index_path=HELIX_BRAIN_DIR / "Memória Principal.md",
        note_title=note_path.stem,
        description=content,
    )

    return note_path


def log_command_to_obsidian(
    user_message: str,
    action: str,
    target: str,
    result: str,
    user_name: str = "marcos",
) -> Path:
    ensure_obsidian_structure()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = HELIX_LOGS_DIR / "Comandos" / "Log de Comandos.md"

    if not log_path.exists():
        initial_content = """# Log de Comandos

Este arquivo registra comandos executados pelo Helix.

"""
        write_file_if_missing(log_path, initial_content)

    markdown = f"""
---

## Comando — {now}

- **Usuário:** {user_name}
- **Mensagem:** {user_message}
- **Ação:** {action}
- **Alvo:** {target}
- **Resultado:** {result}
"""

    append_to_file(log_path, markdown)

    return log_path


def log_error_to_obsidian(
    error: str,
    context: str = "backend",
    user_message: str | None = None,
    user_name: str = "marcos",
) -> Path:
    ensure_obsidian_structure()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = HELIX_LOGS_DIR / "Erros" / "Log de Erros.md"

    if not log_path.exists():
        initial_content = """# Log de Erros

Este arquivo registra erros capturados pelo Helix.

"""
        write_file_if_missing(log_path, initial_content)

    markdown = f"""
---

## Erro — {now}

- **Usuário:** {user_name}
- **Contexto:** {context}
"""

    if user_message:
        markdown += f"- **Mensagem do usuário:** {user_message}\n"

    markdown += f"""
- **Erro:** `{error}`
"""

    append_to_file(log_path, markdown)

    return log_path


def log_event_to_obsidian(
    event: str,
    context: str = "system",
    details: str | None = None,
    user_name: str = "marcos",
) -> Path:
    ensure_obsidian_structure()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = HELIX_LOGS_DIR / "Eventos" / "Log de Eventos.md"

    if not log_path.exists():
        initial_content = """# Log de Eventos

Este arquivo registra eventos normais do Helix.

"""
        write_file_if_missing(log_path, initial_content)

    markdown = f"""
---

## Evento — {now}

- **Usuário:** {user_name}
- **Contexto:** {context}
- **Evento:** {event}
"""

    if details:
        markdown += f"- **Detalhes:** {details}\n"

    append_to_file(log_path, markdown)

    return log_path


def log_conversation_to_obsidian(
    user_message: str,
    ai_response: str,
    user_name: str = "marcos",
) -> Path:
    ensure_obsidian_structure()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = HELIX_LOGS_DIR / "Conversas" / "Log de Conversas.md"

    if not log_path.exists():
        initial_content = """# Log de Conversas

Este arquivo registra interações importantes ou resumidas do Helix.

"""
        write_file_if_missing(log_path, initial_content)

    short_user_message = user_message.strip()
    short_ai_response = ai_response.strip()

    if len(short_user_message) > 500:
        short_user_message = short_user_message[:500] + "..."

    if len(short_ai_response) > 800:
        short_ai_response = short_ai_response[:800] + "..."

    markdown = f"""
---

## Conversa — {now}

- **Usuário:** {user_name}

### Mensagem
{short_user_message}

### Resposta do Helix
{short_ai_response}
"""

    append_to_file(log_path, markdown)

    return log_path


def read_text_file(path: Path, max_chars: int = 1200) -> str:
    try:
        text = path.read_text(encoding="utf-8")
        return text[:max_chars]
    except Exception:
        return ""


def calculate_note_score(note_path: Path, query: str, content: str) -> int:
    score = 0

    query_lower = query.lower()
    title_lower = note_path.stem.lower()
    path_lower = str(note_path).lower()
    content_lower = content.lower()

    if query_lower in title_lower:
        score += 100

    if "\\decisoes\\" in path_lower or "/decisoes/" in path_lower:
        score += 40

    if "\\regras\\" in path_lower or "/regras/" in path_lower:
        score += 35

    if "\\memorias\\" in path_lower or "/memorias/" in path_lower:
        score += 30

    if "\\arquitetura\\" in path_lower or "/arquitetura/" in path_lower:
        score += 25

    if "\\ideias\\" in path_lower or "/ideias/" in path_lower:
        score += 20

    index_titles = [
        "dashboard helix",
        "dasboard helix",
        "decisões técnicas",
        "decisoes tecnicas",
        "regras do sistema",
        "memória principal",
        "memoria principal",
        "status do projeto",
        "ideias futuras",
        "arquitetura do helix",
    ]

    if title_lower in index_titles:
        score -= 25

    if query_lower in content_lower:
        score += 10

    position = content_lower.find(query_lower)

    if position != -1:
        if position < 500:
            score += 10
        elif position < 1500:
            score += 5

    return score


def search_obsidian_notes(
    query: str,
    limit: int = 10,
    scope: str = "brain",
) -> list[dict]:
    ensure_obsidian_structure()

    clean_query = query.lower().strip()

    if not clean_query:
        return []

    if scope == "brain":
        search_root = HELIX_BRAIN_DIR
    elif scope == "logs":
        search_root = HELIX_LOGS_DIR
    else:
        search_root = OBSIDIAN_VAULT_PATH

    results = []

    for note_path in search_root.rglob("*.md"):
        try:
            content = note_path.read_text(encoding="utf-8")
        except Exception:
            continue

        title = note_path.stem
        content_lower = content.lower()
        title_lower = title.lower()

        if clean_query not in title_lower and clean_query not in content_lower:
            continue

        index = content_lower.find(clean_query)

        if index == -1:
            snippet = content[:300]
        else:
            start = max(index - 120, 0)
            end = min(index + 300, len(content))
            snippet = content[start:end]

        score = calculate_note_score(note_path, clean_query, content)

        results.append(
            {
                "title": title,
                "path": str(note_path.relative_to(OBSIDIAN_VAULT_PATH)),
                "scope": scope,
                "score": score,
                "snippet": snippet.strip(),
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)

    return results[:limit]


def read_obsidian_note_by_path(
    relative_path: str,
    max_chars: int = 3000,
) -> dict:
    ensure_obsidian_structure()

    note_path = OBSIDIAN_VAULT_PATH / relative_path

    if not note_path.exists():
        return {
            "found": False,
            "error": "Nota não encontrada.",
        }

    if note_path.suffix.lower() != ".md":
        return {
            "found": False,
            "error": "O arquivo não é uma nota Markdown.",
        }

    content = read_text_file(note_path, max_chars=max_chars)

    return {
        "found": True,
        "title": note_path.stem,
        "path": str(note_path.relative_to(OBSIDIAN_VAULT_PATH)),
        "content": content,
    }


def is_inside_managed_folder(note_path: Path) -> bool:
    try:
        relative = note_path.relative_to(OBSIDIAN_VAULT_PATH)
    except ValueError:
        return True

    parts = relative.parts

    if not parts:
        return True

    managed_roots = {
        "Helix Brain",
        "Helix Logs",
        "_Lixeira",
    }

    return parts[0] in managed_roots


def suggest_note_destination(title: str, content: str) -> dict:
    text = f"{title} {content}".lower()

    if any(
        term in text
        for term in [
            "autenticação",
            "autenticacao",
            "usuário",
            "usuario",
            "login",
            "multi-usuário",
            "multiusuario",
        ]
    ):
        return {
            "folder": "Helix Brain/Arquitetura",
            "category": "architecture",
            "reason": "Parece tratar de autenticação, usuários ou estrutura do sistema.",
        }

    if any(
        term in text
        for term in [
            "cache",
            "performance",
            "otimização",
            "otimizacao",
        ]
    ):
        return {
            "folder": "Helix Brain/Arquitetura",
            "category": "architecture",
            "reason": "Parece tratar de arquitetura, performance ou otimização.",
        }

    if any(
        term in text
        for term in [
            "frontend",
            "interface",
            "visual",
            "orb",
            "tela",
            "dashboard",
        ]
    ):
        return {
            "folder": "Helix Brain/Ideias",
            "category": "idea",
            "reason": "Parece ser uma ideia ou melhoria visual/frontend.",
        }

    if any(
        term in text
        for term in [
            "plugin",
            "extensão",
            "extensao",
            "módulo",
            "modulo",
        ]
    ):
        return {
            "folder": "Helix Brain/Arquitetura",
            "category": "architecture",
            "reason": "Parece tratar de módulos, plugins ou extensões do Helix.",
        }

    if any(
        term in text
        for term in [
            "memória",
            "memoria",
            "rag",
            "rede neural",
            "neurônio",
            "neuronio",
            "obsidian",
            "postgres",
        ]
    ):
        return {
            "folder": "Helix Brain/Memorias",
            "category": "memory",
            "reason": "Parece tratar de memória, RAG, Obsidian ou banco de dados.",
        }

    if any(
        term in text
        for term in [
            "regra",
            "segurança",
            "seguranca",
            "permissão",
            "permissao",
            "confirmar",
            "apagar",
        ]
    ):
        return {
            "folder": "Helix Brain/Regras",
            "category": "system_rule",
            "reason": "Parece conter regra de comportamento ou segurança.",
        }

    return {
        "folder": "Helix Brain/Ideias",
        "category": "idea",
        "reason": "Não foi possível classificar com alta precisão; sugerido como ideia geral.",
    }


def scan_loose_obsidian_notes(limit: int = 50) -> dict:
    ensure_obsidian_structure()

    loose_notes = []

    for note_path in OBSIDIAN_VAULT_PATH.glob("*.md"):
        if is_inside_managed_folder(note_path):
            continue

        content = read_text_file(note_path, max_chars=1200)
        suggestion = suggest_note_destination(note_path.stem, content)

        loose_notes.append(
            {
                "title": note_path.stem,
                "path": str(note_path.relative_to(OBSIDIAN_VAULT_PATH)),
                "suggested_folder": suggestion["folder"],
                "category": suggestion["category"],
                "reason": suggestion["reason"],
                "preview": content[:300].strip(),
            }
        )

        if len(loose_notes) >= limit:
            break

    return {
        "count": len(loose_notes),
        "notes": loose_notes,
    }


def move_obsidian_note(
    relative_path: str,
    destination_folder: str,
) -> dict:
    ensure_obsidian_structure()

    source_path = OBSIDIAN_VAULT_PATH / relative_path
    destination_dir = OBSIDIAN_VAULT_PATH / destination_folder

    if not source_path.exists():
        return {
            "moved": False,
            "error": "Nota de origem não encontrada.",
            "source": str(source_path),
        }

    if source_path.suffix.lower() != ".md":
        return {
            "moved": False,
            "error": "Só é permitido mover arquivos Markdown.",
            "source": str(source_path),
        }

    try:
        source_path.relative_to(OBSIDIAN_VAULT_PATH)
    except ValueError:
        return {
            "moved": False,
            "error": "Caminho fora do vault bloqueado por segurança.",
        }

    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_path = destination_dir / source_path.name

    if destination_path.exists():
        return {
            "moved": False,
            "error": "Já existe uma nota com esse nome no destino.",
            "source": str(source_path.relative_to(OBSIDIAN_VAULT_PATH)),
            "destination": str(destination_path.relative_to(OBSIDIAN_VAULT_PATH)),
        }

    source_path.rename(destination_path)

    return {
        "moved": True,
        "source": str(source_path.relative_to(OBSIDIAN_VAULT_PATH)),
        "destination": str(destination_path.relative_to(OBSIDIAN_VAULT_PATH)),
    }


def normalize_note_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"---.*?---", "", text, flags=re.DOTALL)
    text = re.sub(r"\[\[|\]\]", "", text)
    text = re.sub(r"#+", "", text)
    text = re.sub(r"[*_`>-]", " ", text)
    text = re.sub(r"[^a-z0-9áàâãéèêíóôõúç\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def calculate_text_similarity(a: str, b: str) -> float:
    normalized_a = normalize_note_text(a)
    normalized_b = normalize_note_text(b)

    if not normalized_a or not normalized_b:
        return 0.0

    sequence_score = SequenceMatcher(
        None,
        normalized_a,
        normalized_b,
    ).ratio()

    words_a = set(normalized_a.split())
    words_b = set(normalized_b.split())

    intersection = len(words_a & words_b)
    union = len(words_a | words_b)

    word_score = intersection / union if union else 0.0

    return max(sequence_score, word_score)


def calculate_title_similarity(a: str, b: str) -> float:
    normalized_a = normalize_note_text(a)
    normalized_b = normalize_note_text(b)

    if not normalized_a or not normalized_b:
        return 0.0

    return SequenceMatcher(None, normalized_a, normalized_b).ratio()


def find_possible_duplicate_notes(
    relative_path: str,
    threshold: float = 0.72,
    limit: int = 5,
) -> dict:
    ensure_obsidian_structure()

    source_path = OBSIDIAN_VAULT_PATH / relative_path

    if not source_path.exists():
        return {
            "found": False,
            "error": "Nota de origem não encontrada.",
            "source": relative_path,
        }

    if source_path.suffix.lower() != ".md":
        return {
            "found": False,
            "error": "O arquivo de origem não é Markdown.",
            "source": relative_path,
        }

    try:
        source_path.relative_to(OBSIDIAN_VAULT_PATH)
    except ValueError:
        return {
            "found": False,
            "error": "Caminho fora do vault bloqueado por segurança.",
            "source": relative_path,
        }

    source_content = read_text_file(source_path, max_chars=10000)
    source_title = source_path.stem

    candidates = []
    matches = []

    for candidate_path in HELIX_BRAIN_DIR.rglob("*.md"):
        if candidate_path == source_path:
            continue

        candidate_content = read_text_file(candidate_path, max_chars=10000)
        candidate_title = candidate_path.stem

        title_similarity = calculate_title_similarity(
            source_title,
            candidate_title,
        )

        content_similarity = calculate_text_similarity(
            source_content,
            candidate_content,
        )

        duplicate_score = max(
            title_similarity,
            content_similarity,
        )

        item = {
            "path": str(candidate_path.relative_to(OBSIDIAN_VAULT_PATH)),
            "title": candidate_title,
            "title_similarity": round(title_similarity, 4),
            "content_similarity": round(content_similarity, 4),
            "duplicate_score": round(duplicate_score, 4),
        }

        candidates.append(item)

        is_duplicate = (
            title_similarity >= 0.85
            or content_similarity >= threshold
        )

        if is_duplicate:
            matches.append(
                {
                    **item,
                    "recommendation": (
                        "Possível duplicata. Revise antes de mover para a lixeira."
                    ),
                }
            )

    candidates.sort(key=lambda item: item["duplicate_score"], reverse=True)
    matches.sort(key=lambda item: item["duplicate_score"], reverse=True)

    return {
        "found": True,
        "source": str(source_path.relative_to(OBSIDIAN_VAULT_PATH)),
        "threshold": threshold,
        "possible_duplicate": len(matches) > 0,
        "matches": matches[:limit],
        "closest_candidates": candidates[:limit],
    }


def move_note_to_trash(
    relative_path: str,
    reason: str = "Movido para lixeira pelo Helix.",
) -> dict:
    ensure_obsidian_structure()

    source_path = OBSIDIAN_VAULT_PATH / relative_path
    trash_dir = OBSIDIAN_VAULT_PATH / "_Lixeira"

    if not source_path.exists():
        return {
            "moved": False,
            "error": "Nota não encontrada.",
            "source": str(source_path),
        }

    if source_path.suffix.lower() != ".md":
        return {
            "moved": False,
            "error": "Só é permitido mover notas Markdown para a lixeira.",
            "source": str(source_path),
        }

    try:
        source_path.relative_to(OBSIDIAN_VAULT_PATH)
    except ValueError:
        return {
            "moved": False,
            "error": "Caminho fora do vault bloqueado por segurança.",
        }

    trash_dir.mkdir(parents=True, exist_ok=True)

    destination_path = trash_dir / source_path.name

    if destination_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination_path = trash_dir / f"{source_path.stem}-{timestamp}{source_path.suffix}"

    source_path.rename(destination_path)

    log_event_to_obsidian(
        event="Nota movida para a lixeira.",
        context="move_note_to_trash",
        details=(
            f"Origem: {relative_path} | "
            f"Destino: {destination_path.relative_to(OBSIDIAN_VAULT_PATH)} | "
            f"Motivo: {reason}"
        ),
    )

    return {
        "moved": True,
        "source": relative_path,
        "destination": str(destination_path.relative_to(OBSIDIAN_VAULT_PATH)),
        "reason": reason,
    }