import json
import re
import unicodedata

from backend.ai.factory import get_provider

OPEN_COMMANDS = ["abrir", "abre", "iniciar", "executar", "abra", "rodar", "start", "run", "open"]
CLOSE_COMMANDS = ["fechar", "fecha", "encerrar", "terminar", "close", "kill", "feche"]
SEARCH_COMMANDS = ["pesquisar", "procurar", "buscar", "search"]
OBSIDIAN_LIST_COMMANDS = [
    "minhas notas",
    "mostrar minhas notas",
    "mostre minhas notas",
    "ver minhas notas",
    "veja minhas notas",
    "listar minhas notas",
    "listar notas no obsidian",
    "listar notas no obisidian",
    "liste as notas no obsidian",
    "liste as notas no obisidian",
    "liste o que esta no obsidian",
    "liste o que esta no obisidian",
    "mostrar notas no obsidian",
    "mostrar notas no obisidian",
    "o que tem no obsidian",
    "o que tem no obisidian",
    "o que tem nas minhas notas",
    "o que tem nas notas",
]
OBSIDIAN_OPEN_COMMANDS = [
    "acessar obsidian",
    "acesse o obsidian",
    "acessar o obsidian",
    "entrar no obsidian",
    "abra meu obsidian",
    "abrir meu obsidian",
]
OBSIDIAN_OPEN_NOTE_COMMANDS = [
    "abrir nota",
    "abra nota",
    "abrir no obsidian",
    "abrir no obisidian",
]
OBSIDIAN_READ_COMMANDS = [
    "ler nota",
    "leia nota",
    "mostrar nota",
    "ver nota",
]
OBSIDIAN_SEARCH_COMMANDS = [
    "buscar no obsidian",
    "buscar no obisidian",
    "procurar no obsidian",
    "procurar no obisidian",
    "buscar nas notas",
    "procurar nas notas",
]
OBSIDIAN_APPEND_COMMANDS = [
    "adicionar em",
    "adicionar na nota",
    "adicionar no obsidian",
    "append nota",
]
OBSIDIAN_RESTORE_COMMANDS = [
    "restaurar nota",
    "recuperar nota",
    "restaurar do obsidian",
    "restaurar da lixeira",
]
OBSIDIAN_DELETE_COMMANDS = [
    "deletar nota",
    "apagar nota",
    "remover nota",
    "deletar no obsidian",
    "apagar no obsidian",
    "remover no obsidian",
]
OBSIDIAN_RENAME_COMMANDS = [
    "renomear nota",
    "renomeie nota",
    "renomear no obsidian",
    "mudar nome da nota",
]
OBSIDIAN_LINK_COMMANDS = [
    "ligar nota",
    "conectar nota",
    "linkar nota",
    "ligar no obsidian",
    "conectar no obsidian",
    "linkar no obsidian",
]
OBSIDIAN_HUB_COMMANDS = [
    "criar hub no obsidian",
    "criar indice no obsidian",
    "criar índice no obsidian",
    "criar nota hub",
    "crie uma nota chamada",
]
OBSIDIAN_NOTE_COMMANDS = [
    "salvar no obsidian",
    "criar nota no obsidian",
    "nova nota no obsidian",
    "anotar no obsidian",
]
OBSIDIAN_SUMMARY_COMMANDS = [
    "resumir conversa no obsidian",
    "salvar resumo no obsidian",
    "resumir nossa conversa no obsidian",
    "deixar resumo no obsidian",
]

SYSTEM_COMMAND_PROMPT = """
Voce e um interpretador de comandos.

Sua tarefa e analisar a mensagem do usuario e responder APENAS em JSON valido.

{
    "action": "open" | "close" | "search" | "obsidian_note" | "obsidian_summary" | "obsidian_delete" | "obsidian_link" | "obsidian_hub" | "obsidian_rename" | "obsidian_list" | "obsidian_open_note" | "obsidian_read" | "obsidian_search" | "obsidian_append" | "obsidian_restore" | null,
    "target": "nome_do_programa_ou_site_ou_busca" | null
}

Regras:
- Se for um comando para abrir algo, action = "open"
- Se for para fechar algo, action = "close"
- Se for para pesquisar algo, action = "search"
- Se for para salvar ou criar nota no Obsidian, action = "obsidian_note"
- Se for para listar notas do Obsidian, action = "obsidian_list"
- Se for para abrir uma nota especifica do Obsidian, action = "obsidian_open_note"
- Se for para ler uma nota do Obsidian, action = "obsidian_read"
- Se for para buscar dentro das notas do Obsidian, action = "obsidian_search"
- Se for para adicionar texto a uma nota do Obsidian, action = "obsidian_append"
- Se for para restaurar uma nota da lixeira do Obsidian, action = "obsidian_restore"
- Se for para resumir a conversa no Obsidian, action = "obsidian_summary"
- Se for para apagar uma nota do Obsidian, action = "obsidian_delete"
- Se for para renomear uma nota do Obsidian, action = "obsidian_rename"
- Se for para ligar duas notas do Obsidian, action = "obsidian_link"
- Se for para criar uma nota central/indice/hub no Obsidian, action = "obsidian_hub"
- Se nao for comando, action = null
- Nao explique nada
- Nao escreva texto fora JSON
"""


