import re


def parse_local_command(message: str) -> dict | None:
    original = message.strip()
    text = original.lower().strip()

    if not text:
        return None

    # Abrir app/site
    open_starts = [
        "abra ",
        "abrir ",
        "abre ",
        "inicie ",
        "iniciar ",
    ]

    for start in open_starts:
        if text.startswith(start):
            target = original[len(start):].strip()
            if target:
                return {
                    "action": "open",
                    "target": target,
                }

    # Fechar app
    close_starts = [
        "feche ",
        "fechar ",
        "encerre ",
        "encerrar ",
    ]

    for start in close_starts:
        if text.startswith(start):
            target = original[len(start):].strip()
            if target:
                return {
                    "action": "close",
                    "target": target,
                }

    # Buscar no Obsidian
    # IMPORTANTE: vem antes da busca genérica na web.
    obsidian_search_starts = [
        "busque no obsidian ",
        "buscar no obsidian ",
        "pesquise no obsidian ",
        "pesquisar no obsidian ",
        "procure no obsidian ",
        "procurar no obsidian ",
    ]

    for start in obsidian_search_starts:
        if text.startswith(start):
            target = original[len(start):].strip()
            if target:
                return {
                    "action": "obsidian_search",
                    "target": target,
                }

    # Pesquisar na web
    search_starts = [
        "pesquise ",
        "pesquisar ",
        "busque ",
        "buscar ",
        "procure ",
        "procurar ",
    ]

    for start in search_starts:
        if text.startswith(start):
            target = original[len(start):].strip()
            if target:
                return {
                    "action": "search",
                    "target": target,
                }

    # Apagar nota
    delete_note_starts = [
        "apague a nota ",
        "apagar a nota ",
        "delete a nota ",
        "deletar a nota ",
        "remova a nota ",
        "remover a nota ",
        "exclua a nota ",
        "excluir a nota ",
    ]

    for start in delete_note_starts:
        if text.startswith(start):
            target = original[len(start):].strip()
            if target:
                return {
                    "action": "obsidian_delete",
                    "target": target,
                }

    # Renomear nota
    # Exemplo: "renomeie a nota aaa para teste"
    rename_patterns = [
        r"^renomeie a nota (.+?) para (.+)$",
        r"^renomear a nota (.+?) para (.+)$",
        r"^renomeie nota (.+?) para (.+)$",
        r"^renomear nota (.+?) para (.+)$",
    ]

    for pattern in rename_patterns:
        match = re.match(pattern, text)

        if match:
            old_name = match.group(1).strip()
            new_name = match.group(2).strip()

            if old_name and new_name:
                return {
                    "action": "obsidian_rename",
                    "target": f"{old_name}|{new_name}",
                }

    # Ler nota
    read_note_starts = [
        "leia a nota ",
        "ler a nota ",
        "mostre a nota ",
        "mostrar a nota ",
    ]

    for start in read_note_starts:
        if text.startswith(start):
            target = original[len(start):].strip()
            if target:
                return {
                    "action": "obsidian_read",
                    "target": target,
                }

    # Abrir nota
    open_note_starts = [
        "abra a nota ",
        "abrir a nota ",
        "abre a nota ",
    ]

    for start in open_note_starts:
        if text.startswith(start):
            target = original[len(start):].strip()
            if target:
                return {
                    "action": "obsidian_open_note",
                    "target": target,
                }

    # Criar nota no Obsidian
    create_note_starts = [
        "crie uma nota ",
        "criar uma nota ",
        "crie nota ",
        "criar nota ",
        "crie no obsidian ",
        "salve no obsidian ",
    ]

    for start in create_note_starts:
        if text.startswith(start):
            target = original[len(start):].strip()
            if target:
                return {
                    "action": "obsidian_note",
                    "target": target,
                }

    # Adicionar em nota
    # Exemplo: "adicione em Nome da Nota: texto"
    append_patterns = [
        r"^adicione em (.+?):\s*(.+)$",
        r"^adicionar em (.+?):\s*(.+)$",
        r"^anote em (.+?):\s*(.+)$",
    ]

    for pattern in append_patterns:
        match = re.match(pattern, original, flags=re.IGNORECASE)

        if match:
            note_name = match.group(1).strip()
            content = match.group(2).strip()

            if note_name and content:
                return {
                    "action": "obsidian_append",
                    "target": f"{note_name}|{content}",
                }

    # Listar notas
    list_note_starts = [
        "liste as notas",
        "listar notas",
        "mostre as notas",
        "mostrar notas",
    ]

    if text in list_note_starts:
        return {
            "action": "obsidian_list",
            "target": "all",
        }

    # Resumir conversa no Obsidian
    summary_starts = [
        "resuma no obsidian",
        "salve resumo no obsidian",
        "resumir conversa no obsidian",
    ]

    if text in summary_starts:
        return {
            "action": "obsidian_summary",
            "target": "conversation",
        }

    return None