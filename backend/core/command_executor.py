import json
import os
import re
import shutil
import subprocess
import time
import uuid
import webbrowser
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, quote_plus

from sqlalchemy.orm import Session

from backend.core.database import SessionLocal
from backend.services.app_resolver_service import resolve_app_target


OBSIDIAN_VAULT_PATH = Path(
    os.environ.get(
        "HELIX_OBSIDIAN_VAULT",
        r"C:\Users\Marcos\OneDrive\Documentos\Helix Vault",
    )
)
OBSIDIAN_VAULT_NAME = os.environ.get("HELIX_OBSIDIAN_VAULT_NAME", "Helix Vault")
OBSIDIAN_CONFIG_PATH = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"

# Fallback manual. A fonte principal para abrir apps agora é:
# 1. app_resolver_service.py usando o banco
# 2. data/known_apps.json, gerado pelo scanner
# 3. PROGRAMS manual para comandos especiais/sistema
PROGRAMS = {
    "notepad": {
        "path": "notepad.exe",
        "process": "notepad.exe",
    },
    "bloco de notas": {
        "path": "notepad.exe",
        "process": "notepad.exe",
    },
    "calculadora": {
        "path": "calc.exe",
        "process": "Calculator.exe",
    },
    "discord": {
        "path": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Discord", "Update.exe"),
        "args": ["--processStart", "Discord.exe"],
        "process": "Discord.exe",
    },
    "obsidian": {
        "path": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Obsidian", "Obsidian.exe"),
        "process": "Obsidian.exe",
    },
}

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://www.github.com",
}

AUTO_LINK_MAX_NOTES = 5
HUB_MAX_NOTES = 10
LIST_MAX_NOTES = 30
READ_MAX_CHARS = 2000
SEARCH_MAX_RESULTS = 8
AUTO_LINK_MIN_SHARED_KEYWORDS = 1
AUTO_LINK_STRONG_KEYWORDS = {
    "api",
    "bot",
    "discord",
    "fastapi",
    "ia",
    "ollama",
    "postgres",
    "postgresql",
    "python",
    "sqlalchemy",
}
AUTO_LINK_STOPWORDS = {
    "abrir", "agora", "ainda", "alguma", "algum", "anotar", "aqui",
    "assim", "cada", "chamada", "chamado", "como", "com", "conversa",
    "criado", "criar", "da", "das", "de", "dei", "deixa", "deixar",
    "dele", "dela", "disso", "do", "dos", "ele", "ela", "em", "essa",
    "esse", "esta", "este", "eu", "foi", "helix", "isso", "ja", "mais",
    "mas", "meu", "minha", "na", "nas", "no", "nos", "nota", "nova",
    "novo", "obsidian", "para", "pela", "pelo", "por", "que", "salvar",
    "sem", "sobre", "sua", "suo", "tem", "ter", "teste", "um", "uma",
    "vai", "voce",
}

KNOWN_APPS_CACHE_PATH = Path("data") / "known_apps.json"

KNOWN_APP_IGNORED_PATH_KEYWORDS = {
    "installer",
    "install",
    "uninstall",
    "updater",
    "update",
    "setup",
    "crash",
    "helper",
    "service",
    "broker",
    "elevation",
    "notification",
    "maintenance",
    "runtime",
}

LEADING_TARGET_WORDS = {
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "uns",
    "umas",
    "app",
    "aplicativo",
    "programa",
}


APP_PROTOCOL_FALLBACKS = {
    # Apps da Microsoft Store ou instalados por usuário podem não abrir bem pelo .exe.
    # O protocolo é o caminho mais seguro/estável quando disponível.
    "spotify": ["spotify:"],
}


def _app_protocols_for_query(name: str, app: dict | None = None) -> list[str]:
    lookup_values = {normalize_app_lookup(name)}

    if app:
        lookup_values.add(normalize_app_lookup(app.get("name", "")))
        lookup_values.add(normalize_app_lookup(app.get("normalized_name", "")))

        for alias in app.get("aliases", []) or []:
            lookup_values.add(normalize_app_lookup(alias))

        process_name = app.get("process_name") or ""
        lookup_values.add(normalize_app_lookup(Path(process_name).stem))

    protocols: list[str] = []

    for key, values in APP_PROTOCOL_FALLBACKS.items():
        if any(key == value or key in value for value in lookup_values if value):
            protocols.extend(values)

    return protocols


def _open_via_cmd_start(path_or_uri: str) -> bool:
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", path_or_uri],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        return True
    except Exception:
        return False


