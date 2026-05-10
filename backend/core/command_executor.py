import json
import os
import re
import subprocess
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, quote_plus


OBSIDIAN_VAULT_PATH = Path(
    os.environ.get(
        "HELIX_OBSIDIAN_VAULT",
        r"C:\Users\Marcos\OneDrive\Documentos\Helix Vault",
    )
)
OBSIDIAN_VAULT_NAME = os.environ.get("HELIX_OBSIDIAN_VAULT_NAME", "Helix Vault")
OBSIDIAN_CONFIG_PATH = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"

PROGRAMS = {
    "opera": {
        "path": r"C:\Users\Marcos\AppData\Local\Programs\Opera GX\opera.exe",
        "process": "opera.exe",
    },
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
    "abrir",
    "agora",
    "ainda",
    "alguma",
    "algum",
    "anotar",
    "aqui",
    "assim",
    "cada",
    "chamada",
    "chamado",
    "como",
    "com",
    "conversa",
    "criado",
    "criar",
    "da",
    "das",
    "de",
    "dei",
    "deixa",
    "deixar",
    "dele",
    "dela",
    "disso",
    "do",
    "dos",
    "ele",
    "ela",
    "em",
    "essa",
    "esse",
    "esta",
    "este",
    "eu",
    "foi",
    "helix",
    "isso",
    "ja",
    "mais",
    "mas",
    "meu",
    "minha",
    "na",
    "nas",
    "no",
    "nos",
    "nota",
    "nova",
    "novo",
    "obsidian",
    "para",
    "pela",
    "pelo",
    "por",
    "que",
    "salvar",
    "sem",
    "sobre",
    "sua",
    "suo",
    "tem",
    "ter",
    "teste",
    "um",
    "uma",
    "vai",
    "voce",
}


def _sanitize_filename(filename: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*]', "", filename).strip()
    filename = re.sub(r"\s+", " ", filename)
    return filename[:80] or "Nota Helix"


def _normalize_note_name(note_name: str) -> str:
    note_name = note_name.strip().removesuffix(".md").strip()
    return _sanitize_filename(note_name).lower()


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


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem} {counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _extract_keywords(text: str) -> set[str]:
    words = set(re.findall(r"[a-zA-Z0-9_]{3,}", text.lower()))
    keywords = {
        word
        for word in words
        if word not in AUTO_LINK_STOPWORDS and (len(word) >= 5 or word in AUTO_LINK_STRONG_KEYWORDS)
    }
    return keywords | (words & AUTO_LINK_STRONG_KEYWORDS)


def _note_keywords(note_path: Path) -> set[str]:
    try:
        content = note_path.read_text(encoding="utf-8")
    except OSError:
        content = ""

    return _extract_keywords(f"{note_path.stem}\n{content}")


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


def _create_obsidian_note(target: str) -> str:
    title, markdown = _parse_obsidian_note(target)
    note_path = create_obsidian_markdown_note(title, markdown)
    _open_obsidian_file(note_path)
    return f"Nota criada no Obsidian: {note_path.name}"


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


def _normalize_url(target: str) -> str | None:
    target = target.strip()
    if not target:
        return None

    if target.startswith(("http://", "https://")):
        return target

    if target.startswith("www.") or "." in target:
        return f"https://{target}"

    return None


def execute_command(action: str, target: str):
    action = (action or "").lower().strip()
    target = (target or "").strip()
    target_lower = target.lower()

    if not action or not target:
        return None

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
            if site_name in target_lower:
                webbrowser.open(url)
                return f"Abrindo {site_name}..."

        url = _normalize_url(target)
        if url:
            webbrowser.open(url)
            return f"Abrindo {url}..."

        for program_name, program in PROGRAMS.items():
            if program_name in target_lower:
                if program.get("args"):
                    subprocess.Popen([program["path"], *program["args"]])
                else:
                    os.startfile(program["path"])
                return f"Abrindo {program_name}..."

    if action == "close":
        for program_name, program in PROGRAMS.items():
            if program_name in target_lower:
                subprocess.call(["taskkill", "/IM", program["process"], "/F"])
                return f"Fechando {program_name}..."

    return None
