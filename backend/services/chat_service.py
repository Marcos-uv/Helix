import re
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.ai.factory import get_provider

from backend.core.command_executor import (
    create_obsidian_markdown_note,
    execute_command,
    open_obsidian_note,
)

from backend.core.command_interpreter import interpret_command

from backend.core.command_safety import (
    check_command_safety,
    build_confirmation_message,
)

from backend.core.database import (
    ChatHistory,
    get_or_create_user,
)

from backend.core.memory_service import (
    load_relevant_memories,
    save_memory_if_relevant,
)

from backend.core.obsidian_service import (
    log_command_to_obsidian,
    log_event_to_obsidian,
    log_conversation_to_obsidian,
    search_obsidian_notes,
)

from backend.core.local_command_parser import parse_local_command
from backend.core.router_service import route_message

from backend.services.dashboard_service import (
    is_dashboard_update_question,
    build_dashboard_update_response,
)

from backend.services.storage_service import (
    is_storage_cleanup_question,
    _build_storage_scan_context,
    build_storage_scan_response,
    is_full_storage_audit_question,
    build_full_storage_audit_response,
    extract_folder_path_from_message,
    is_specific_folder_audit_question,
    build_specific_folder_audit_response,
)

from backend.services.pc_checkup_service import (
    is_automatic_checkup_question,
    build_automatic_checkup_response,
    _build_pc_context,
)

from backend.services.dev_environment_service import (
    generate_dev_environment_report,
    save_dev_environment_report_to_obsidian,
)

from backend.services.project_creator_service import create_gitignore


SYSTEM_PROMPT = """
Você é Helix, um assistente pessoal local criado pelo Marcos.

Sua função:
- Ajudar o Marcos com programação, organização, automação do PC, Obsidian, PostgreSQL, diagnósticos e tarefas do dia a dia.
- Conversar de forma natural, útil e inteligente.
- Explicar decisões técnicas com clareza.
- Ajudar a manter o projeto Helix organizado e seguro.

Personalidade:
- Você é divertido, vivo e levemente brincalhão.
- Fala como um parceiro técnico, não como um robô seco.
- Pode usar humor leve, comentários rápidos e frases com personalidade.
- Não exagere nas piadas.
- Seja engraçado quando o momento permitir, mas não atrapalhe a resposta.
- Pode chamar o usuário de "chefe" ou "Marcos" às vezes, mas sem repetir toda hora.
- Quando algo der certo, pode comemorar de forma leve.
- Quando algo der errado, seja calmo, útil e explique o próximo passo.

Segurança:
- Nunca apague arquivos sem confirmação explícita.
- Nunca mova, sobrescreva ou edite arquivos importantes sem avisar antes.
- Sempre explique riscos antes de ações perigosas.
- Quando o assunto envolver exclusão, sistema, arquivos sensíveis, comandos perigosos, tokens, chaves de API ou banco de dados, fique mais sério.
- Nunca sacrifique segurança por humor.

Estilo:
- Responda em português do Brasil.
- Seja claro, direto e prático.
- Use linguagem natural.
- Evite respostas longas demais quando o pedido for simples.
- Em explicações técnicas, use exemplos.
- Quando detectar algo importante, explique como se fosse um parceiro ajudando no projeto.

Exemplos de tom:
- "Backend online. O coração do Helix voltou a bater."
- "Modo investigação ativado. Vamos caçar esse bug."
- "Encontrei o problema. Nada explodiu ainda, mas precisamos corrigir isso."
- "Eu não apagaria esse arquivo nem com luva de borracha. Ele parece importante para o projeto."
- "Seu PC está respirando pesado. Vamos ver quem está devorando a RAM."
- "Comando entendido. Preparando os motores."
- "Boa, chefe. Isso aqui já está começando a parecer coisa de ficção científica."
"""


MAX_HISTORY = 10

PENDING_COMMANDS = {}


def _get_request_user_name(request) -> str:
    user_name = getattr(request, "user_name", None)

    if not user_name:
        return "marcos"

    clean_name = str(user_name).strip()

    if not clean_name:
        return "marcos"

    return clean_name


def _get_voice_mode(request) -> bool:
    return bool(getattr(request, "voice_mode", False))


