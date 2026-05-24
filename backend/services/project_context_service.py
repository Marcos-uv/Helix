from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================
# Helix Project Context Service
# ------------------------------------------------------------
# Objetivo:
# - Dar ao Helix uma forma real de entender projetos locais.
# - Deixar explícito que D:\Helix é o projeto/código da própria Helix.
# - Permitir analisar qualquer pasta informada pelo usuário.
# - Evitar leitura de pastas pesadas/sensíveis por padrão.
# ============================================================


HELIX_PROJECT_ROOT = Path(
    os.environ.get("HELIX_PROJECT_ROOT", r"D:\Helix")
).resolve()


KNOWN_PROJECTS: dict[str, dict[str, Any]] = {
    "helix": {
        "name": "Helix",
        "path": str(HELIX_PROJECT_ROOT),
        "description": (
            "Projeto principal da assistente Helix. "
            "Esta pasta representa o próprio sistema/código da Helix."
        ),
        "is_self": True,
        "aliases": [
            "helix",
            "a helix",
            "projeto helix",
            "seu projeto",
            "sua pasta",
            "seu código",
            "seu codigo",
            "você",
            "voce",
            "seu corpo",
            "seu sistema",
        ],
    }
}


IGNORED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    "htmlcov",
    "target",
    "bin",
    "obj",
    "logs",
    "log",
    "tmp",
    "temp",
    "cache",
    ".cache",
}


IGNORED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "secrets.json",
    "secret.json",
    "credentials.json",
    "token.json",
    "known_apps.json",  # pode ficar grande e é cache operacional
}


TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".env.example",
    ".bat",
    ".ps1",
    ".sh",
    ".sql",
    ".xml",
    ".gitignore",
    ".dockerfile",
}


IMPORTANT_FILE_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "manage.py",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "vite.config.js",
    "vite.config.ts",
    "next.config.js",
    "README.md",
    "readme.md",
    ".gitignore",
    "docker-compose.yml",
    "Dockerfile",
}


MAX_FILE_READ_CHARS = 20_000
MAX_STRUCTURE_ITEMS = 350
MAX_RECENT_FILES = 30
MAX_PROJECT_SEARCH_RESULTS = 50
MAX_LINE_MATCHES_PER_FILE = 5
MAX_SEARCH_FILE_BYTES = 1_000_000


@dataclass
class ProjectResolution:
    name: str
    path: Path
    description: str = ""
    is_self: bool = False
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "description": self.description,
            "is_self": self.is_self,
            "source": self.source,
            "exists": self.path.exists(),
        }


# ============================================================
# Normalização / Segurança de caminho
# ============================================================


def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value



def extract_windows_path(message: str) -> str | None:
    """Extrai caminhos Windows do texto, ex: D:\Helix ou D:/Helix."""
    patterns = [
        r"[a-zA-Z]:\\[^\n\r<>|?*]+",
        r"[a-zA-Z]:/[^\n\r<>|?*]+",
    ]

    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            path = match.group(0).strip().strip('"').strip("'")
            return path

    return None



def safe_resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()