def _try_open_protocols(protocols: list[str]) -> bool:
    for protocol in protocols:
        try:
            os.startfile(protocol)
            return True
        except Exception:
            if _open_via_cmd_start(protocol):
                return True

    return False


# -----------------------------------------------------------------------------
# Utilidades gerais
# -----------------------------------------------------------------------------

def _sanitize_filename(filename: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*]', "", filename).strip()
    filename = re.sub(r"\s+", " ", filename)
    return filename[:80] or "Nota Helix"


def _normalize_note_name(note_name: str) -> str:
    note_name = note_name.strip().removesuffix(".md").strip()
    return _sanitize_filename(note_name).lower()


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 2

    while True:
        candidate = path.with_name(f"{path.stem} {counter}{path.suffix}")

        if not candidate.exists():
            return candidate

        counter += 1


def _normalize_url(target: str) -> str | None:
    target = target.strip()

    if not target:
        return None

    if target.startswith(("http://", "https://")):
        return target

    if target.startswith("www.") or "." in target:
        return f"https://{target}"

    return None


# -----------------------------------------------------------------------------
# Obsidian
# -----------------------------------------------------------------------------

def _find_obsidian_note(note_name: str) -> Path | None:
    OBSIDIAN_VAULT_PATH.mkdir(parents=True, exist_ok=True)
    normalized_name = _normalize_note_name(note_name)
    candidates = []

    for note_path in OBSIDIAN_VAULT_PATH.rglob("*.md"):
        if "_Lixeira" in note_path.relative_to(OBSIDIAN_VAULT_PATH).parts:
            continue

        normalized_stem = _normalize_note_name(note_path.stem)

        if normalized_stem == normalized_name:
            return note_path

        if normalized_name in normalized_stem:
            candidates.append(note_path)

    if len(candidates) == 1:
        return candidates[0]

    return None


def _find_trashed_obsidian_note(note_name: str) -> Path | None:
    trash_dir = OBSIDIAN_VAULT_PATH / "_Lixeira"

    if not trash_dir.exists():
        return None

    normalized_name = _normalize_note_name(note_name)
    candidates = []

    for note_path in trash_dir.rglob("*.md"):
        normalized_stem = _normalize_note_name(note_path.stem)

        if normalized_stem == normalized_name:
            return note_path

        if normalized_name in normalized_stem:
            candidates.append(note_path)

    if len(candidates) == 1:
        return candidates[0]

    return None


def _extract_keywords(text: str) -> set[str]:
    words = set(re.findall(r"[a-zA-Z0-9_]{3,}", text.lower()))
    keywords = {
        word
        for word in words
        if word not in AUTO_LINK_STOPWORDS
        and (len(word) >= 5 or word in AUTO_LINK_STRONG_KEYWORDS)
    }
    return keywords | (words & AUTO_LINK_STRONG_KEYWORDS)


def _note_keywords(note_path: Path) -> set[str]:
    try:
        content = note_path.read_text(encoding="utf-8")
    except OSError:
        content = ""

    return _extract_keywords(f"{note_path.stem}\n{content}")


def _list_obsidian_notes(exclude: Path | None = None) -> list[Path]:
    OBSIDIAN_VAULT_PATH.mkdir(parents=True, exist_ok=True)
    notes = []

    for note_path in OBSIDIAN_VAULT_PATH.rglob("*.md"):
        if exclude and note_path == exclude:
            continue

        if "_Lixeira" in note_path.relative_to(OBSIDIAN_VAULT_PATH).parts:
            continue

        notes.append(note_path)

    return sorted(notes, key=lambda path: path.stat().st_mtime, reverse=True)


def _append_obsidian_link(note_path: Path, linked_note_name: str) -> bool:
    content = note_path.read_text(encoding="utf-8")
    link = f"[[{linked_note_name}]]"

    if link in content:
        return False

    if "## Links" not in content:
        content = content.rstrip() + "\n\n## Links\n"

    content = content.rstrip() + f"\n- {link}\n"
    note_path.write_text(content, encoding="utf-8")

    return True