def _history_to_messages(history_raw: list[ChatHistory]) -> list[dict[str, str]]:
    recent_history = []

    for h in reversed(history_raw):
        recent_history.append(
            {
                "role": "user",
                "content": h.user_message,
            }
        )

        recent_history.append(
            {
                "role": "assistant",
                "content": h.ai_response,
            }
        )

    return recent_history


def _load_recent_history(
    db: Session,
    user_id: int,
) -> list[dict[str, str]]:
    try:
        history_raw = (
            db.query(ChatHistory)
            .filter(ChatHistory.user_id == user_id)
            .order_by(ChatHistory.timestamp.desc())
            .limit(MAX_HISTORY)
            .all()
        )

        return _history_to_messages(history_raw)

    except SQLAlchemyError as exc:
        print(f"Banco indisponível ao ler histórico: {exc}")
        db.rollback()
        return []


def _save_history(
    db: Session,
    user_id: int,
    user_message: str,
    ai_response: str,
) -> None:
    try:
        novo = ChatHistory(
            user_id=user_id,
            user_message=user_message,
            ai_response=ai_response,
        )

        db.add(novo)
        db.commit()
        db.refresh(novo)

    except SQLAlchemyError as exc:
        print(f"Banco indisponível ao salvar histórico: {exc}")
        db.rollback()


def _build_memory_context(memories: list[str]) -> str:
    if not memories:
        return ""

    memory_context = "\n\nMemórias relevantes do Helix:\n"

    for memory in memories:
        memory_context += f"- {memory}\n"

    return memory_context


def extract_obsidian_search_terms(user_message: str) -> list[str]:
    text = user_message.lower().strip()

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
        "sobre",
        "que",
        "qual",
        "quais",
        "como",
        "ja",
        "já",
        "foi",
        "foram",
        "tem",
        "tenho",
        "temos",
        "me",
        "te",
        "se",
        "isso",
        "projeto",
    }

    priority_terms = [
        "helix",
        "postgres",
        "postgresql",
        "obsidian",
        "memória",
        "memoria",
        "frontend",
        "backend",
        "arquitetura",
        "dashboard",
        "comando",
        "comandos",
        "regra",
        "regras",
        "decisão",
        "decisoes",
        "decisões",
        "erro",
        "erros",
        "log",
        "logs",
    ]

    terms = []

    for term in priority_terms:
        if term in text and term not in terms:
            terms.append(term)

    words = text.replace("?", "").replace(".", "").replace(",", "").split()

    for word in words:
        if word in stop_words:
            continue

        if len(word) < 4:
            continue

        if word not in terms:
            terms.append(word)

    return terms[:6]


def _build_obsidian_context(user_message: str, limit: int = 5) -> str:
    search_terms = extract_obsidian_search_terms(user_message)

    if not search_terms:
        return ""

    all_results = []
    seen_paths = set()

    for term in search_terms:
        results = search_obsidian_notes(
            query=term,
            limit=limit,
            scope="brain",
        )

        for result in results:
            path = result.get("path")

            if path in seen_paths:
                continue

            seen_paths.add(path)
            all_results.append(result)

            if len(all_results) >= limit:
                break

        if len(all_results) >= limit:
            break

    if not all_results:
        return ""

    context = "\n\nContexto encontrado no Obsidian:\n"

    for result in all_results:
        title = result.get("title", "Sem título")
        path = result.get("path", "caminho desconhecido")
        score = result.get("score", 0)
        snippet = result.get("snippet", "").strip()

        context += f"\nNota: {title}\n"
        context += f"Caminho: {path}\n"
        context += f"Score: {score}\n"
        context += f"Trecho:\n{snippet}\n"

    return context


def build_obsidian_context_debug(
    user_message: str,
    limit: int = 5,
    scope: str = "brain",
) -> dict:
    search_terms = extract_obsidian_search_terms(user_message)

    all_results = []
    seen_paths = set()

    for term in search_terms:
        results = search_obsidian_notes(
            query=term,
            limit=limit,
            scope=scope,
        )

        for result in results:
            path = result.get("path")

            if path in seen_paths:
                continue

            seen_paths.add(path)

            all_results.append(
                {
                    "matched_term": term,
                    "title": result.get("title", "Sem título"),
                    "path": result.get("path", "caminho desconhecido"),
                    "scope": result.get("scope", scope),
                    "score": result.get("score", 0),
                    "snippet": result.get("snippet", "").strip(),
                }
            )

            if len(all_results) >= limit:
                break

        if len(all_results) >= limit:
            break

    return {
        "query": user_message,
        "scope": scope,
        "search_terms": search_terms,
        "count": len(all_results),
        "results": all_results,
    }