OBSIDIAN_ALIAS_RE = re.compile(r"\b(obs|obsidian|obisidian|obsidina|obsidiana)\b", re.IGNORECASE)


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _has_obsidian_alias(text: str) -> bool:
    return bool(OBSIDIAN_ALIAS_RE.search(_normalize_text(text)))


def _looks_like_obsidian_open(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    return _has_obsidian_alias(normalized) and bool(
        re.search(r"\b(abrir|abre|abra|acessar|acesse|entrar|iniciar|executar)\b", normalized)
    )


def _looks_like_obsidian_list(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    has_notes_word = bool(re.search(r"\b(nota|notas|vault)\b", normalized))
    has_obsidian = _has_obsidian_alias(normalized)
    has_list_intent = bool(
        re.search(
            r"\b(lista|liste|listar|mostra|mostrar|mostre|ver|veja|exibir|exiba)\b|o que tem",
            normalized,
        )
    )
    return has_list_intent and (has_obsidian or has_notes_word)


def _extract_target(text: str, commands: list[str]) -> str | None:
    text_clean = text.strip()
    text_lower = text_clean.lower()

    for command in commands:
        if text_lower.startswith(command):
            return text_clean[len(command):].strip() or None

        marker = f" {command} "
        padded_text = f" {text_lower} "
        if marker in padded_text:
            command_index = text_lower.find(command)
            return text_clean[command_index + len(command):].strip() or None

    return None


def _matches_command(text: str, commands: list[str]) -> bool:
    text_lower = text.strip().lower()
    return any(text_lower == command or text_lower.startswith(f"{command}:") for command in commands)


def _clean_obsidian_target(target: str) -> str:
    target = target.strip().lstrip(":").strip()
    target = target.removesuffix(".md").strip()
    for suffix in [" no obsidian", " do obsidian", " da obsidian"]:
        if target.lower().endswith(suffix):
            target = target[: -len(suffix)].strip()
    return target


def _extract_obsidian_link_target(text: str) -> str | None:
    target = _extract_target(text, OBSIDIAN_LINK_COMMANDS)
    if not target:
        return None

    target = _clean_obsidian_target(target)
    separators = [" com ", " a ", " para "]
    target_lower = target.lower()
    for separator in separators:
        if separator in target_lower:
            index = target_lower.find(separator)
            source = _clean_obsidian_target(target[:index])
            destination = _clean_obsidian_target(target[index + len(separator):])
            if source and destination:
                return f"{source}|{destination}"

    return None


def _extract_obsidian_rename_target(text: str) -> str | None:
    target = _extract_target(text, OBSIDIAN_RENAME_COMMANDS)
    if not target:
        return None

    target = _clean_obsidian_target(target)
    target_lower = target.lower()
    separators = [" para ", " como ", " por "]
    for separator in separators:
        if separator in target_lower:
            index = target_lower.find(separator)
            old_name = _clean_obsidian_target(target[:index])
            new_name = _clean_obsidian_target(target[index + len(separator):])
            if old_name and new_name:
                return f"{old_name}|{new_name}"

    return None


def _extract_obsidian_append_target(text: str) -> str | None:
    target = _extract_target(text, OBSIDIAN_APPEND_COMMANDS)
    if not target:
        return None

    target = target.strip().lstrip(":").strip()
    target_lower = target.lower()
    separators = [":", " texto ", " conteudo ", " conteúdo "]
    for separator in separators:
        if separator in target_lower:
            index = target_lower.find(separator)
            note_name = _clean_obsidian_target(target[:index])
            content = target[index + len(separator):].strip()
            if note_name and content:
                return f"{note_name}|{content}"

    return None


def _extract_obsidian_search_target(text: str) -> str | None:
    target = _extract_target(text, OBSIDIAN_SEARCH_COMMANDS)
    if target:
        return _clean_obsidian_target(target)

    text_clean = text.strip()
    text_lower = text_clean.lower()
    patterns = [
        ("buscar ", " no obsidian"),
        ("buscar ", " no obisidian"),
        ("procurar ", " no obsidian"),
        ("procurar ", " no obisidian"),
        ("buscar ", " nas notas"),
        ("procurar ", " nas notas"),
    ]

    for prefix, suffix in patterns:
        if text_lower.startswith(prefix) and text_lower.endswith(suffix):
            return text_clean[len(prefix): -len(suffix)].strip()

    return None


def _extract_obsidian_hub_target(text: str) -> str | None:
    target = _extract_target(text, OBSIDIAN_HUB_COMMANDS)
    if not target:
        return None

    target = target.replace("chamada", "").replace("chamado", "").strip()
    target_lower = target.lower()
    endings = [
        " e link as anteriores com ela",
        " e linkar as anteriores com ela",
        " e ligar as anteriores com ela",
        " e conectar as anteriores com ela",
        " e link elas",
    ]
    for ending in endings:
        if target_lower.endswith(ending):
            target = target[: -len(ending)].strip()
            break

    return _clean_obsidian_target(target)


async def interpret_command(user_input: str):
    try:
        user_input = re.sub("obisidian", "obsidian", user_input, flags=re.IGNORECASE)
        user_input = re.sub("obsidina", "obsidian", user_input, flags=re.IGNORECASE)

        obsidian_open_note_target = _extract_target(user_input, OBSIDIAN_OPEN_NOTE_COMMANDS)
        if obsidian_open_note_target:
            return {"action": "obsidian_open_note", "target": _clean_obsidian_target(obsidian_open_note_target)}

        if _matches_command(user_input, OBSIDIAN_LIST_COMMANDS):
            return {"action": "obsidian_list", "target": "notas"}

        if _looks_like_obsidian_list(user_input):
            return {"action": "obsidian_list", "target": "notas"}

        if _matches_command(user_input, OBSIDIAN_OPEN_COMMANDS):
            return {"action": "open", "target": "obsidian"}

        if _looks_like_obsidian_open(user_input):
            return {"action": "open", "target": "obsidian"}

        if re.search(r"\b(obsidian|notas)\b", user_input, flags=re.IGNORECASE) and re.search(
            r"\b(acessar|acesso|ver|mostrar|mostra|listar|lista|ler|abrir)\b",
            user_input,
            flags=re.IGNORECASE,
        ):
            return {"action": "obsidian_list", "target": "notas"}

        if _matches_command(user_input, OBSIDIAN_SUMMARY_COMMANDS):
            return {"action": "obsidian_summary", "target": "conversa"}

        obsidian_append_target = _extract_obsidian_append_target(user_input)
        if obsidian_append_target:
            return {"action": "obsidian_append", "target": obsidian_append_target}

        obsidian_search_target = _extract_obsidian_search_target(user_input)
        if obsidian_search_target:
            return {"action": "obsidian_search", "target": obsidian_search_target}

        obsidian_read_target = _extract_target(user_input, OBSIDIAN_READ_COMMANDS)
        if obsidian_read_target:
            return {"action": "obsidian_read", "target": _clean_obsidian_target(obsidian_read_target)}

        obsidian_restore_target = _extract_target(user_input, OBSIDIAN_RESTORE_COMMANDS)
        if obsidian_restore_target:
            return {"action": "obsidian_restore", "target": _clean_obsidian_target(obsidian_restore_target)}

        obsidian_hub_target = _extract_obsidian_hub_target(user_input)
        if obsidian_hub_target:
            return {"action": "obsidian_hub", "target": obsidian_hub_target}

        obsidian_rename_target = _extract_obsidian_rename_target(user_input)
        if obsidian_rename_target:
            return {"action": "obsidian_rename", "target": obsidian_rename_target}

        obsidian_link_target = _extract_obsidian_link_target(user_input)
        if obsidian_link_target:
            return {"action": "obsidian_link", "target": obsidian_link_target}

        obsidian_delete_target = _extract_target(user_input, OBSIDIAN_DELETE_COMMANDS)
        if obsidian_delete_target:
            return {"action": "obsidian_delete", "target": _clean_obsidian_target(obsidian_delete_target)}

        obsidian_note_target = _extract_target(user_input, OBSIDIAN_NOTE_COMMANDS)
        if obsidian_note_target:
            return {"action": "obsidian_note", "target": obsidian_note_target}

        search_target = _extract_target(user_input, SEARCH_COMMANDS)
        if search_target:
            return {"action": "search", "target": search_target}

        open_target = _extract_target(user_input, OPEN_COMMANDS)
        if open_target:
            return {"action": "open", "target": open_target}

        close_target = _extract_target(user_input, CLOSE_COMMANDS)
        if close_target:
            return {"action": "close", "target": close_target}

        messages = [
            {"role": "system", "content": SYSTEM_COMMAND_PROMPT},
            {"role": "user", "content": user_input},
        ]

        response = await get_provider().generate(messages, temperature=0, top_p=1)

        try:
            data = json.loads(response)
            return {
                "action": data.get("action"),
                "target": data.get("target"),
            }
        except json.JSONDecodeError:
            return {"action": None, "target": None}
    except Exception as e:
        print(f"Erro no interpret_command: {e}")
        return {"action": None, "target": None}