def _auto_link_obsidian_note(note_path: Path) -> int:
    new_note_keywords = _note_keywords(note_path)

    if not new_note_keywords:
        return 0

    matches = []

    for candidate_path in OBSIDIAN_VAULT_PATH.rglob("*.md"):
        if candidate_path == note_path:
            continue

        if "_Lixeira" in candidate_path.relative_to(OBSIDIAN_VAULT_PATH).parts:
            continue

        shared_keywords = new_note_keywords & _note_keywords(candidate_path)
        strong_shared = shared_keywords & AUTO_LINK_STRONG_KEYWORDS

        if len(shared_keywords) >= AUTO_LINK_MIN_SHARED_KEYWORDS and strong_shared:
            matches.append((len(strong_shared), len(shared_keywords), candidate_path))

    matches.sort(reverse=True, key=lambda item: (item[0], item[1], item[2].stat().st_mtime))
    linked_count = 0

    for _, _, candidate_path in matches[:AUTO_LINK_MAX_NOTES]:
        source_changed = _append_obsidian_link(note_path, candidate_path.stem)
        destination_changed = _append_obsidian_link(candidate_path, note_path.stem)

        if source_changed or destination_changed:
            linked_count += 1

    return linked_count


def _ensure_obsidian_vault_registered() -> None:
    OBSIDIAN_VAULT_PATH.mkdir(parents=True, exist_ok=True)
    (OBSIDIAN_VAULT_PATH / ".obsidian").mkdir(exist_ok=True)

    if not OBSIDIAN_CONFIG_PATH.parent.exists():
        return

    config = {"vaults": {}}

    if OBSIDIAN_CONFIG_PATH.exists():
        try:
            config = json.loads(OBSIDIAN_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config = {"vaults": {}}

    vaults = config.setdefault("vaults", {})
    vault_path = str(OBSIDIAN_VAULT_PATH)

    for vault in vaults.values():
        if vault.get("path", "").lower() == vault_path.lower():
            return

    vaults[uuid.uuid4().hex[:16]] = {
        "path": vault_path,
        "ts": int(time.time() * 1000),
        "open": True,
    }

    try:
        OBSIDIAN_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def _open_obsidian_vault() -> None:
    _ensure_obsidian_vault_registered()
    webbrowser.open(f"obsidian://open?vault={quote(OBSIDIAN_VAULT_NAME, safe='')}")


def _open_obsidian_file(note_path: Path) -> None:
    _ensure_obsidian_vault_registered()
    relative_file = note_path.relative_to(OBSIDIAN_VAULT_PATH).with_suffix("").as_posix()

    webbrowser.open(
        f"obsidian://open?vault={quote(OBSIDIAN_VAULT_NAME, safe='')}&file={quote(relative_file, safe='')}"
    )


def _parse_obsidian_note(target: str) -> tuple[str, str]:
    target = target.strip().lstrip(":").strip()
    now = datetime.now()

    if ":" in target:
        title, content = target.split(":", 1)
        title = title.replace("chamada", "").replace("chamado", "").strip()
        content = content.strip()
    else:
        title = target
        content = target

    title = _sanitize_filename(title or f"Nota Helix {now:%Y-%m-%d %H-%M}")
    content = content or title

    markdown = (
        f"# {title}\n\n"
        f"Criado pelo Helix em {now:%Y-%m-%d %H:%M}.\n\n"
        f"{content}\n"
    )

    return title, markdown


def create_obsidian_markdown_note(title: str, markdown: str) -> Path:
    title = _sanitize_filename(title)
    OBSIDIAN_VAULT_PATH.mkdir(parents=True, exist_ok=True)

    note_path = OBSIDIAN_VAULT_PATH / f"{title}.md"
    counter = 2

    while note_path.exists():
        note_path = OBSIDIAN_VAULT_PATH / f"{title} {counter}.md"
        counter += 1

    note_path.write_text(markdown, encoding="utf-8")
    _auto_link_obsidian_note(note_path)

    return note_path


def open_obsidian_note(note_path: Path) -> None:
    _open_obsidian_file(note_path)


def _create_obsidian_note(target: str) -> str:
    title, markdown = _parse_obsidian_note(target)
    note_path = create_obsidian_markdown_note(title, markdown)
    _open_obsidian_file(note_path)

    return f"Nota criada no Obsidian: {note_path.name}"


def _remove_obsidian_links_to_note(deleted_note_name: str, deleted_note_path: Path) -> int:
    updated_count = 0
    plain_link = f"[[{deleted_note_name}]]"
    alias_link_pattern = re.compile(rf"\[\[{re.escape(deleted_note_name)}\|([^\]]+)\]\]")
    list_link_line_pattern = re.compile(
        rf"^\s*[-*]\s*\[\[{re.escape(deleted_note_name)}(?:\|[^\]]+)?\]\]\s*$",
        re.MULTILINE,
    )

    for note_path in _list_obsidian_notes(exclude=deleted_note_path):
        try:
            content = note_path.read_text(encoding="utf-8")
        except OSError:
            continue

        updated_content = list_link_line_pattern.sub("", content)
        updated_content = updated_content.replace(plain_link, deleted_note_name)
        updated_content = alias_link_pattern.sub(r"\1", updated_content)
        updated_content = re.sub(r"\n{3,}", "\n\n", updated_content).strip() + "\n"

        if updated_content != content:
            note_path.write_text(updated_content, encoding="utf-8")
            updated_count += 1

    return updated_count


def _delete_obsidian_note(note_name: str) -> str:
    note_path = _find_obsidian_note(note_name)

    if not note_path:
        return f"Nao encontrei a nota '{note_name}' no Helix Vault."

    removed_links_count = _remove_obsidian_links_to_note(note_path.stem, note_path)
    trash_dir = OBSIDIAN_VAULT_PATH / "_Lixeira"
    trash_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_path(trash_dir / note_path.name)
    note_path.rename(destination)

    return f"Nota movida para _Lixeira: {destination.name}. Links removidos em {removed_links_count} nota(s)."


def _format_obsidian_notes_list() -> str:
    notes = _list_obsidian_notes()[:LIST_MAX_NOTES]

    if not notes:
        return "Nao encontrei notas no Helix Vault."

    note_names = "\n".join(f"- {note.stem}" for note in notes)
    total = len(_list_obsidian_notes())
    suffix = "" if total <= LIST_MAX_NOTES else f"\n...e mais {total - LIST_MAX_NOTES} nota(s)."

    return f"Notas no Helix Vault:\n{note_names}{suffix}"


def _open_specific_obsidian_note(note_name: str) -> str:
    note_path = _find_obsidian_note(note_name)

    if not note_path:
        return f"Nao encontrei a nota '{note_name}' no Helix Vault."

    open_obsidian_note(note_path)

    return f"Abrindo nota: {note_path.stem}"


def _read_obsidian_note(note_name: str) -> str:
    note_path = _find_obsidian_note(note_name)

    if not note_path:
        return f"Nao encontrei a nota '{note_name}' no Helix Vault."

    content = note_path.read_text(encoding="utf-8")

    if len(content) > READ_MAX_CHARS:
        content = content[:READ_MAX_CHARS].rstrip() + "\n\n...conteudo cortado."

    return f"Conteudo de {note_path.name}:\n\n{content}"


def _search_obsidian_notes(query: str) -> str:
    query = query.strip()

    if not query:
        return "Diga o que voce quer buscar nas notas."

    query_lower = query.lower()
    results = []

    for note_path in _list_obsidian_notes():
        try:
            content = note_path.read_text(encoding="utf-8")
        except OSError:
            continue

        haystack = f"{note_path.stem}\n{content}".lower()

        if query_lower not in haystack:
            continue

        lines = content.splitlines()
        snippet = ""

        for line in lines:
            if query_lower in line.lower():
                snippet = line.strip()
                break

        results.append((note_path.stem, snippet[:160]))

        if len(results) >= SEARCH_MAX_RESULTS:
            break

    if not results:
        return f"Nao encontrei '{query}' nas notas do Helix Vault."

    formatted_results = "\n".join(
        f"- {name}" + (f": {snippet}" if snippet else "")
        for name, snippet in results
    )

    return f"Resultados para '{query}':\n{formatted_results}"


def _append_to_obsidian_note(target: str) -> str:
    if "|" not in target:
        return "Use assim: adicionar em nome da nota: texto para adicionar."

    note_name, content = [part.strip() for part in target.split("|", 1)]
    note_path = _find_obsidian_note(note_name)

    if not note_path:
        return f"Nao encontrei a nota '{note_name}' no Helix Vault."

    now = datetime.now()
    current_content = note_path.read_text(encoding="utf-8")
    addition = f"\n\n## Adicionado em {now:%Y-%m-%d %H:%M}\n{content}\n"
    note_path.write_text(current_content.rstrip() + addition, encoding="utf-8")
    _auto_link_obsidian_note(note_path)
    open_obsidian_note(note_path)

    return f"Conteudo adicionado em: {note_path.name}"


def _restore_obsidian_note(note_name: str) -> str:
    note_path = _find_trashed_obsidian_note(note_name)

    if not note_path:
        return f"Nao encontrei a nota '{note_name}' na _Lixeira."

    destination = _unique_path(OBSIDIAN_VAULT_PATH / note_path.name)
    note_path.rename(destination)
    _auto_link_obsidian_note(destination)
    open_obsidian_note(destination)

    return f"Nota restaurada: {destination.name}"


def _link_obsidian_notes(target: str) -> str:
    if "|" not in target:
        return "Diga as duas notas usando: ligar nota A com B."

    source_name, destination_name = [part.strip() for part in target.split("|", 1)]
    source_path = _find_obsidian_note(source_name)
    destination_path = _find_obsidian_note(destination_name)

    if not source_path:
        return f"Nao encontrei a nota '{source_name}' no Helix Vault."

    if not destination_path:
        return f"Nao encontrei a nota '{destination_name}' no Helix Vault."

    source_changed = _append_obsidian_link(source_path, destination_path.stem)
    destination_changed = _append_obsidian_link(destination_path, source_path.stem)
    open_obsidian_note(source_path)

    if not source_changed and not destination_changed:
        return f"As notas '{source_path.stem}' e '{destination_path.stem}' ja estavam ligadas."

    return f"Notas ligadas: {source_path.stem} <-> {destination_path.stem}"


def _update_obsidian_links_after_rename(old_name: str, new_name: str, renamed_path: Path) -> int:
    updated_count = 0

    for note_path in _list_obsidian_notes(exclude=renamed_path):
        try:
            content = note_path.read_text(encoding="utf-8")
        except OSError:
            continue

        updated_content = content.replace(f"[[{old_name}]]", f"[[{new_name}]]")
        updated_content = updated_content.replace(f"[[{old_name}|", f"[[{new_name}|")

        if updated_content != content:
            note_path.write_text(updated_content, encoding="utf-8")
            updated_count += 1

    return updated_count


def _rename_obsidian_note(target: str) -> str:
    if "|" not in target:
        return "Diga o nome antigo e o novo usando: renomear nota antiga para nova."

    old_name, new_name = [part.strip() for part in target.split("|", 1)]
    note_path = _find_obsidian_note(old_name)

    if not note_path:
        return f"Nao encontrei a nota '{old_name}' no Helix Vault."

    sanitized_new_name = _sanitize_filename(new_name)
    new_path = _unique_path(note_path.with_name(f"{sanitized_new_name}.md"))
    old_stem = note_path.stem

    note_path.rename(new_path)
    updated_count = _update_obsidian_links_after_rename(old_stem, new_path.stem, new_path)
    open_obsidian_note(new_path)

    return f"Nota renomeada para {new_path.name}. Links atualizados em {updated_count} nota(s)."


def _create_obsidian_hub(target: str) -> str:
    title = _sanitize_filename(target)
    now = datetime.now()
    note_path = _unique_path(OBSIDIAN_VAULT_PATH / f"{title}.md")
    related_notes = _list_obsidian_notes(exclude=note_path)[:HUB_MAX_NOTES]

    markdown = (
        f"# {title}\n\n"
        f"Criado pelo Helix em {now:%Y-%m-%d %H:%M}.\n\n"
        "## Notas relacionadas\n"
    )

    if related_notes:
        markdown += "\n".join(f"- [[{note.stem}]]" for note in related_notes) + "\n"
    else:
        markdown += "- Nenhuma nota encontrada ainda.\n"

    OBSIDIAN_VAULT_PATH.mkdir(parents=True, exist_ok=True)
    note_path.write_text(markdown, encoding="utf-8")

    linked_count = 0

    for related_note in related_notes:
        if _append_obsidian_link(related_note, note_path.stem):
            linked_count += 1

    open_obsidian_note(note_path)

    return f"Hub criado no Obsidian: {note_path.name} ({linked_count} notas ligadas)"


# -----------------------------------------------------------------------------
# Registro/cache de aplicativos descobertos pelo scanner
# -----------------------------------------------------------------------------

def normalize_app_lookup(value: str) -> str:
    if not value:
        return ""

    value = value.lower().strip()
    value = value.replace(".exe", "")
    value = value.replace(".lnk", "")
    value = value.replace("-", " ")
    value = value.replace("_", " ")
    value = re.sub(r"[^a-z0-9áàâãéèêíïóôõöúçñ\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    words = value.split()

    while words and words[0] in LEADING_TARGET_WORDS:
        words.pop(0)

    return " ".join(words).strip()


def load_known_apps_cache() -> list[dict]:
    if not KNOWN_APPS_CACHE_PATH.exists():
        return []

    try:
        payload = json.loads(KNOWN_APPS_CACHE_PATH.read_text(encoding="utf-8"))

        if isinstance(payload, list):
            return payload

        return []
    except Exception as exc:
        print(f"Erro ao carregar known_apps.json: {exc}")
        return []


def _is_bad_known_app_path(exe_path: str | None) -> bool:
    if not exe_path:
        return True

    text = exe_path.lower()
    name = Path(exe_path).stem.lower()

    if any(keyword in name for keyword in KNOWN_APP_IGNORED_PATH_KEYWORDS):
        return True

    if any(part in text for part in ["\\temp\\", "/temp/", "\\cache\\", "/cache/"]):
        return True

    return False


def find_known_app_in_cache(name: str) -> dict | None:
    query = normalize_app_lookup(name)

    if not query:
        return None

    apps = load_known_apps_cache()

    best_app = None
    best_score = 0

    for app in apps:
        if not app.get("is_active", True):
            continue

        exe_path = app.get("exe_path")

        if _is_bad_known_app_path(exe_path):
            continue

        candidates = set()
        candidates.add(normalize_app_lookup(app.get("name", "")))
        candidates.add(normalize_app_lookup(app.get("normalized_name", "")))

        for alias in app.get("aliases", []) or []:
            candidates.add(normalize_app_lookup(alias))

        score = 0

        for candidate in candidates:
            if not candidate:
                continue

            if query == candidate:
                score = max(score, 100)
            elif query in candidate:
                score = max(score, 85)
            elif candidate in query:
                score = max(score, 75)
            else:
                similarity = SequenceMatcher(None, query, candidate).ratio()

                if similarity >= 0.82:
                    score = max(score, int(similarity * 100))

        # Preferimos atalhos do Menu Iniciar para abrir apps de usuário.
        # Eles lidam melhor com apps Store/protocolos do que tentar executar o .exe protegido.
        source = (app.get("source") or "").lower()
        path_suffix = Path(exe_path).suffix.lower() if exe_path else ""

        if source == "start_menu":
            score += 10

        if path_suffix == ".lnk":
            score += 8

        if app.get("process_name"):
            score += 3

        if score > best_score:
            best_score = score
            best_app = app

    if best_score < 75:
        return None

    return best_app


# -----------------------------------------------------------------------------
# Resolver inteligente de apps usando banco
# -----------------------------------------------------------------------------

def _known_app_model_to_dict(app) -> dict:
    return {
        "name": getattr(app, "name", None),
        "normalized_name": getattr(app, "normalized_name", None),
        "aliases": getattr(app, "aliases", None),
        "exe_path": getattr(app, "exe_path", None),
        "process_name": getattr(app, "process_name", None),
        "source": getattr(app, "source", None),
        "confidence": getattr(app, "confidence", None),
        "is_active": getattr(app, "is_active", True),
    }


def open_resolved_app_from_db(name: str) -> str | None:
    db: Session | None = None

    try:
        db = SessionLocal()
        resolved = resolve_app_target(name, db)

        if not resolved.found or not resolved.app:
            return None

        app = resolved.app

        if resolved.requires_confirmation:
            return (
                f"Encontrei {app.name}, mas esse app precisa de confirmação antes de abrir. "
                f"Motivo: confiança baixa, fonte sensível ou possível ambiguidade."
            )

        app_dict = _known_app_model_to_dict(app)
        exe_path = app.exe_path
        protocols = _app_protocols_for_query(name, app_dict)

        # Protocolos primeiro para apps conhecidos que podem vir da Microsoft Store.
        if protocols and _try_open_protocols(protocols):
            return f"Abrindo {app.name} pelo protocolo do sistema..."

        if not exe_path:
            return f"Encontrei {app.name}, mas ele não tem caminho salvo para abrir."

        path = Path(exe_path)

        if not path.exists():
            if protocols and _try_open_protocols(protocols):
                return f"Abrindo {app.name} pelo protocolo do sistema..."

            return f"Encontrei {app.name}, mas o caminho salvo não existe mais: {exe_path}"

        errors = []

        # Atalho do Menu Iniciar: abrir com shell do Windows.
        if path.suffix.lower() == ".lnk":
            try:
                os.startfile(str(path))
                return f"Abrindo {app.name}..."
            except Exception as exc:
                errors.append(str(exc))

                if _open_via_cmd_start(str(path)):
                    return f"Abrindo {app.name}..."

        # Executável normal.
        try:
            subprocess.Popen([str(path)], shell=False)
            return f"Abrindo {app.name}..."
        except Exception as exc:
            errors.append(str(exc))

        # Fallback shell do Windows.
        try:
            os.startfile(str(path))
            return f"Abrindo {app.name}..."
        except Exception as exc:
            errors.append(str(exc))

        if _open_via_cmd_start(str(path)):
            return f"Abrindo {app.name}..."

        if protocols and _try_open_protocols(protocols):
            return f"Abrindo {app.name} pelo protocolo do sistema..."

        reason = errors[0] if errors else "erro desconhecido"

        return f"Encontrei {app.name}, mas falhei ao abrir: {reason}"

    except Exception as exc:
        print(f"Erro no resolver de apps: {exc}")
        return None

    finally:
        if db:
            db.close()


def close_resolved_app_from_db(name: str) -> str | None:
    db: Session | None = None

    try:
        db = SessionLocal()
        resolved = resolve_app_target(name, db)

        if not resolved.found or not resolved.app:
            return None

        app = resolved.app
        process_name = app.process_name

        if not process_name:
            exe_path = app.exe_path

            if exe_path and Path(exe_path).suffix.lower() == ".exe":
                process_name = Path(exe_path).name

        if not process_name:
            return f"Encontrei {app.name}, mas não sei o processo para fechar com segurança."

        subprocess.call(["taskkill", "/IM", process_name, "/F"])

        return f"Fechando {app.name}..."

    except Exception as exc:
        print(f"Erro ao fechar app pelo resolver: {exc}")
        return None

    finally:
        if db:
            db.close()


def open_known_app_from_cache(name: str) -> str | None:
    app = find_known_app_in_cache(name)

    if not app:
        return None

    exe_path = app.get("exe_path")
    protocols = _app_protocols_for_query(name, app)

    # Protocolos primeiro para apps conhecidos que podem vir da Microsoft Store.
    # Exemplo: Spotify às vezes dá WinError 5 ao tentar abrir o executável direto.
    if protocols and _try_open_protocols(protocols):
        return f"Abrindo {app.get('name')} pelo protocolo do sistema..."

    if not exe_path:
        return None

    path = Path(exe_path)

    if not path.exists():
        # Mesmo sem caminho válido, ainda podemos tentar protocolo.
        if protocols and _try_open_protocols(protocols):
            return f"Abrindo {app.get('name')} pelo protocolo do sistema..."

        return f"Encontrei {app.get('name')}, mas o caminho salvo não existe mais: {exe_path}"

    errors = []

    # Atalho do Menu Iniciar: abrir com shell do Windows, não com Popen.
    if path.suffix.lower() == ".lnk":
        try:
            os.startfile(str(path))
            return f"Abrindo {app.get('name')} pelo atalho do Menu Iniciar..."
        except Exception as exc:
            errors.append(str(exc))

            if _open_via_cmd_start(str(path)):
                return f"Abrindo {app.get('name')} pelo atalho do Menu Iniciar..."

    # Executável normal.
    try:
        subprocess.Popen([str(path)], shell=False)
        return f"Abrindo {app.get('name')} pelo registro do Helix..."
    except Exception as exc:
        errors.append(str(exc))

    # Fallback shell do Windows.
    try:
        os.startfile(str(path))
        return f"Abrindo {app.get('name')} pelo registro do Helix..."
    except Exception as exc:
        errors.append(str(exc))

    if _open_via_cmd_start(str(path)):
        return f"Abrindo {app.get('name')} pelo registro do Helix..."

    # Última tentativa: protocolo, caso não tenha sido usado antes por algum motivo.
    if protocols and _try_open_protocols(protocols):
        return f"Abrindo {app.get('name')} pelo protocolo do sistema..."

    reason = errors[0] if errors else "erro desconhecido"

    return f"Encontrei {app.get('name')}, mas falhei ao abrir: {reason}"


def close_known_app_from_cache(name: str) -> str | None:
    app = find_known_app_in_cache(name)

    if not app:
        return None

    process_name = app.get("process_name")

    if not process_name:
        exe_path = app.get("exe_path")

        if exe_path and Path(exe_path).suffix.lower() == ".exe":
            process_name = Path(exe_path).name

    if not process_name:
        return f"Encontrei {app.get('name')}, mas não sei o nome do processo para fechar com segurança."

    subprocess.call(["taskkill", "/IM", process_name, "/F"])

    return f"Fechando {app.get('name')} pelo registro do Helix..."


# -----------------------------------------------------------------------------
# Fallback manual de programas
# -----------------------------------------------------------------------------

def _resolve_program_path(program: dict) -> str | None:
    path = program.get("path")

    if path and Path(path).exists():
        return path

    fallback_command = program.get("fallback_command")

    if fallback_command:
        command_path = shutil.which(fallback_command)

        if command_path:
            return command_path

    if path:
        return path

    return None


def _open_program(program_name: str, program: dict) -> str:
    program_path = _resolve_program_path(program)

    if not program_path:
        return f"Não encontrei o caminho do programa: {program_name}."

    args = program.get("args")

    try:
        if args:
            subprocess.Popen([program_path, *args])
        else:
            subprocess.Popen([program_path])

        return f"Abrindo {program_name}..."

    except Exception as exc:
        try:
            os.startfile(program_path)
            return f"Abrindo {program_name}..."
        except Exception:
            return f"Tentei abrir {program_name}, mas falhou: {exc}"


# -----------------------------------------------------------------------------
# Executor principal
# -----------------------------------------------------------------------------

def execute_command(action: str, target: str):
    action = (action or "").lower().strip()
    original_target = (target or "").strip()
    target = original_target
    target_lower = target.lower()

    # Para comandos de app, remove artigos e palavras de apoio:
    # "abre o spotify" -> "spotify"; "fecha a steam" -> "steam".
    clean_target = normalize_app_lookup(target) or target_lower

    if not action or not target:
        return None

    if action == "open_url":
        url = _normalize_url(target)

        if not url:
            return f"URL inválida: {target}"

        webbrowser.open(url)

        return f"Abrindo URL: {url}"

    if action == "search":
        url = f"https://www.google.com/search?q={quote_plus(target)}"
        webbrowser.open(url)

        return f"Pesquisando por '{target}'..."

    if action == "obsidian_note":
        return _create_obsidian_note(target)

    if action == "obsidian_delete":
        return _delete_obsidian_note(target)

    if action == "obsidian_list":
        return _format_obsidian_notes_list()

    if action == "obsidian_open_note":
        return _open_specific_obsidian_note(target)

    if action == "obsidian_read":
        return _read_obsidian_note(target)

    if action == "obsidian_search":
        return _search_obsidian_notes(target)

    if action == "obsidian_append":
        return _append_to_obsidian_note(target)

    if action == "obsidian_restore":
        return _restore_obsidian_note(target)

    if action == "obsidian_link":
        return _link_obsidian_notes(target)

    if action == "obsidian_hub":
        return _create_obsidian_hub(target)

    if action == "obsidian_rename":
        return _rename_obsidian_note(target)

    if action == "open":
        if "obsidian" in target_lower:
            _open_obsidian_vault()
            return "Abrindo Obsidian..."

        for site_name, url in SITES.items():
            if site_name in clean_target or site_name in target_lower:
                webbrowser.open(url)
                return f"Abrindo {site_name}..."

        url = _normalize_url(target)

        if url:
            webbrowser.open(url)
            return f"Abrindo {url}..."

        # Fonte principal: resolver inteligente usando banco.
        resolved_app_result = open_resolved_app_from_db(clean_target)

        if resolved_app_result:
            return resolved_app_result

        # Fallback antigo: cache JSON de aplicativos conhecidos.
        known_app_result = open_known_app_from_cache(clean_target)

        if known_app_result:
            return known_app_result

        # Fallback manual: usado apenas para programas essenciais/especiais.
        for program_name, program in PROGRAMS.items():
            if program_name in clean_target or program_name in target_lower:
                return _open_program(program_name, program)

        return f"Não encontrei nenhum aplicativo salvo com o nome: {clean_target}"

    if action == "close":
        # Primeiro tenta pelo resolver inteligente usando banco.
        resolved_close_result = close_resolved_app_from_db(clean_target)

        if resolved_close_result:
            return resolved_close_result

        # Fallback antigo: cache JSON.
        known_close_result = close_known_app_from_cache(clean_target)

        if known_close_result:
            return known_close_result

        # Fallback manual para processos especiais.
        for program_name, program in PROGRAMS.items():
            if (program_name in clean_target or program_name in target_lower) and program.get("process"):
                subprocess.call(["taskkill", "/IM", program["process"], "/F"])
                return f"Fechando {program_name}..."

        return f"Não encontrei nenhum processo salvo para fechar: {clean_target}"

    return None