async def _save_conversation_summary(
    request,
    db: Session,
    user_id: int,
) -> str:
    recent_history = _load_recent_history(db, user_id)
    memories = load_relevant_memories(db, user_id)
    memory_context = _build_memory_context(memories)

    messages = [
        {
            "role": "system",
            "content": (
                "Resuma a conversa em português do Brasil, em Markdown curto e útil. "
                "Inclua decisões, problemas abertos e próximos passos quando existirem."
                + memory_context
            ),
        },
        *recent_history,
        {"role": "user", "content": request.message},
    ]

    provider = get_provider()

    summary = await provider.generate(
        messages,
        model=request.model,
        temperature=0.2,
        top_p=0.9,
        num_predict=request.num_predict,
    )

    now = datetime.now()
    title = f"Resumo Helix {now:%Y-%m-%d %H-%M}"
    markdown = f"# {title}\n\n{summary.strip()}\n"

    note_path = create_obsidian_markdown_note(title, markdown)
    open_obsidian_note(note_path)

    return f"Resumo salvo no Obsidian: {note_path.name}"


def should_log_conversation(user_message: str, ai_response: str) -> bool:
    text = f"{user_message} {ai_response}".lower().strip()

    if not text:
        return False

    important_keywords = [
        "helix",
        "projeto",
        "progresso",
        "próximo passo",
        "proximos passos",
        "próximos passos",
        "decisão",
        "decidido",
        "erro",
        "bug",
        "problema",
        "corrigir",
        "backend",
        "frontend",
        "postgres",
        "postgresql",
        "obsidian",
        "memória",
        "memoria",
        "comando",
        "arquitetura",
        "dashboard",
        "sistema",
        "organizar",
        "otimizar",
    ]

    if any(keyword in text for keyword in important_keywords):
        return True

    if len(user_message) >= 120:
        return True

    if len(ai_response) >= 500:
        return True

    return False


def is_confirmation_message(message: str) -> bool:
    text = message.lower().strip()

    confirmations = {
        "confirmar",
        "confirmo",
        "confirme",
        "confirmado",
        "confimar",
        "sim confirmar",
        "sim, confirmar",
        "pode confirmar",
        "pode executar",
        "executar",
    }

    return text in confirmations


def should_save_dev_environment_report(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "salve no obsidian",
        "salvar no obsidian",
        "salva no obsidian",
        "registre no obsidian",
        "registrar no obsidian",
        "crie uma nota",
        "criar uma nota",
        "gere uma nota",
        "gerar uma nota",
        "salve esse relatório",
        "salvar esse relatório",
        "salve o relatório",
        "salvar o relatório",
    ]

    return any(keyword in text for keyword in keywords)


def is_dev_environment_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "analise meu ambiente de desenvolvimento",
        "analisar meu ambiente de desenvolvimento",
        "analisa meu ambiente de desenvolvimento",
        "ambiente de desenvolvimento",
        "meu vscode",
        "meu vs code",
        "minhas extensões",
        "minhas extensoes",
        "extensões do vscode",
        "extensoes do vscode",
        "extensões do vs code",
        "extensoes do vs code",
        "quais extensões devo manter",
        "quais extensoes devo manter",
        "quais extensões devo apagar",
        "quais extensoes devo apagar",
        "analise minhas ferramentas",
        "analisar minhas ferramentas",
        "ferramentas de desenvolvimento",
        "meus projetos",
        "encontre meus projetos",
        "analise meus projetos",
        "scanner de desenvolvimento",
        "dev scanner",
    ]

    return any(keyword in text for keyword in keywords)