def is_ignored_dir(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return any(ignored.lower() in parts for ignored in IGNORED_DIRS)



def is_sensitive_file(path: Path) -> bool:
    name = path.name.lower()

    if name in {item.lower() for item in IGNORED_FILE_NAMES}:
        return True

    if name.startswith(".env") and name != ".env.example":
        return True

    secret_keywords = [
        "secret",
        "credential",
        "credentials",
        "token",
        "apikey",
        "api_key",
        "private_key",
        "password",
    ]

    return any(keyword in name for keyword in secret_keywords)



def is_text_like_file(path: Path) -> bool:
    if path.name in IMPORTANT_FILE_NAMES:
        return True

    suffix = path.suffix.lower()

    if suffix in TEXT_EXTENSIONS:
        return True

    # arquivos sem extensão muito comuns em projetos
    if path.name.lower() in {"dockerfile", "makefile", "license"}:
        return True

    return False


# ============================================================
# Resolução de projeto
# ============================================================


def get_known_projects() -> list[dict[str, Any]]:
    projects = []

    for key, data in KNOWN_PROJECTS.items():
        path = Path(data["path"])
        projects.append(
            {
                "key": key,
                "name": data.get("name", key),
                "path": str(path),
                "description": data.get("description", ""),
                "is_self": bool(data.get("is_self", False)),
                "exists": path.exists(),
                "aliases": data.get("aliases", []),
            }
        )

    return projects



def resolve_project_reference(message: str | None = None, path: str | None = None) -> ProjectResolution:
    """
    Resolve qual projeto deve ser analisado.

    Prioridade:
    1. Caminho explícito informado.
    2. Caminho dentro da mensagem.
    3. Referências a Helix/seu projeto/sua pasta.
    4. Fallback: Helix.
    """
    if path:
        resolved = safe_resolve_path(path)
        return ProjectResolution(
            name=resolved.name or str(resolved),
            path=resolved,
            description="Projeto/pasta informado explicitamente pelo usuário.",
            is_self=resolved == HELIX_PROJECT_ROOT,
            source="explicit_path",
        )

    message = message or ""
    explicit_path = extract_windows_path(message)

    if explicit_path:
        resolved = safe_resolve_path(explicit_path)
        return ProjectResolution(
            name=resolved.name or str(resolved),
            path=resolved,
            description="Projeto/pasta detectado na mensagem do usuário.",
            is_self=resolved == HELIX_PROJECT_ROOT,
            source="message_path",
        )

    text = normalize_text(message)

    for key, data in KNOWN_PROJECTS.items():
        aliases = [normalize_text(alias) for alias in data.get("aliases", [])]

        if key in text or any(alias in text for alias in aliases):
            resolved = safe_resolve_path(data["path"])
            return ProjectResolution(
                name=data.get("name", key),
                path=resolved,
                description=data.get("description", ""),
                is_self=bool(data.get("is_self", False)),
                source="known_project",
            )

    # Fallback intencional: quando o usuário fala de projeto de forma vaga,
    # usamos Helix, porque este serviço nasceu para dar contexto ao próprio Helix.
    data = KNOWN_PROJECTS["helix"]
    return ProjectResolution(
        name=data["name"],
        path=safe_resolve_path(data["path"]),
        description=data["description"],
        is_self=True,
        source="fallback_helix",
    )


# ============================================================
# Scanner de estrutura
# ============================================================


def detect_project_technologies(root: Path) -> list[str]:
    technologies: set[str] = set()

    checks = {
        "Python": ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py"],
        "FastAPI": ["main.py"],
        "Django": ["manage.py"],
        "Node.js": ["package.json"],
        "React/Vite": ["vite.config.js", "vite.config.ts"],
        "Next.js": ["next.config.js", "next.config.ts"],
        "Docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
        "PostgreSQL/SQL": [],
    }

    for tech, files in checks.items():
        for file_name in files:
            if (root / file_name).exists():
                technologies.add(tech)

    # Heurísticas adicionais leves
    if (root / "backend").exists():
        technologies.add("Backend")

    if (root / "frontend").exists():
        technologies.add("Frontend")

    if any(root.rglob("*.sql")):
        technologies.add("PostgreSQL/SQL")

    return sorted(technologies)



def find_important_files(root: Path, limit: int = 80) -> list[dict[str, Any]]:
    important: list[dict[str, Any]] = []

    if not root.exists() or not root.is_dir():
        return important

    for path in root.rglob("*"):
        if len(important) >= limit:
            break

        if not path.is_file():
            continue

        if is_ignored_dir(path.parent):
            continue

        if is_sensitive_file(path):
            continue

        if path.name in IMPORTANT_FILE_NAMES or path.suffix.lower() in {".py", ".js", ".ts", ".html", ".css", ".md"}:
            try:
                stat = path.stat()
                important.append(
                    {
                        "name": path.name,
                        "relative_path": str(path.relative_to(root)),
                        "size_kb": round(stat.st_size / 1024, 2),
                        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    }
                )
            except OSError:
                continue

    return important



def scan_project_structure(
    project_path: str | Path,
    max_depth: int = 4,
    max_items: int = MAX_STRUCTURE_ITEMS,
) -> dict[str, Any]:
    root = safe_resolve_path(project_path)

    if not root.exists():
        return {
            "status": "error",
            "reason": "path_not_found",
            "path": str(root),
            "message": "O caminho do projeto não existe.",
        }

    if not root.is_dir():
        return {
            "status": "error",
            "reason": "not_a_directory",
            "path": str(root),
            "message": "O caminho informado não é uma pasta.",
        }

    items: list[dict[str, Any]] = []
    ignored_count = 0
    file_count = 0
    dir_count = 0

    base_depth = len(root.parts)

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.parts) - base_depth

        # Remove diretórios ignorados antes do walk entrar neles.
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_DIRS]

        if depth > max_depth:
            dirs[:] = []
            continue

        if is_ignored_dir(current_path):
            ignored_count += 1
            dirs[:] = []
            continue

        if len(items) >= max_items:
            break

        if current_path != root:
            try:
                items.append(
                    {
                        "type": "dir",
                        "relative_path": str(current_path.relative_to(root)),
                        "depth": depth,
                    }
                )
                dir_count += 1
            except ValueError:
                pass

        for file_name in files:
            if len(items) >= max_items:
                break

            file_path = current_path / file_name

            if is_sensitive_file(file_path):
                ignored_count += 1
                continue

            try:
                stat = file_path.stat()
                items.append(
                    {
                        "type": "file",
                        "relative_path": str(file_path.relative_to(root)),
                        "depth": depth + 1,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                        "is_text": is_text_like_file(file_path),
                        "is_important": file_path.name in IMPORTANT_FILE_NAMES,
                    }
                )
                file_count += 1
            except OSError:
                ignored_count += 1

    technologies = detect_project_technologies(root)
    important_files = find_important_files(root)

    return {
        "status": "ok",
        "path": str(root),
        "name": root.name,
        "technologies": technologies,
        "items": items,
        "counts": {
            "items_returned": len(items),
            "files_seen": file_count,
            "dirs_seen": dir_count,
            "ignored": ignored_count,
        },
        "important_files": important_files[:30],
        "truncated": len(items) >= max_items,
    }



def build_tree_text(items: list[dict[str, Any]], max_lines: int = 120) -> str:
    lines: list[str] = []

    for item in items[:max_lines]:
        depth = int(item.get("depth", 0))
        indent = "  " * max(depth - 1, 0)
        icon = "📁" if item.get("type") == "dir" else "📄"
        rel = item.get("relative_path", "")
        lines.append(f"{indent}{icon} {rel}")

    if len(items) > max_lines:
        lines.append(f"... e mais {len(items) - max_lines} item(ns).")

    return "\n".join(lines)



