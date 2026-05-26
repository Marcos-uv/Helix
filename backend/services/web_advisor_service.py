from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from backend.services.web_access_service import (
    WebSearchResult,
    build_practical_summary,
    fetch_page_text,
    fetch_web_search_results,
    get_source_type,
    rank_web_search_results,
)


# ============================================================
# Helix Web Advisor Service - v1
#
# Objetivo:
# - Juntar pesquisa web + contexto real do projeto Helix.
# - Dar opinião técnica prática.
# - Sugerir arquivos, estrutura e caminho de implementação.
#
# Esta v1 é determinística.
# A v2 pode usar LLM com contexto web + contexto do projeto.
# ============================================================


HELIX_PROJECT_ROOT = Path(
    os.environ.get("HELIX_PROJECT_ROOT", r"D:\Helix")
).resolve()


ADVISOR_TRIGGERS = [
    "como aplicar no helix",
    "como aplicar na helix",
    "aplicar no helix",
    "aplicar na helix",
    "usar no helix",
    "usar na helix",
    "vale a pena usar",
    "vale usar",
    "onde eu adicionaria",
    "onde adicionaria",
    "em que arquivo",
    "em qual arquivo",
    "como ficaria a estrutura",
    "como ficaria no projeto",
    "como ficaria no nosso projeto",
    "como implementar no helix",
    "como implementar na helix",
    "me diga como aplicar",
    "diga como aplicar",
    "opinião",
    "opiniao",
    "o que você acha",
    "o que voce acha",
]


PROJECT_WORDS = [
    "helix",
    "projeto",
    "nosso projeto",
    "meu projeto",
    "seu projeto",
    "código",
    "codigo",
    "estrutura",
    "arquivo",
    "arquivos",
    "backend",
    "frontend",
]


IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def is_web_advisor_intent(message: str) -> bool:
    text = normalize_text(message)

    has_advisor_trigger = any(trigger in text for trigger in ADVISOR_TRIGGERS)
    has_project_word = any(word in text for word in PROJECT_WORDS)

    has_web_trigger = any(
        trigger in text
        for trigger in [
            "pesquise",
            "pesquisar",
            "procure",
            "buscar",
            "busque",
            "na web",
            "na internet",
        ]
    )

    return has_web_trigger and (has_advisor_trigger or has_project_word)


def clean_advisor_query(message: str) -> str:
    text = message.strip()

    patterns = [
        r"pesquise na internet sobre\s+(.+)",
        r"pesquisar na internet sobre\s+(.+)",
        r"procure na internet sobre\s+(.+)",
        r"busque na internet sobre\s+(.+)",
        r"pesquise na web sobre\s+(.+)",
        r"procure na web sobre\s+(.+)",
        r"busque na web sobre\s+(.+)",
        r"pesquise sobre\s+(.+)",
        r"pesquisar sobre\s+(.+)",
        r"procure sobre\s+(.+)",
        r"busque sobre\s+(.+)",
        r"buscar sobre\s+(.+)",
    ]

    lowered = text.lower()

    query = ""

    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)

        if match:
            query = text[match.start(1):].strip()
            break

    if not query:
        query = text

    suffix_patterns = [
        r"\s+e\s+me\s+diga\s+como\s+aplicar.*$",
        r"\s+e\s+diga\s+como\s+aplicar.*$",
        r"\s+e\s+como\s+aplicar.*$",
        r"\s+e\s+me\s+explique.*$",
        r"\s+e\s+explique.*$",
        r"\s+e\s+resuma.*$",
        r"\s+no\s+helix.*$",
        r"\s+na\s+helix.*$",
        r"\s+no\s+nosso\s+projeto.*$",
        r"\s+no\s+meu\s+projeto.*$",
        r"\s+nesse\s+projeto.*$",
        r"\s+em\s+que\s+arquivo.*$",
        r"\s+em\s+qual\s+arquivo.*$",
        r"\s+como\s+ficaria\s+a\s+estrutura.*$",
        r"\s+vale\s+a\s+pena.*$",
    ]

    for pattern in suffix_patterns:
        query = re.sub(pattern, "", query, flags=re.IGNORECASE).strip()

    query = re.sub(r"[?.!]+$", "", query).strip()

    return query