def build_dev_environment_response(save_to_obsidian: bool = False) -> str:
    report = generate_dev_environment_report()

    vscode = report.get("vscode", {})
    projects = report.get("projects", {})

    extensions = vscode.get("extensions", {})
    essential = extensions.get("essential", [])
    useful = extensions.get("useful", [])
    database = extensions.get("database", [])
    theme_or_visual = extensions.get("theme_or_visual", [])
    review = extensions.get("review", [])
    unknown = extensions.get("unknown", [])

    project_list = projects.get("projects", [])

    response = "Fiz uma análise inicial do seu ambiente de desenvolvimento. Nada foi apagado ou alterado.\n\n"

    response += "## VS Code\n\n"
    response += f"- Extensões encontradas: {vscode.get('count', 0)}\n"
    response += f"- Fonte: {vscode.get('source')}\n"
    response += f"- Essenciais detectadas: {len(essential)}\n"
    response += f"- Úteis/opcionais: {len(useful)}\n"
    response += f"- Banco de dados: {len(database)}\n"
    response += f"- Temas/visuais: {len(theme_or_visual)}\n"
    response += f"- Para revisar: {len(review)}\n"
    response += f"- Desconhecidas: {len(unknown)}\n\n"

    if review:
        response += "### Extensões que eu revisaria primeiro\n\n"

        for item in review[:10]:
            response += f"- `{item.get('id')}` — {item.get('reason')}\n"

        response += "\n"

    if unknown:
        response += "### Extensões não classificadas automaticamente\n\n"

        for item in unknown[:10]:
            response += f"- `{item.get('id')}` — {item.get('reason')}\n"

        response += "\n"

    response += "## Projetos encontrados\n\n"
    response += f"- Projetos detectados: {projects.get('count', 0)}\n\n"

    if project_list:
        response += "### Principais projetos\n\n"

        for project in project_list[:10]:
            technologies = ", ".join(project.get("technologies", [])) or "não identificado"

            response += (
                f"- **{project.get('name')}**\n"
                f"  - Caminho: `{project.get('path')}`\n"
                f"  - Tecnologias: {technologies}\n"
            )

            recommendations = project.get("recommendations", [])

            if recommendations:
                response += f"  - Sugestão: {recommendations[0]}\n"

        response += "\n"

    response += "## Minha leitura inicial\n\n"
    response += (
        "- Seu VS Code tem bastante coisa instalada. Vale fazer uma revisão com calma.\n"
        "- Eu não recomendo apagar nada agora. Primeiro precisamos separar o que é essencial, útil, visual e realmente desnecessário.\n"
        "- O Helix já consegue detectar projetos e tecnologias, então dá para evoluir isso para um relatório no Obsidian.\n"
        "- Próximo passo recomendado: gerar uma lista detalhada das extensões para revisar.\n\n"
    )

    response += (
        "Modo seguro ativado: eu só analisei. Nenhuma extensão foi removida, nenhum projeto foi alterado, "
        "e nenhum arquivo foi apagado. O aspirador inteligente continua com freio de mão puxado."
    )

    if save_to_obsidian:
        note_path = save_dev_environment_report_to_obsidian(report)

        if note_path:
            response += f"\n\nRelatório salvo no Obsidian em:\n`{note_path}`"
        else:
            response += "\n\nTentei salvar o relatório no Obsidian, mas algo falhou no caminho."

    return response


def force_command_route(message: str) -> bool:
    text = message.lower().strip()

    command_starts = [
        "abra ",
        "abrir ",
        "abre ",
        "execute ",
        "executar ",
        "pesquise ",
        "pesquisar ",
        "busque ",
        "buscar ",
        "procure ",
        "procurar ",
        "feche ",
        "fechar ",
        "encerre ",
        "encerrar ",
        "apague ",
        "apagar ",
        "delete ",
        "deletar ",
        "remova ",
        "remover ",
        "exclua ",
        "excluir ",
        "renomeie ",
        "renomear ",
        "mova ",
        "mover ",
        "crie uma nota",
        "criar nota",
        "adicione em",
        "adicionar em",
        "salve no obsidian",
        "resuma no obsidian",
        "crie no obsidian",
        "busque no obsidian",
        "pesquise no obsidian",
        "procure no obsidian",
    ]

    return any(text.startswith(command) for command in command_starts)