def build_project_structure_response(message: str | None = None, path: str | None = None) -> str:
    project = resolve_project_reference(message=message, path=path)
    scan = scan_project_structure(project.path)

    if scan.get("status") != "ok":
        return (
            "Não consegui analisar esse projeto.\n\n"
            f"- Caminho: `{scan.get('path')}`\n"
            f"- Motivo: {scan.get('message') or scan.get('reason')}"
        )

    technologies = ", ".join(scan.get("technologies", [])) or "não detectadas"
    counts = scan.get("counts", {})
    important_files = scan.get("important_files", [])

    response = "## Visão do projeto\n\n"
    response += f"- Projeto: **{project.name}**\n"
    response += f"- Caminho: `{project.path}`\n"

    if project.is_self:
        response += "- Identidade: esta pasta é o próprio projeto/corpo da Helix.\n"

    response += f"- Fonte da resolução: `{project.source}`\n"
    response += f"- Tecnologias detectadas: {technologies}\n"
    response += f"- Arquivos listados: `{counts.get('files_seen', 0)}`\n"
    response += f"- Pastas listadas: `{counts.get('dirs_seen', 0)}`\n"
    response += f"- Ignorados por segurança/performance: `{counts.get('ignored', 0)}`\n"

    if scan.get("truncated"):
        response += "- Observação: a listagem foi truncada para evitar resposta gigante.\n"

    if important_files:
        response += "\n## Arquivos importantes detectados\n\n"
        for item in important_files[:20]:
            response += f"- `{item.get('relative_path')}` — {item.get('size_kb')} KB\n"

    response += "\n## Estrutura resumida\n\n"
    response += "```text\n"
    response += build_tree_text(scan.get("items", []), max_lines=90)
    response += "\n```"

    return response.strip()


# ============================================================
# Leitura de arquivos
# ============================================================


def find_file_in_project(project_path: str | Path, file_query: str, limit: int = 20) -> list[dict[str, Any]]:
    root = safe_resolve_path(project_path)
    query = normalize_text(file_query)

    if not root.exists() or not root.is_dir():
        return []

    matches: list[dict[str, Any]] = []

    for path in root.rglob("*"):
        if len(matches) >= limit:
            break

        if not path.is_file():
            continue

        if is_ignored_dir(path.parent) or is_sensitive_file(path):
            continue

        rel = str(path.relative_to(root))
        name = path.name

        normalized_name = normalize_text(name)
        normalized_rel = normalize_text(rel)

        if query == normalized_name or query in normalized_name or query in normalized_rel:
            try:
                stat = path.stat()
                matches.append(
                    {
                        "name": name,
                        "relative_path": rel,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                        "is_text": is_text_like_file(path),
                    }
                )
            except OSError:
                continue

    return matches



def read_project_file(
    project_path: str | Path,
    relative_path: str,
    max_chars: int = MAX_FILE_READ_CHARS,
) -> dict[str, Any]:
    root = safe_resolve_path(project_path)
    target = safe_resolve_path(root / relative_path)

    # Segurança: impede escapar da pasta do projeto com ..
    try:
        target.relative_to(root)
    except ValueError:
        return {
            "status": "error",
            "reason": "outside_project",
            "message": "O arquivo solicitado está fora da pasta do projeto.",
        }

    if not target.exists():
        return {
            "status": "error",
            "reason": "file_not_found",
            "message": "Arquivo não encontrado.",
            "path": str(target),
        }

    if not target.is_file():
        return {
            "status": "error",
            "reason": "not_a_file",
            "message": "O caminho encontrado não é um arquivo.",
            "path": str(target),
        }

    if is_sensitive_file(target):
        return {
            "status": "error",
            "reason": "sensitive_file",
            "message": "Arquivo sensível bloqueado por segurança.",
            "path": str(target),
        }

    if not is_text_like_file(target):
        return {
            "status": "error",
            "reason": "unsupported_file_type",
            "message": "Não vou ler esse tipo de arquivo como texto por padrão.",
            "path": str(target),
        }

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars
        content = content[:max_chars]
        stat = target.stat()

        return {
            "status": "ok",
            "path": str(target),
            "relative_path": str(target.relative_to(root)),
            "size_kb": round(stat.st_size / 1024, 2),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "content": content,
            "truncated": truncated,
        }

    except OSError as exc:
        return {
            "status": "error",
            "reason": "read_error",
            "message": str(exc),
            "path": str(target),
        }