def safe_relative(path: Path) -> str:
    try:
        return str(path.relative_to(HELIX_PROJECT_ROOT)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def project_file_exists(relative_path: str) -> bool:
    return (HELIX_PROJECT_ROOT / relative_path).exists()


def should_ignore_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return any(ignored.lower() in parts for ignored in IGNORED_DIRS)


def find_project_files(name_contains: str, limit: int = 20) -> list[str]:
    results: list[str] = []
    needle = name_contains.lower()

    if not HELIX_PROJECT_ROOT.exists():
        return results

    for path in HELIX_PROJECT_ROOT.rglob("*"):
        if len(results) >= limit:
            break

        if should_ignore_path(path):
            continue

        if not path.is_file():
            continue

        relative = safe_relative(path)

        if needle in path.name.lower() or needle in relative.lower():
            results.append(relative)

    return results


def collect_project_snapshot() -> dict[str, Any]:
    known_paths = [
        "backend/main.py",
        "backend/services/web_access_service.py",
        "backend/services/web_advisor_service.py",
        "backend/api/routes/web_routes.py",
        "backend/api/system_routes.py",
        "backend/api/obsidian_routes.py",
        "backend/api/memory_routes.py",
        "backend/api/voice_routes.py",
        "backend/schemas/chat_schema.py",
        "backend/schemas/web_schema.py",
        "backend/schemas/app_schema.py",
        "backend/core/command_executor.py",
        "backend/services/chat_service.py",
        "frontend/index.html",
        "frontend/script.js",
        "frontend/style.css",
    ]

    existing = [
        path for path in known_paths
        if project_file_exists(path)
    ]

    missing = [
        path for path in known_paths
        if not project_file_exists(path)
    ]

    route_files = find_project_files("routes", limit=25)
    schema_files = find_project_files("schema", limit=25)
    service_files = find_project_files("service", limit=30)

    return {
        "root": str(HELIX_PROJECT_ROOT),
        "exists": HELIX_PROJECT_ROOT.exists(),
        "known_existing": existing,
        "known_missing": missing,
        "route_files": route_files,
        "schema_files": schema_files,
        "service_files": service_files,
    }


def format_file_list(title: str, items: list[str], max_items: int = 8) -> str:
    if not items:
        return f"{title}\n- Nenhum arquivo encontrado.\n"

    response = f"{title}\n"

    for item in items[:max_items]:
        response += f"- `{item}`\n"

    if len(items) > max_items:
        response += f"- ...mais {len(items) - max_items} arquivo(s)\n"

    return response


def build_source_context(query: str) -> dict[str, Any]:
    results = fetch_web_search_results(query)

    if not results:
        return {
            "ok": False,
            "query": query,
            "results": [],
            "best": None,
            "summary": [],
            "reason": "Nenhum resultado útil encontrado.",
        }

    ranked_results = rank_web_search_results(query, results)
    best = ranked_results[0]
    page_result = fetch_page_text(best.url)

    if not page_result.ok:
        return {
            "ok": False,
            "query": query,
            "results": ranked_results,
            "best": best,
            "summary": [],
            "reason": page_result.reason,
        }

    summary = build_practical_summary(
        page_result.text or "",
        page_result.domain,
        max_items=5,
    )

    return {
        "ok": True,
        "query": query,
        "results": ranked_results,
        "best": best,
        "summary": summary,
        "reason": None,
    }


def web_result_to_line(result: WebSearchResult) -> str:
    return f"**{result.title}** — `{result.domain or 'desconhecido'}`\n  URL: `{result.url}`"


def build_basemodel_advice(snapshot: dict[str, Any]) -> str:
    has_web_routes = "backend/api/routes/web_routes.py" in snapshot["known_existing"]
    has_chat_schema = "backend/schemas/chat_schema.py" in snapshot["known_existing"]
    has_web_schema = "backend/schemas/web_schema.py" in snapshot["known_existing"]

    response = "Minha opinião para o Helix:\n"
    response += (
        "- Sim, vale usar `BaseModel`, mas não espalhado de qualquer jeito.\n"
        "- O melhor caminho é concentrar os modelos de entrada/saída em `backend/schemas/`.\n"
        "- As rotas devem importar schemas prontos, e não ficar acumulando classe de payload dentro do arquivo de rota.\n"
    )

    response += "\nOnde eu mexeria primeiro:\n"

    if has_web_routes:
        response += "- `backend/api/routes/web_routes.py` — hoje é o primeiro candidato, porque já tem payloads de `/web/search`, `/web/summary`, `/web/explain` e `/web/ask`.\n"
    else:
        response += "- Eu criaria/validaria primeiro a rota web, porque o bloco de internet é o foco atual.\n"

    if has_web_schema:
        response += "- `backend/schemas/web_schema.py` — já existe, então eu moveria/organizaria ali os modelos web.\n"
    else:
        response += "- `backend/schemas/web_schema.py` — eu criaria esse arquivo para `WebReadRequest`, `WebSearchRequest`, `WebExplainRequest` e `WebAskRequest`.\n"

    if has_chat_schema:
        response += "- `backend/schemas/chat_schema.py` — manteria o `ChatRequest` separado, sem misturar com schemas web.\n"

    response += "\nEstrutura que eu seguiria:\n"
    response += (
        "```text\n"
        "backend/\n"
        "  api/\n"
        "    routes/\n"
        "      web_routes.py        # só endpoints e chamadas ao service\n"
        "  schemas/\n"
        "    chat_schema.py        # ChatRequest e payloads do chat\n"
        "    web_schema.py         # WebReadRequest, WebSearchRequest, WebAskRequest\n"
        "  services/\n"
        "    web_access_service.py # motor de busca/leitura/resumo\n"
        "    web_advisor_service.py# opinião web + projeto\n"
        "```\n"
    )

    response += "\nComo ficaria na prática:\n"
    response += (
        "- `web_schema.py` teria os `BaseModel`.\n"
        "- `web_routes.py` importaria esses modelos.\n"
        "- `web_access_service.py` continuaria sem depender de FastAPI, só regra de negócio.\n"
        "- Isso deixa o backend mais limpo e testável.\n"
    )

    response += "\nCaminho que eu recomendo:\n"
    response += (
        "1. Não refatorar tudo de uma vez.\n"
        "2. Começar movendo só os schemas web para `backend/schemas/web_schema.py`.\n"
        "3. Rodar `py_compile`.\n"
        "4. Testar `/web/health`, `/web/ask`, `/chat`.\n"
        "5. Só depois pensar em schemas de response mais completos.\n"
    )

    return response


def build_fastapi_router_advice(snapshot: dict[str, Any]) -> str:
    response = "Minha opinião para o Helix:\n"
    response += (
        "- Sim, faz sentido usar `APIRouter` de forma cada vez mais organizada.\n"
        "- Seu projeto já está indo nessa direção, principalmente com `/web` separado.\n"
        "- O objetivo não é criar mil arquivos por estética, é separar módulos que têm responsabilidades diferentes.\n"
    )

    response += "\nOnde eu mexeria:\n"
    response += (
        "- `backend/main.py` — deve continuar só registrando routers e configurando app/middlewares.\n"
        "- `backend/api/routes/web_routes.py` — rotas web.\n"
        "- `backend/api/system_routes.py` — status e sistema.\n"
        "- `backend/api/memory_routes.py` — memória.\n"
        "- `backend/api/voice_routes.py` — voz/TTS/STT.\n"
        "- `backend/api/obsidian_routes.py` — Obsidian.\n"
    )

    response += "\nEstrutura sugerida:\n"
    response += (
        "```text\n"
        "backend/\n"
        "  main.py\n"
        "  api/\n"
        "    routes/\n"
        "      web_routes.py\n"
        "      chat_routes.py       # futuro: mover /chat para cá\n"
        "      system_routes.py\n"
        "      memory_routes.py\n"
        "      voice_routes.py\n"
        "      obsidian_routes.py\n"
        "      app_registry_routes.py\n"
        "```\n"
    )

    response += "\nMinha recomendação:\n"
    response += (
        "- Não mexeria no `/chat` agora se ele está estável.\n"
        "- Primeiro consolidaria `/web`.\n"
        "- Depois, quando a poeira baixar, moveria o endpoint `/chat` de `main.py` para `chat_routes.py`.\n"
        "- Isso deixa o `main.py` menos inchado, sem quebrar o fluxo atual.\n"
    )

    return response


def build_pathlib_advice(snapshot: dict[str, Any]) -> str:
    response = "Minha opinião para o Helix:\n"
    response += (
        "- Sim, `pathlib` combina muito com o Helix.\n"
        "- O projeto mexe com arquivos, pastas, scanners, Obsidian Vault, frontend estático e comandos locais.\n"
        "- Usar `Path` reduz gambiarra com string de caminho no Windows. E Windows com caminho em string já é uma pequena punição divina.\n"
    )

    response += "\nOnde eu aplicaria:\n"
    response += (
        "- Serviços de leitura de projeto.\n"
        "- Scanner de apps/processos.\n"
        "- Integração com Obsidian.\n"
        "- Manipulação do frontend estático no `main.py`.\n"
        "- Qualquer lugar com `D:\\Helix`, `C:\\Users\\...`, `os.path.join` ou concatenação manual de caminho.\n"
    )

    response += "\nRegra prática:\n"
    response += (
        "- Dentro do backend: use `Path`.\n"
        "- Na API/resposta JSON: converta para `str`.\n"
        "- Nunca devolva objeto `Path` cru em response.\n"
    )

    return response


def build_react_hooks_advice(snapshot: dict[str, Any]) -> str:
    response = "Minha opinião para o Helix:\n"
    response += (
        "- React hooks fariam sentido principalmente quando você reconstruir o frontend em React.\n"
        "- Para o frontend atual em HTML/CSS/JS puro, não vale forçar isso agora.\n"
        "- Quando migrar, hooks podem separar bem chat, voz, orb, sistema e web.\n"
    )

    response += "\nEstrutura futura que eu usaria:\n"
    response += (
        "```text\n"
        "frontend/\n"
        "  src/\n"
        "    hooks/\n"
        "      useHelixChat.ts\n"
        "      useWebAsk.ts\n"
        "      useSystemStatus.ts\n"
        "      useVoiceMode.ts\n"
        "    components/\n"
        "      CommandCenter.tsx\n"
        "      WebPanel.tsx\n"
        "      SystemPanel.tsx\n"
        "      OrbCore.tsx\n"
        "```\n"
    )

    response += "\nMinha recomendação:\n"
    response += (
        "- Não migrar o frontend agora só por causa disso.\n"
        "- Guardar essa arquitetura para a reconstrução visual do Helix.\n"
        "- No momento, o foco certo continua sendo web access no backend.\n"
    )

    return response


def build_generic_project_advice(query: str, snapshot: dict[str, Any]) -> str:
    response = "Minha opinião para o Helix:\n"
    response += (
        "- A ideia parece útil, mas eu não aplicaria direto sem transformar em uma mudança pequena e testável.\n"
        "- O Helix já tem bastante módulo crescendo ao mesmo tempo, então a regra é: uma melhoria por camada.\n"
    )

    response += "\nEu começaria olhando estes pontos do projeto:\n"
    response += format_file_list("- Arquivos de serviço encontrados:", snapshot.get("service_files", []), max_items=6)
    response += "\n"
    response += format_file_list("- Arquivos de rota encontrados:", snapshot.get("route_files", []), max_items=6)
    response += "\n"

    response += "Caminho recomendado:\n"
    response += (
        "1. Definir se isso é schema, rota, service ou frontend.\n"
        "2. Criar um arquivo pequeno ou função isolada.\n"
        "3. Integrar no `/chat` ou `/web` só depois do teste direto.\n"
        "4. Commitar em bloco pequeno.\n"
    )

    return response


def build_topic_advice(query: str, snapshot: dict[str, Any]) -> str:
    query_lower = query.lower()

    if "pydantic" in query_lower or "basemodel" in query_lower:
        return build_basemodel_advice(snapshot)

    if "fastapi" in query_lower and ("router" in query_lower or "apirouter" in query_lower):
        return build_fastapi_router_advice(snapshot)

    if "pathlib" in query_lower:
        return build_pathlib_advice(snapshot)

    if "react" in query_lower and "hook" in query_lower:
        return build_react_hooks_advice(snapshot)

    return build_generic_project_advice(query, snapshot)


def build_web_project_advisor_response(message: str) -> str | None:
    if not is_web_advisor_intent(message):
        return None

    query = clean_advisor_query(message)

    if not query:
        return "Entendi que você quer uma opinião técnica usando web + projeto, mas não achei o tema da pesquisa."

    source_context = build_source_context(query)
    snapshot = collect_project_snapshot()

    response = (
        "Pesquisei na web e analisei isso pensando no projeto Helix.\n\n"
        f"Tema: `{query}`\n"
    )

    if source_context["best"]:
        best = source_context["best"]
        source_type = get_source_type(query, best.domain)

        response += (
            f"Fonte principal: **{best.title}**\n"
            f"Tipo de fonte: {source_type}\n"
            f"Domínio: `{best.domain or 'desconhecido'}`\n"
            f"URL: `{best.url}`\n\n"
        )

    if source_context["summary"]:
        response += "O que a fonte indica, em resumo:\n"

        for item in source_context["summary"][:4]:
            response += f"- {item}\n"

        response += "\n"

    response += "Contexto real do projeto que considerei:\n"
    response += f"- Raiz detectada: `{snapshot['root']}`\n"

    if snapshot["known_existing"]:
        response += "- Arquivos relevantes encontrados:\n"

        for path in snapshot["known_existing"][:8]:
            response += f"  - `{path}`\n"

    response += "\n"
    response += build_topic_advice(query, snapshot)

    if source_context["results"]:
        response += "\n\nOutras fontes encontradas:\n"

        for index, result in enumerate(source_context["results"][1:4], start=1):
            response += f"{index}. {web_result_to_line(result)}\n"

    return response.strip()