def fallback_command_interpreter(message: str) -> dict | None:
    text = message.lower().strip()

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
            target = message[len(start):].strip()

            if target:
                return {
                    "action": "obsidian_delete",
                    "target": target,
                }

    rename_note_patterns = [
        r"^renomeie a nota (.+?) para (.+)$",
        r"^renomear a nota (.+?) para (.+)$",
        r"^renomeie nota (.+?) para (.+)$",
        r"^renomear nota (.+?) para (.+)$",
    ]

    for pattern in rename_note_patterns:
        match = re.match(pattern, text)

        if match:
            old_name = match.group(1).strip()
            new_name = match.group(2).strip()

            if old_name and new_name:
                return {
                    "action": "obsidian_rename",
                    "target": f"{old_name}|{new_name}",
                }

    close_starts = [
        "feche ",
        "fechar ",
        "encerre ",
        "encerrar ",
    ]

    for start in close_starts:
        if text.startswith(start):
            target = message[len(start):].strip()

            if target:
                return {
                    "action": "close",
                    "target": target,
                }

    return None


def is_create_gitignore_question(message: str) -> bool:
    text = message.lower().strip()

    obsidian_note_keywords = [
        "crie uma nota no obsidian",
        "criar uma nota no obsidian",
        "cria uma nota no obsidian",
        "crie nota no obsidian",
        "criar nota no obsidian",
        "salve no obsidian",
        "salvar no obsidian",
        "anote no obsidian",
    ]

    if any(keyword in text for keyword in obsidian_note_keywords):
        return False

    keywords = [
        "crie um gitignore",
        "criar um gitignore",
        "cria um gitignore",
        "crie o gitignore",
        "criar o gitignore",
        "cria o gitignore",
        "crie .gitignore",
        "criar .gitignore",
        "cria .gitignore",
        "crie um .gitignore",
        "criar um .gitignore",
        "cria um .gitignore",
        "crie o .gitignore",
        "criar o .gitignore",
        "cria o .gitignore",
        "gere um gitignore",
        "gerar um gitignore",
        "gera um gitignore",
        "gere .gitignore",
        "gerar .gitignore",
        "gera .gitignore",
        "gere um .gitignore",
        "gerar um .gitignore",
        "gera um .gitignore",
    ]

    return any(keyword in text for keyword in keywords)


def extract_project_path_from_gitignore_message(message: str) -> str | None:
    text = message.strip()

    windows_match = re.search(r"[a-zA-Z]:\\[^<>|?*\n\r]+", text)

    if windows_match:
        return windows_match.group(0).strip().strip('"').strip("'")

    slash_match = re.search(r"[a-zA-Z]:/[^<>|?*\n\r]+", text)

    if slash_match:
        return slash_match.group(0).strip().strip('"').strip("'")

    lowered = text.lower()

    if "helix" in lowered:
        return "D:/Helix"

    return None


def should_overwrite_gitignore(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "sobrescreva",
        "sobrescrever",
        "substitua",
        "substituir",
        "forçar",
        "force",
        "overwrite",
    ]

    return any(keyword in text for keyword in keywords)


def build_create_gitignore_response(user_message: str) -> str:
    project_path = extract_project_path_from_gitignore_message(user_message)

    if not project_path:
        return (
            "Consigo criar o `.gitignore`, mas preciso saber em qual projeto.\n\n"
            "Exemplo:\n"
            "`crie um gitignore no projeto D:\\Helix`"
        )

    overwrite = should_overwrite_gitignore(user_message)

    result = create_gitignore(
        project_path=project_path,
        overwrite=overwrite,
    )

    if result.get("created"):
        response = "`.gitignore` criado com sucesso.\n\n"
        response += f"Arquivo: `{result.get('path')}`\n"

        if result.get("overwritten"):
            response += "\nAtenção: o arquivo existente foi sobrescrito porque você pediu explicitamente."
        else:
            response += "\nNada foi apagado. Apenas criei o arquivo porque ele não existia."

        return response

    response = "Não criei o `.gitignore`.\n\n"
    response += f"Motivo: {result.get('reason')}\n"

    if result.get("path"):
        response += f"Caminho: `{result.get('path')}`\n"

    if result.get("requires_confirmation"):
        response += (
            "\nEle já existe. Por segurança, eu não sobrescrevi.\n"
            "Se quiser substituir mesmo assim, mande:\n"
            "`crie um gitignore no projeto "
            f"{project_path} e sobrescreva`"
        )

    return response