def extract_file_reference(message: str) -> str | None:
    text = message.strip()
    lowered = normalize_text(text)

    # Casos comuns: "main", "main.py", "o que tem no main"
    if "main.py" in lowered or re.search(r"\bmain\b", lowered):
        return "main.py"

    patterns = [
        r"arquivo\s+([\w\-.\\/]+)",
        r"dentro do\s+([\w\-.\\/]+)",
        r"no\s+([\w\-.\\/]+\.\w+)",
        r"ler\s+([\w\-.\\/]+\.\w+)",
        r"leia\s+([\w\-.\\/]+\.\w+)",
        r"abre\s+([\w\-.\\/]+\.\w+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return match.group(1).strip()

    return None



def build_project_file_response(message: str, path: str | None = None) -> str:
    project = resolve_project_reference(message=message, path=path)
    file_ref = extract_file_reference(message)

    if not file_ref:
        return (
            "Entendi que você quer olhar um arquivo do projeto, mas não identifiquei qual.\n\n"
            "Exemplos:\n"
            "- `o que tem no main.py?`\n"
            "- `leia backend/main.py`\n"
            "- `mostra o arquivo backend/services/chat_service.py`"
        )

    matches = find_file_in_project(project.path, file_ref)

    if not matches:
        return (
            f"Não encontrei `{file_ref}` dentro de `{project.path}`.\n\n"
            "Talvez o arquivo esteja em outro caminho ou com outro nome."
        )

    # Preferência: se pediu main.py, tenta backend/main.py primeiro, depois main.py.
    chosen = matches[0]

    if file_ref.lower() == "main.py":
        for item in matches:
            rel = item.get("relative_path", "").replace("\\", "/").lower()
            if rel.endswith("backend/main.py"):
                chosen = item
                break

    if len(matches) > 1 and file_ref.lower() != "main.py":
        options = "\n".join(f"- `{item.get('relative_path')}`" for item in matches[:10])
        return (
            f"Encontrei mais de um arquivo parecido com `{file_ref}` em **{project.name}**.\n\n"
            f"{options}\n\n"
            "Me diga o caminho exato para eu ler sem chutar."
        )

    read = read_project_file(project.path, chosen["relative_path"])

    if read.get("status") != "ok":
        return (
            "Não consegui ler o arquivo.\n\n"
            f"- Arquivo: `{chosen.get('relative_path')}`\n"
            f"- Motivo: {read.get('message') or read.get('reason')}"
        )

    content = read.get("content", "")
    truncated_note = "\n\n> Observação: conteúdo truncado por segurança/tamanho." if read.get("truncated") else ""

    summary = summarize_code_content(chosen["relative_path"], content)

    response = f"## Arquivo lido: `{read.get('relative_path')}`\n\n"
    response += f"- Projeto: **{project.name}**\n"
    response += f"- Caminho: `{read.get('path')}`\n"
    response += f"- Tamanho: `{read.get('size_kb')} KB`\n"
    response += f"- Modificado em: `{read.get('modified_at')}`\n"

    response += "\n## Leitura rápida\n\n"
    response += summary

    response += "\n\n## Trecho inicial\n\n"
    response += "```text\n"
    response += content[:5000]
    response += "\n```"
    response += truncated_note

    return response.strip()



def resolve_requested_project_file(message: str, path: str | None = None) -> dict[str, Any]:
    """Resolve a referência de arquivo pedida pelo usuário e lê o arquivo real.

    Usado tanto para leitura simples quanto para análise/opinião. Mantém a mesma
    regra de preferência: se o usuário disser `main`, preferimos `backend/main.py`.
    """
    project = resolve_project_reference(message=message, path=path)
    file_ref = extract_file_reference(message)

    if not file_ref:
        return {
            "status": "error",
            "reason": "file_ref_not_found",
            "message": "Não identifiquei qual arquivo do projeto você quer analisar.",
            "project": project,
        }

    matches = find_file_in_project(project.path, file_ref)

    if not matches:
        return {
            "status": "error",
            "reason": "file_not_found",
            "message": f"Não encontrei `{file_ref}` dentro de `{project.path}`.",
            "project": project,
            "file_ref": file_ref,
        }

    chosen = matches[0]

    if file_ref.lower() == "main.py":
        for item in matches:
            rel = item.get("relative_path", "").replace("\\", "/").lower()
            if rel.endswith("backend/main.py"):
                chosen = item
                break

    if len(matches) > 1 and file_ref.lower() != "main.py":
        return {
            "status": "multiple_matches",
            "project": project,
            "file_ref": file_ref,
            "matches": matches[:10],
        }

    read = read_project_file(project.path, chosen["relative_path"])

    if read.get("status") != "ok":
        return {
            "status": "error",
            "reason": read.get("reason"),
            "message": read.get("message"),
            "project": project,
            "file_ref": file_ref,
            "chosen": chosen,
            "read": read,
        }

    return {
        "status": "ok",
        "project": project,
        "file_ref": file_ref,
        "chosen": chosen,
        "read": read,
    }


def analyze_python_code_quality(relative_path: str, content: str) -> dict[str, Any]:
    """Faz uma análise heurística simples do código Python sem depender da IA."""
    lines = content.splitlines()
    stripped_lines = [line.strip() for line in lines]

    imports = [line for line in stripped_lines if line.startswith(("import ", "from "))]
    functions = [line for line in stripped_lines if line.startswith(("def ", "async def "))]
    classes = [line for line in stripped_lines if line.startswith("class ")]
    routes = [line for line in stripped_lines if line.startswith(("@app.", "@router."))]

    has_fastapi_app = "FastAPI(" in content
    has_middleware = "add_middleware" in content
    has_static_files = "StaticFiles" in content or "app.mount" in content
    has_db_dependency = "Depends(get_db)" in content or "Session = Depends" in content
    has_try_except = "try:" in content and "except" in content
    has_traceback = "traceback" in content
    has_large_prompt = "SYSTEM_PROMPT" in content and len(content) > 8000
    has_business_logic = len(functions) >= 5 or len(routes) >= 5
    has_direct_provider_call = "get_provider" in content or "generate_response" in content
    has_router_include = "include_router" in content

    strengths: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    if has_fastapi_app:
        strengths.append("O arquivo configura claramente uma aplicação FastAPI.")
    if has_middleware:
        strengths.append("Há configuração de middleware, o que indica preocupação com comportamento global da API.")
    if has_static_files:
        strengths.append("O frontend está sendo servido pelo backend, útil para desenvolvimento local.")
    if has_db_dependency:
        strengths.append("As rotas usam dependência de banco, mantendo o acesso ao DB integrado ao FastAPI.")
    if routes:
        strengths.append(f"As rotas principais estão declaradas de forma visível (`{len(routes)}` decorator(s) detectado(s)).")

    if len(lines) > 220:
        warnings.append("O arquivo está começando a ficar grande para um ponto de entrada. Pode virar um 'main.py faz-tudo'.")
    if has_large_prompt:
        warnings.append("Existe prompt grande ou lógica de conversa dentro do arquivo; isso costuma ficar melhor em service/config separado.")
    if has_business_logic and has_direct_provider_call:
        warnings.append("O arquivo mistura entrada da API com regra de negócio/chamada de IA. Funciona, mas reduz manutenção.")
    if has_try_except and has_traceback:
        warnings.append("Há tratamento amplo de erro com traceback. Bom para debug, mas em produção precisa resposta mais controlada/logging melhor.")
    if not has_router_include and len(routes) >= 5:
        warnings.append("Várias rotas estão concentradas no main.py. É melhor dividir por routers quando o projeto cresce.")

    if not warnings:
        warnings.append("Não vi sinais graves pelo scanner heurístico. Mesmo assim, vale revisar organização por camadas.")

    suggestions.append("Manter o `main.py` como ponto de montagem da aplicação: app, middlewares, routers e startup.")
    suggestions.append("Mover lógica pesada para `backend/services/` e contratos para `backend/schemas/`.")
    suggestions.append("Separar rotas por domínio em `backend/api/`, por exemplo chat, system, voice, apps e projects.")
    suggestions.append("Evitar prompts longos e regras complexas direto no main; deixar isso em serviços/configurações.")

    if "main.py" in relative_path.replace("\\", "/").lower():
        suggestions.append("Para o Helix, o ideal é o `backend/main.py` virar só o painel de entrada, não o cérebro inteiro.")

    score = 80
    score -= max(0, len(lines) - 180) // 20 * 3
    score -= 8 if has_large_prompt else 0
    score -= 8 if has_business_logic and has_direct_provider_call else 0
    score -= 6 if not has_router_include and len(routes) >= 5 else 0
    score = max(35, min(95, score))

    return {
        "lines": len(lines),
        "imports": len(imports),
        "functions": len(functions),
        "classes": len(classes),
        "routes": len(routes),
        "score": score,
        "strengths": strengths,
        "warnings": warnings,
        "suggestions": suggestions,
    }


def analyze_generic_code_quality(relative_path: str, content: str) -> dict[str, Any]:
    suffix = Path(relative_path).suffix.lower()
    lines = content.splitlines()

    if suffix == ".py":
        return analyze_python_code_quality(relative_path, content)

    strengths = ["Arquivo textual legível e acessível pelo scanner do projeto."]
    warnings = []
    suggestions = ["Revisar organização, responsabilidade do arquivo e tamanho conforme o papel dele no projeto."]

    if len(lines) > 300:
        warnings.append("Arquivo grande; pode estar acumulando responsabilidades demais.")
    else:
        warnings.append("Nenhum alerta estrutural forte detectado pela análise genérica.")

    return {
        "lines": len(lines),
        "imports": 0,
        "functions": 0,
        "classes": 0,
        "routes": 0,
        "score": 75,
        "strengths": strengths,
        "warnings": warnings,
        "suggestions": suggestions,
    }


def build_project_file_analysis_response(message: str, path: str | None = None) -> str:
    resolved = resolve_requested_project_file(message, path=path)

    if resolved.get("status") == "multiple_matches":
        options = "\n".join(f"- `{item.get('relative_path')}`" for item in resolved.get("matches", []))
        return (
            f"Encontrei mais de um arquivo parecido com `{resolved.get('file_ref')}`.\n\n"
            f"{options}\n\n"
            "Me diga o caminho exato para eu opinar sem bancar a vidente de repositório."
        )

    if resolved.get("status") != "ok":
        return (
            "Não consegui analisar o arquivo.\n\n"
            f"- Motivo: {resolved.get('message') or resolved.get('reason')}"
        )

    project = resolved["project"]
    read = resolved["read"]
    relative_path = read.get("relative_path", "arquivo desconhecido")
    content = read.get("content", "")
    analysis = analyze_generic_code_quality(relative_path, content)
    summary = summarize_code_content(relative_path, content)

    response = f"## Minha análise sobre `{relative_path}`\n\n"
    response += f"- Projeto: **{project.name}**\n"
    response += f"- Caminho: `{read.get('path')}`\n"
    response += f"- Tamanho: `{read.get('size_kb')} KB`\n"
    response += f"- Linhas: `{analysis.get('lines')}`\n"
    response += f"- Nota heurística de organização: `{analysis.get('score')}/100`\n\n"

    response += "## O que esse arquivo parece fazer\n\n"
    response += summary + "\n\n"

    response += "## Pontos bons\n\n"
    for item in analysis.get("strengths", [])[:8]:
        response += f"- {item}\n"

    response += "\n## Pontos de atenção\n\n"
    for item in analysis.get("warnings", [])[:8]:
        response += f"- {item}\n"

    response += "\n## Minha opinião direta\n\n"

    score = int(analysis.get("score", 0))
    if score >= 82:
        response += (
            "Está bem encaminhado. Eu manteria a estrutura geral, mas continuaria separando responsabilidades "
            "para o arquivo não virar um painel de controle com síndrome de Deus.\n"
        )
    elif score >= 65:
        response += (
            "Funciona, mas já dá sinais de que precisa ser mantido sob controle. "
            "Não é caso de jogar fora; é caso de extrair responsabilidades aos poucos.\n"
        )
    else:
        response += (
            "Está pesado ou concentrando responsabilidades demais. Eu trataria como candidato a refatoração gradual, "
            "sem sair quebrando tudo com entusiasmo de britadeira.\n"
        )

    response += "\n## Melhorias recomendadas\n\n"
    for item in analysis.get("suggestions", [])[:8]:
        response += f"- {item}\n"

    if read.get("truncated"):
        response += "\n> Observação: a análise usou conteúdo truncado por limite de segurança/tamanho.\n"

    return response.strip()


def summarize_code_content(relative_path: str, content: str) -> str:
    suffix = Path(relative_path).suffix.lower()
    lines = content.splitlines()

    if not content.strip():
        return "O arquivo está vazio. Trágico, porém organizado."

    summary: list[str] = []

    if suffix == ".py":
        imports = [line.strip() for line in lines if line.strip().startswith(("import ", "from "))]
        functions = []
        classes = []
        routes = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                functions.append(stripped)
            elif stripped.startswith("class "):
                classes.append(stripped)
            elif stripped.startswith("@app.") or stripped.startswith("@router."):
                routes.append(stripped)

        summary.append(f"- Linhas: `{len(lines)}`")
        summary.append(f"- Imports detectados: `{len(imports)}`")
        summary.append(f"- Classes detectadas: `{len(classes)}`")
        summary.append(f"- Funções detectadas: `{len(functions)}`")
        summary.append(f"- Rotas/decorators detectados: `{len(routes)}`")

        if routes:
            summary.append("\nRotas/decorators principais:")
            for route in routes[:12]:
                summary.append(f"- `{route}`")

        if functions:
            summary.append("\nFunções principais:")
            for fn in functions[:15]:
                summary.append(f"- `{fn}`")

        if classes:
            summary.append("\nClasses principais:")
            for cls in classes[:10]:
                summary.append(f"- `{cls}`")

        return "\n".join(summary)

    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        functions = [
            line.strip()
            for line in lines
            if "function " in line or "=>" in line or line.strip().startswith("export")
        ]
        summary.append(f"- Linhas: `{len(lines)}`")
        summary.append(f"- Declarações/funções/exportações prováveis: `{len(functions)}`")
        for item in functions[:15]:
            summary.append(f"- `{item[:160]}`")
        return "\n".join(summary)

    if suffix == ".json":
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                keys = ", ".join(list(data.keys())[:20])
                return f"- JSON válido.\n- Chaves principais: {keys}"
            if isinstance(data, list):
                return f"- JSON válido.\n- Lista com `{len(data)}` item(ns)."
        except json.JSONDecodeError:
            return "- Parece JSON, mas não consegui validar o conteúdo."

    return f"- Linhas: `{len(lines)}`\n- Tipo: `{suffix or 'sem extensão'}`\n- Arquivo textual lido com sucesso."




# ============================================================
# Busca de texto dentro do projeto
# ============================================================


def looks_like_code_symbol(value: str) -> bool:
    """Detecta termos com cara de símbolo/código: SYSTEM_PROMPT, get_provider, main.py etc."""
    value = value.strip()

    if not value:
        return False

    if "`" in value:
        return True

    if re.search(r"\b[A-Z][A-Z0-9_]{2,}\b", value):
        return True

    if re.search(r"\b[a-zA-Z_][\w]*\([^)]*\)", value):
        return True

    if re.search(r"\b[a-zA-Z_][\w]*_[a-zA-Z0-9_]+\b", value):
        return True

    if re.search(r"\b[\w\-/\\]+\.\w+\b", value):
        return True

    return False



def extract_search_query_from_message(message: str) -> str | None:
    """
    Extrai o termo que o usuário quer procurar dentro do projeto.

    Exemplos:
    - "liste os arquivos que tenham SYSTEM_PROMPT" -> SYSTEM_PROMPT
    - "procure `get_provider` no seu código" -> get_provider
    - "onde está handle_web_access_intent?" -> handle_web_access_intent
    """
    original = message.strip()
    lowered = normalize_text(original)

    # Prioridade máxima: texto entre crases.
    backtick = re.search(r"`([^`]{2,120})`", original)
    if backtick:
        return backtick.group(1).strip()

    # Texto entre aspas.
    quoted = re.search(r'"([^"]{2,120})"', original) or re.search(r"'([^']{2,120})'", original)
    if quoted:
        return quoted.group(1).strip()

    patterns = [
        r"(?:algo como|termo|texto|trecho|string|vari[aá]vel|fun[cç][aã]o|classe)\s+([A-Za-z0-9_\-./\\:]{2,120})",
        r"(?:procure|procurar|busque|buscar|encontre|encontrar)\s+([A-Za-z0-9_\-./\\:]{2,120})",
        r"(?:onde est[aá]|onde fica|em quais arquivos aparece|quais arquivos usam|quais arquivos usa)\s+([A-Za-z0-9_\-./\\:]{2,120})",
        r"(?:tenham|tenha|cont[eé]m|contem|usa|usam)\s+([A-Za-z0-9_\-./\\:]{2,120})",
    ]

    stop_words = {
        "no", "na", "nos", "nas", "em", "dentro", "do", "da", "dos", "das",
        "seu", "sua", "código", "codigo", "projeto", "arquivo", "arquivos",
    }

    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if not match:
            continue

        candidate = match.group(1).strip().strip("?.!,;:")
        candidate_parts = [part for part in candidate.split() if part not in stop_words]
        candidate = " ".join(candidate_parts).strip()

        if candidate:
            # Recupera grafia original quando possível, preservando maiúsculas.
            original_match = re.search(re.escape(candidate), original, flags=re.IGNORECASE)
            if original_match:
                return original_match.group(0).strip().strip("?.!,;:")
            return candidate

    # Fallback: procura tokens com cara de símbolo de código.
    symbol_candidates = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", original)
    ignored = {
        "liste", "lista", "listar", "arquivos", "arquivo", "procure", "busque",
        "encontre", "codigo", "código", "projeto", "helix", "onde", "esta", "está",
        "dentro", "tenha", "tenham", "algo", "como", "isso", "voce", "você",
    }

    for candidate in symbol_candidates:
        if candidate.lower() in ignored:
            continue

        if looks_like_code_symbol(candidate) or "_" in candidate or candidate.isupper():
            return candidate

    return None



def search_text_in_project(
    project_path: str | Path,
    query: str,
    max_results: int = MAX_PROJECT_SEARCH_RESULTS,
) -> dict[str, Any]:
    root = safe_resolve_path(project_path)
    query = query.strip()

    if not root.exists() or not root.is_dir():
        return {
            "status": "error",
            "reason": "project_not_found",
            "message": "A pasta do projeto não existe ou não é uma pasta.",
            "path": str(root),
        }

    if len(query) < 2:
        return {
            "status": "error",
            "reason": "query_too_short",
            "message": "O termo de busca é curto demais.",
            "path": str(root),
        }

    query_lower = query.lower()
    matches: list[dict[str, Any]] = []
    scanned_files = 0
    skipped_files = 0

    for path in root.rglob("*"):
        if len(matches) >= max_results:
            break

        if not path.is_file():
            continue

        if is_ignored_dir(path.parent) or is_sensitive_file(path):
            skipped_files += 1
            continue

        if not is_text_like_file(path):
            skipped_files += 1
            continue

        try:
            stat = path.stat()
            if stat.st_size > MAX_SEARCH_FILE_BYTES:
                skipped_files += 1
                continue

            content = path.read_text(encoding="utf-8", errors="replace")
            scanned_files += 1
        except OSError:
            skipped_files += 1
            continue

        if query_lower not in content.lower():
            continue

        line_matches: list[dict[str, Any]] = []

        for index, line in enumerate(content.splitlines(), start=1):
            if query_lower in line.lower():
                clean_line = line.strip()
                if len(clean_line) > 220:
                    clean_line = clean_line[:220].rstrip() + "..."

                line_matches.append(
                    {
                        "line": index,
                        "content": clean_line,
                    }
                )

            if len(line_matches) >= MAX_LINE_MATCHES_PER_FILE:
                break

        try:
            relative_path = str(path.relative_to(root))
        except ValueError:
            relative_path = str(path)

        matches.append(
            {
                "relative_path": relative_path,
                "size_kb": round(stat.st_size / 1024, 2),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "line_matches": line_matches,
            }
        )

    return {
        "status": "ok",
        "path": str(root),
        "query": query,
        "matches": matches,
        "counts": {
            "matches": len(matches),
            "scanned_files": scanned_files,
            "skipped_files": skipped_files,
        },
        "truncated": len(matches) >= max_results,
    }



def build_project_text_search_response(message: str, path: str | None = None) -> str:
    project = resolve_project_reference(message=message, path=path)
    query = extract_search_query_from_message(message)

    if not query:
        return (
            "Entendi que você quer procurar algo no meu código, mas não identifiquei exatamente o termo.\n\n"
            "Exemplos:\n"
            "- `procure SYSTEM_PROMPT no seu código`\n"
            "- `liste os arquivos que usam get_provider`\n"
            "- `onde está handle_web_access_intent?`"
        )

    result = search_text_in_project(project.path, query)

    if result.get("status") != "ok":
        return (
            "Tentei procurar no projeto, mas não consegui concluir a busca.\n\n"
            f"- Projeto: **{project.name}**\n"
            f"- Caminho: `{project.path}`\n"
            f"- Termo: `{query}`\n"
            f"- Motivo: {result.get('message') or result.get('reason')}"
        )

    matches = result.get("matches", [])
    counts = result.get("counts", {})

    if not matches:
        return (
            f"Procurei por `{query}` no projeto **{project.name}**, mas não encontrei nada.\n\n"
            f"- Caminho: `{project.path}`\n"
            f"- Arquivos analisados: `{counts.get('scanned_files', 0)}`\n"
            f"- Arquivos ignorados por segurança/tipo/tamanho: `{counts.get('skipped_files', 0)}`\n\n"
            "Pelo menos agora eu procurei de verdade, não dei aquela resposta de NPC perdido."
        )

    response = f"## Busca no código do projeto\n\n"
    response += f"- Projeto: **{project.name}**\n"
    response += f"- Caminho: `{project.path}`\n"
    response += f"- Termo procurado: `{query}`\n"
    response += f"- Arquivos com ocorrência: `{counts.get('matches', len(matches))}`\n"
    response += f"- Arquivos analisados: `{counts.get('scanned_files', 0)}`\n"
    response += f"- Arquivos ignorados: `{counts.get('skipped_files', 0)}`\n\n"

    response += "## Arquivos encontrados\n\n"

    for item in matches[:25]:
        response += f"- `{item.get('relative_path')}` — {item.get('size_kb')} KB\n"

        for line_match in item.get("line_matches", [])[:MAX_LINE_MATCHES_PER_FILE]:
            line_number = line_match.get("line")
            content = line_match.get("content", "")
            response += f"  - linha {line_number}: `{content}`\n"

    if result.get("truncated") or len(matches) > 25:
        response += "\n> Observação: mostrei os primeiros resultados para não transformar o chat num pergaminho medieval.\n"

    return response.strip()

# ============================================================
# Arquivos recentes
# ============================================================


def list_recent_project_files(project_path: str | Path, limit: int = MAX_RECENT_FILES) -> list[dict[str, Any]]:
    root = safe_resolve_path(project_path)

    if not root.exists() or not root.is_dir():
        return []

    files: list[dict[str, Any]] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if is_ignored_dir(path.parent) or is_sensitive_file(path):
            continue

        if not is_text_like_file(path):
            continue

        try:
            stat = path.stat()
            files.append(
                {
                    "relative_path": str(path.relative_to(root)),
                    "size_kb": round(stat.st_size / 1024, 2),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "mtime": stat.st_mtime,
                }
            )
        except OSError:
            continue

    files.sort(key=lambda item: item["mtime"], reverse=True)

    for item in files:
        item.pop("mtime", None)

    return files[:limit]



def build_recent_project_files_response(message: str | None = None, path: str | None = None) -> str:
    project = resolve_project_reference(message=message, path=path)
    files = list_recent_project_files(project.path)

    if not files:
        return f"Não encontrei arquivos recentes legíveis em `{project.path}`."

    response = f"## Arquivos recentes em {project.name}\n\n"
    response += f"Projeto: `{project.path}`\n\n"

    for item in files:
        response += (
            f"- `{item.get('relative_path')}` — "
            f"{item.get('size_kb')} KB — {item.get('modified_at')}\n"
        )

    return response.strip()


# ============================================================
# Interpretador simples para o chat_service
# ============================================================


def interpret_project_context_intent(message: str) -> dict[str, Any] | None:
    text = normalize_text(message)

    # Busca textual dentro do projeto/código.
    # Precisa vir antes da leitura genérica de arquivo, senão frases como
    # "liste arquivos que tenham SYSTEM_PROMPT" caem no fallback errado.
    search_words = [
        "procure",
        "procurar",
        "busque",
        "buscar",
        "encontre",
        "encontrar",
        "liste",
        "lista",
        "listar",
        "quais arquivos",
        "onde está",
        "onde esta",
        "onde fica",
        "aparece",
        "usam",
        "usa",
        "tenha",
        "tenham",
        "contém",
        "contem",
    ]

    code_context_words = [
        "código",
        "codigo",
        "arquivo",
        "arquivos",
        "projeto",
        "backend",
        "frontend",
        "função",
        "funcao",
        "classe",
        "variável",
        "variavel",
        "string",
        "trecho",
    ]

    has_search_signal = any(word in text for word in search_words)
    has_code_context = any(word in text for word in code_context_words)
    extracted_query = extract_search_query_from_message(message)

    if has_search_signal and (has_code_context or extracted_query or looks_like_code_symbol(message)):
        return {
            "intent": "search_project_text",
            "confidence": 0.95,
            "query": extracted_query,
        }

    opinion_words = [
        "opinião",
        "opiniao",
        "avalia",
        "avaliar",
        "analise crítica",
        "analise critica",
        "o que acha",
        "o que você acha",
        "o que voce acha",
        "está bom",
        "esta bom",
        "ficou bom",
        "vale a pena",
        "melhorias",
        "melhorar",
        "refatorar",
        "refatoração",
        "refatoracao",
    ]

    if ("main.py" in text or re.search(r"\bmain\b", text)) and any(word in text for word in opinion_words):
        return {
            "intent": "analyze_project_file",
            "confidence": 0.95,
            "file_ref": "main.py",
        }

    if "main.py" in text or re.search(r"\bmain\b", text):
        return {
            "intent": "read_project_file",
            "confidence": 0.95,
            "file_ref": "main.py",
        }

    project_words = [
        "projeto",
        "helix",
        "sua pasta",
        "seu código",
        "seu codigo",
        "seu main",
        "main",
        "main.py",
        "backend",
        "frontend",
        "estrutura",
        "arquivos recentes",
        "pasta",
    ]

    action_words = [
        "olha",
        "olhar",
        "analisa",
        "analisar",
        "verifica",
        "verificar",
        "mostra",
        "mostrar",
        "lista",
        "listar",
        "o que tem",
        "como está",
        "como esta",
        "leia",
        "ler",
        "abre",
    ]

    has_project_signal = any(word in text for word in project_words) or extract_windows_path(message)
    has_action_signal = any(word in text for word in action_words)

    if not has_project_signal or not has_action_signal:
        return None

    if "arquivos recentes" in text or "mudaram recentemente" in text or "alterados recentemente" in text:
        return {
            "intent": "recent_project_files",
            "confidence": 0.9,
        }

    if any(word in text for word in opinion_words):
        return {
            "intent": "analyze_project_file",
            "confidence": 0.9,
            "file_ref": extract_file_reference(message),
        }

    if "main" in text or re.search(r"\b[\w\-/\\]+\.\w+\b", text):
        return {
            "intent": "read_project_file",
            "confidence": 0.9,
            "file_ref": extract_file_reference(message),
        }

    if "estrutura" in text or "árvore" in text or "arvore" in text or "o que tem" in text:
        return {
            "intent": "project_structure",
            "confidence": 0.9,
        }

    if "olha" in text or "analisa" in text or "verifica" in text or "como está" in text or "como esta" in text:
        return {
            "intent": "project_structure",
            "confidence": 0.8,
        }

    return None



def handle_project_context_intent(message: str) -> str | None:
    intent = interpret_project_context_intent(message)

    if not intent:
        return None

    action = intent.get("intent")

    if action == "search_project_text":
        return build_project_text_search_response(message)

    if action == "read_project_file":
        return build_project_file_response(message)

    if action == "analyze_project_file":
        return build_project_file_analysis_response(message)

    if action == "recent_project_files":
        return build_recent_project_files_response(message)

    if action == "project_structure":
        return build_project_structure_response(message)

    return None