def decide_message_route(user_message: str) -> dict:
    local_command = parse_local_command(user_message)

    if local_command:
        return {
            "type": "command",
            "confidence": 1.0,
            "reason": "Comando reconhecido pelo parser local.",
            "local_command": local_command,
        }

    route = route_message(user_message)

    if force_command_route(user_message):
        return {
            "type": "command",
            "confidence": 1.0,
            "reason": "Forçado como comando por palavra inicial explícita.",
            "local_command": None,
        }

    route["local_command"] = None

    return route


def is_create_obsidian_note_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "crie uma nota no obsidian",
        "criar uma nota no obsidian",
        "cria uma nota no obsidian",
        "crie nota no obsidian",
        "criar nota no obsidian",
        "salve uma nota no obsidian",
        "salvar uma nota no obsidian",
    ]

    return any(keyword in text for keyword in keywords)


def extract_obsidian_note_data(message: str) -> dict:
    text = message.strip()

    title = None
    content = None

    title_patterns = [
        r'chamada\s+"([^"]+)"',
        r"chamada\s+'([^']+)'",
        r'chamado\s+"([^"]+)"',
        r"chamado\s+'([^']+)'",
        r'título\s+"([^"]+)"',
        r"título\s+'([^']+)'",
        r'titulo\s+"([^"]+)"',
        r"titulo\s+'([^']+)'",
    ]

    for pattern in title_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if match:
            title = match.group(1).strip()
            break

    content_patterns = [
        r"com o seguinte conteúdo:\s*(.+)$",
        r"com o seguinte conteudo:\s*(.+)$",
        r"conteúdo:\s*(.+)$",
        r"conteudo:\s*(.+)$",
    ]

    for pattern in content_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if match:
            content = match.group(1).strip()
            break

    return {
        "title": title,
        "content": content,
    }


def build_create_obsidian_note_response(user_message: str) -> str:
    note_data = extract_obsidian_note_data(user_message)

    title = note_data.get("title")
    content = note_data.get("content")

    if not title:
        return (
            "Consigo criar a nota no Obsidian, mas não encontrei o título.\n\n"
            "Use assim:\n"
            '`crie uma nota no Obsidian chamada "Nome da nota" com o seguinte conteúdo: ...`'
        )

    if not content:
        return (
            f"Encontrei o título `{title}`, mas não encontrei o conteúdo da nota.\n\n"
            "Use assim:\n"
            '`com o seguinte conteúdo: ...`'
        )

    markdown = content.strip()

    note_path = create_obsidian_markdown_note(title, markdown)

    try:
        open_obsidian_note(note_path)

    except Exception as exc:
        print(f"Não consegui abrir a nota no Obsidian automaticamente: {exc}")

    return (
        "Nota criada com sucesso no Obsidian.\n\n"
        f"- **Título:** {title}\n"
        f"- **Caminho:** `{note_path}`\n\n"
        "Conteúdo salvo em Markdown. Dessa vez sem o Dev Scanner querer bancar o xerife."
    )


async def process_chat_logic(request, db: Session):
    user_message = request.message.strip()
    user_name = _get_request_user_name(request)
    voice_mode = _get_voice_mode(request)

    user = get_or_create_user(db, user_name)

    if not user_message:
        return {
            "response": "Você não escreveu nada."
        }

    # 1. Criação explícita de nota no Obsidian
    if is_create_obsidian_note_question(user_message):
        result = build_create_obsidian_note_response(user_message)

        _save_history(db, user.id, user_message, result)

        try:
            log_event_to_obsidian(
                event="Nota criada no Obsidian pelo chat.",
                context="/chat",
                details="O usuário pediu criação explícita de nota no Obsidian.",
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar criação de nota no Obsidian: {exc}")

        return {
            "response": result
        }

    # 2. Confirmação de comando pendente
    if is_confirmation_message(user_message):
        pending = PENDING_COMMANDS.get(user.id)

        if not pending:
            result = "Não há nenhum comando pendente para confirmar."
            _save_history(db, user.id, user_message, result)

            return {
                "response": result
            }

        action = pending["action"]
        target = pending["target"]
        original_message = pending["user_message"]

        result = execute_command(action, target)

        PENDING_COMMANDS.pop(user.id, None)

        if not result:
            result = "Tentei executar o comando confirmado, mas ele não retornou resultado."

        try:
            log_command_to_obsidian(
                user_message=f"{original_message} | confirmação: {user_message}",
                action=action,
                target=target,
                result=result,
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar comando confirmado no Obsidian: {exc}")

        _save_history(db, user.id, user_message, result)

        return {
            "response": result
        }

    # 3. Roteamento principal
    route = decide_message_route(user_message)

    print("ROTA DA MENSAGEM:", route)

    if route.get("type") == "memory":
        save_memory_if_relevant(db, user.id, user_message)

    command_data = None

    if route.get("type") == "command":
        local_command = route.get("local_command")

        if local_command:
            command_data = local_command

        else:
            command_data = await interpret_command(user_message)

            fallback_data = fallback_command_interpreter(user_message)

            if fallback_data:
                command_data = fallback_data

        print("COMANDO INTERPRETADO:", command_data)

    if (
        route.get("type") == "command"
        and command_data
        and command_data.get("action")
        and command_data.get("target")
    ):
        action = command_data["action"]
        target = command_data["target"]

        if action == "obsidian_summary":
            result = await _save_conversation_summary(request, db, user.id)

            try:
                log_command_to_obsidian(
                    user_message=user_message,
                    action=action,
                    target=target,
                    result=result,
                    user_name=user_name,
                )

            except Exception as exc:
                print(f"Erro ao registrar comando no Obsidian: {exc}")

            _save_history(db, user.id, user_message, result)

            return {
                "response": result
            }

        safety = check_command_safety(action, target)

        if safety["requires_confirmation"]:
            PENDING_COMMANDS[user.id] = {
                "action": action,
                "target": target,
                "user_message": user_message,
                "created_at": datetime.now().isoformat(),
            }

            result = (
                build_confirmation_message(action, target, safety)
                + "\n\nSe quiser executar mesmo assim, responda: `confirmar`."
            )

            try:
                log_command_to_obsidian(
                    user_message=user_message,
                    action=action,
                    target=target,
                    result="Comando aguardando confirmação.",
                    user_name=user_name,
                )

            except Exception as exc:
                print(f"Erro ao registrar comando pendente no Obsidian: {exc}")

            _save_history(db, user.id, user_message, result)

            return {
                "response": result
            }

        if not safety["allowed"]:
            result = f"Comando bloqueado por segurança: {safety['reason']}"
            _save_history(db, user.id, user_message, result)

            return {
                "response": result
            }

        result = execute_command(action, target)

        if result:
            try:
                log_command_to_obsidian(
                    user_message=user_message,
                    action=action,
                    target=target,
                    result=result,
                    user_name=user_name,
                )

            except Exception as exc:
                print(f"Erro ao registrar comando no Obsidian: {exc}")

            _save_history(db, user.id, user_message, result)

            return {
                "response": result
            }

        print("⚠️ Comando detectado, mas falhou. Usando IA como fallback...")

    # 4. Criar .gitignore
    if is_create_gitignore_question(user_message):
        result = build_create_gitignore_response(user_message)

        _save_history(db, user.id, user_message, result)

        try:
            log_event_to_obsidian(
                event="Gitignore solicitado pelo chat.",
                context="/chat",
                details="O usuário pediu criação de .gitignore em um projeto.",
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar criação de gitignore no Obsidian: {exc}")

        return {
            "response": result
        }

    # 5. Dev Scanner
    if is_dev_environment_question(user_message):
        save_to_obsidian = should_save_dev_environment_report(user_message)
        result = build_dev_environment_response(save_to_obsidian=save_to_obsidian)

        _save_history(db, user.id, user_message, result)

        try:
            log_event_to_obsidian(
                event="Ambiente de desenvolvimento analisado pelo chat.",
                context="/chat",
                details="O usuário pediu análise do VS Code, extensões, ferramentas ou projetos.",
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar análise do ambiente dev no Obsidian: {exc}")

        return {
            "response": result
        }

    # 6. Dashboard
    if is_dashboard_update_question(user_message):
        result = build_dashboard_update_response()

        _save_history(db, user.id, user_message, result)

        try:
            log_event_to_obsidian(
                event="Dashboard Helix atualizado por comando natural.",
                context="/chat",
                details="O usuário pediu atualização do dashboard pelo chat.",
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar atualização natural do dashboard no Obsidian: {exc}")

        return {
            "response": result
        }

    # 7. Auditoria de pasta específica
    if is_specific_folder_audit_question(user_message):
        folder_path = extract_folder_path_from_message(user_message)

        if not folder_path:
            result = (
                "Me diga qual pasta você quer que eu analise.\n\n"
                "Exemplo:\n"
                "`analise a pasta C:\\ProgramData\\BlueStacks_nxt`"
            )

        else:
            result = build_specific_folder_audit_response(folder_path)

        _save_history(db, user.id, user_message, result)

        try:
            log_event_to_obsidian(
                event="Auditoria de pasta específica consultada pelo chat.",
                context="/chat",
                details=f"Pasta solicitada: {folder_path}",
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar auditoria de pasta no Obsidian: {exc}")

        return {
            "response": result
        }

    # 8. Auditoria completa de armazenamento
    if is_full_storage_audit_question(user_message):
        result = build_full_storage_audit_response()

        _save_history(db, user.id, user_message, result)

        try:
            log_event_to_obsidian(
                event="Auditoria completa de armazenamento consultada pelo chat.",
                context="/chat",
                details="O usuário pediu uma avaliação completa do armazenamento do C:.",
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar auditoria completa no Obsidian: {exc}")

        return {
            "response": result
        }

    # 9. Scanner seguro de armazenamento
    if is_storage_cleanup_question(user_message):
        result = build_storage_scan_response()

        _save_history(db, user.id, user_message, result)

        try:
            log_event_to_obsidian(
                event="Scanner de armazenamento consultado pelo chat.",
                context="/chat",
                details="O usuário pediu ajuda para liberar espaço no disco C:.",
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar scanner de armazenamento no Obsidian: {exc}")

        return {
            "response": result
        }

    # 10. Check-up automático do PC
    if is_automatic_checkup_question(user_message):
        result = build_automatic_checkup_response()

        _save_history(db, user.id, user_message, result)

        try:
            log_event_to_obsidian(
                event="Check-up automático do PC consultado pelo chat.",
                context="/chat",
                details="O usuário pediu uma avaliação automática do estado atual do PC.",
                user_name=user_name,
            )

        except Exception as exc:
            print(f"Erro ao registrar check-up automático no Obsidian: {exc}")

        return {
            "response": result
        }

    # 11. Fallback para IA normal
    recent_history = _load_recent_history(db, user.id)

    memories = load_relevant_memories(db, user.id)
    memory_context = _build_memory_context(memories)

    obsidian_context = _build_obsidian_context(user_message)
    pc_context = _build_pc_context(user_message)
    storage_scan_context = _build_storage_scan_context(user_message)

    system_content = (
        SYSTEM_PROMPT
        + memory_context
        + obsidian_context
        + pc_context
        + storage_scan_context
    )

    if voice_mode:
        system_content += (
            "\nModo voz ativo: a mensagem do usuário foi transcrita do microfone. "
            "Responda como se estivesse ouvindo a pessoa pelo Helix. "
            "Use respostas mais curtas, naturais e boas para serem faladas."
        )

    messages = [
        {
            "role": "system",
            "content": system_content,
        },
        *recent_history,
        {
            "role": "user",
            "content": user_message,
        },
    ]

    provider = get_provider()

    ai_response = await provider.generate(
        messages,
        model=request.model,
        temperature=request.temperature,
        top_p=request.top_p,
        num_predict=request.num_predict,
    )

    _save_history(db, user.id, user_message, ai_response)

    try:
        if route.get("type") == "chat" and should_log_conversation(
            user_message,
            ai_response,
        ):
            log_conversation_to_obsidian(
                user_message=user_message,
                ai_response=ai_response,
                user_name=user_name,
            )

    except Exception as exc:
        print(f"Erro ao registrar conversa no Obsidian: {exc}")

    return {
        "response": ai_response
    }