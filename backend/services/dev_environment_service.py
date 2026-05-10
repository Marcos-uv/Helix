import json
import os
import subprocess
from pathlib import Path
from datetime import datetime
from backend.core.obsidian_service import HELIX_LOGS_DIR


IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".cache",
    ".idea",
    ".vscode",
}


PROJECT_MARKERS = {
    "python": [
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "poetry.lock",
    ],
    "fastapi": [
        "main.py",
    ],
    "django": [
        "manage.py",
    ],
    "node": [
        "package.json",
    ],
    "frontend": [
        "index.html",
        "vite.config.js",
        "vite.config.ts",
    ],
    "database": [
        "alembic.ini",
        "schema.sql",
    ],
    "docker": [
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
    ],
    "git": [
        ".git",
    ],
}


VS_CODE_EXTENSION_RULES = {
    "essential": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "ms-vscode.cpptools",
        "dbaeumer.vscode-eslint",
        "esbenp.prettier-vscode",
        "eamodio.gitlens",
        "ms-azuretools.vscode-docker",
        "humao.rest-client",
    ],
    "useful": [
        "ritwickdey.liveserver",
        "ms-vscode.live-server",
        "formulahendry.code-runner",
        "ms-toolsai.jupyter",
        "github.copilot",
        "github.copilot-chat",
        "ms-vscode.powershell",
        "redhat.vscode-yaml",
        "yzhang.markdown-all-in-one",
    ],
    "database": [
        "ckolkman.vscode-postgres",
        "mtxr.sqltools",
        "mtxr.sqltools-driver-pg",
        "cweijan.vscode-postgresql-client2",
    ],
    "theme_or_visual": [
        "pkief.material-icon-theme",
        "vscode-icons-team.vscode-icons",
        "dracula-theme.theme-dracula",
        "enkia.tokyo-night",
    ],
}


def _safe_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def list_vscode_extensions() -> dict:
    """
    Lista extensões do VS Code.
    Primeiro tenta usar `code --list-extensions`.
    Se falhar, tenta ler a pasta ~/.vscode/extensions.
    """
    extensions = []
    source = None
    error = None

    try:
        completed = subprocess.run(
            ["code", "--list-extensions"],
            capture_output=True,
            text=True,
            shell=True,
            timeout=10,
        )

        if completed.returncode == 0:
            extensions = [
                line.strip()
                for line in completed.stdout.splitlines()
                if line.strip()
            ]
            source = "code --list-extensions"

    except Exception as exc:
        error = str(exc)

    if not extensions:
        vscode_extensions_dir = Path.home() / ".vscode" / "extensions"

        if vscode_extensions_dir.exists():
            source = str(vscode_extensions_dir)

            for item in vscode_extensions_dir.iterdir():
                if not item.is_dir():
                    continue

                # Exemplo de pasta:
                # ms-python.python-2026.1.0
                name = item.name

                parts = name.split("-")
                if len(parts) >= 2:
                    extension_id = "-".join(parts[:-1])
                else:
                    extension_id = name

                extensions.append(extension_id)

    extensions = sorted(set(extensions))

    classified = classify_vscode_extensions(extensions)

    return {
        "available": bool(extensions),
        "source": source,
        "count": len(extensions),
        "extensions": classified,
        "error": error,
    }


def classify_vscode_extensions(extensions: list[str]) -> dict:
    result = {
        "essential": [],
        "useful": [],
        "database": [],
        "theme_or_visual": [],
        "review": [],
        "unknown": [],
    }

    known = set()

    for category, ids in VS_CODE_EXTENSION_RULES.items():
        for extension in extensions:
            normalized = extension.lower()

            if normalized in ids:
                result[category].append(
                    {
                        "id": extension,
                        "reason": _extension_reason(category, extension),
                    }
                )
                known.add(extension)

    for extension in extensions:
        if extension in known:
            continue

        lowered = extension.lower()

        if any(word in lowered for word in ["theme", "icon", "material", "dracula", "night"]):
            result["theme_or_visual"].append(
                {
                    "id": extension,
                    "reason": "Parece ser extensão visual/tema. Manter se você usa; revisar se estiver acumulando temas.",
                }
            )
        elif any(word in lowered for word in ["python", "pylance", "django", "fastapi"]):
            result["essential"].append(
                {
                    "id": extension,
                    "reason": "Parece relacionada a Python/backend, útil para seus projetos.",
                }
            )
        elif any(word in lowered for word in ["postgres", "sql", "database", "db"]):
            result["database"].append(
                {
                    "id": extension,
                    "reason": "Parece relacionada a banco de dados. Útil porque o Helix usa PostgreSQL.",
                }
            )
        elif any(word in lowered for word in ["java", "spring", "csharp", "php", "ruby", "go", "rust"]):
            result["review"].append(
                {
                    "id": extension,
                    "reason": "Parece ser de uma linguagem específica. Revisar se você ainda usa essa stack.",
                }
            )
        else:
            result["unknown"].append(
                {
                    "id": extension,
                    "reason": "Não classifiquei automaticamente. Precisa de revisão manual.",
                }
            )

    return result


def _extension_reason(category: str, extension: str) -> str:
    reasons = {
        "essential": "Provavelmente essencial para desenvolvimento ou produtividade principal.",
        "useful": "Útil dependendo do fluxo de trabalho; não parece obrigatória.",
        "database": "Útil para trabalhar com banco de dados, especialmente PostgreSQL.",
        "theme_or_visual": "Visual/tema/ícones. Manter se você realmente usa.",
        "review": "Vale revisar se ainda faz sentido manter.",
        "unknown": "Não classificada automaticamente.",
    }

    return reasons.get(category, "Classificação automática.")


def get_default_project_roots() -> list[str]:
    candidates = [
        "D:/",
        str(Path.home() / "Documents"),
        str(Path.home() / "OneDrive" / "Documentos"),
        str(Path.home() / "Desktop"),
    ]

    existing = []

    for candidate in candidates:
        path = Path(candidate)

        if path.exists():
            existing.append(str(path))

    return existing


def scan_projects(
    roots: list[str] | None = None,
    max_depth: int = 3,
    max_projects: int = 50,
) -> dict:
    if roots is None:
        roots = get_default_project_roots()

    projects = []
    scanned_roots = []

    for root in roots:
        root_path = _safe_path(root)

        if not root_path.exists():
            continue

        scanned_roots.append(str(root_path))

        for project in _find_projects_in_root(
            root_path=root_path,
            max_depth=max_depth,
        ):
            projects.append(project)

            if len(projects) >= max_projects:
                break

        if len(projects) >= max_projects:
            break

    return {
        "count": len(projects),
        "roots": scanned_roots,
        "projects": projects,
        "ignored_dirs": sorted(IGNORED_DIRS),
    }


def _find_projects_in_root(root_path: Path, max_depth: int) -> list[dict]:
    found = []

    def walk(current: Path, depth: int):
        if depth > max_depth:
            return

        try:
            if current.name in IGNORED_DIRS:
                return

            if is_project_folder(current):
                found.append(analyze_project_folder(current))
                return

            for child in current.iterdir():
                if not child.is_dir():
                    continue

                if child.name in IGNORED_DIRS:
                    continue

                walk(child, depth + 1)

        except PermissionError:
            return
        except OSError:
            return

    walk(root_path, 0)

    return found


def is_project_folder(path: Path) -> bool:
    if not path.is_dir():
        return False

    try:
        names = {item.name for item in path.iterdir()}
    except OSError:
        return False

    for markers in PROJECT_MARKERS.values():
        if any(marker in names for marker in markers):
            return True

    return False


def analyze_project_folder(path: str | Path) -> dict:
    project_path = _safe_path(path)

    if not project_path.exists() or not project_path.is_dir():
        return {
            "found": False,
            "path": str(project_path),
            "error": "Pasta não encontrada ou inválida.",
        }

    try:
        items = list(project_path.iterdir())
    except OSError as exc:
        return {
            "found": False,
            "path": str(project_path),
            "error": str(exc),
        }

    names = {item.name for item in items}
    technologies = detect_project_technologies(names, project_path)
    important_files = detect_important_files(names)

    summary = build_project_summary(project_path, technologies, important_files)

    return {
        "found": True,
        "name": project_path.name,
        "path": str(project_path),
        "technologies": technologies,
        "important_files": important_files,
        "summary": summary,
        "recommendations": build_project_recommendations(project_path, names, technologies),
    }


def detect_project_technologies(names: set[str], project_path: Path) -> list[str]:
    technologies = []

    if "requirements.txt" in names or "pyproject.toml" in names or "Pipfile" in names:
        technologies.append("Python")

    if "manage.py" in names:
        technologies.append("Django")

    if "package.json" in names:
        technologies.append("Node/JavaScript")

        package_path = project_path / "package.json"
        try:
            data = json.loads(package_path.read_text(encoding="utf-8"))
            deps = {
                **data.get("dependencies", {}),
                **data.get("devDependencies", {}),
            }

            if "react" in deps:
                technologies.append("React")

            if "vite" in deps:
                technologies.append("Vite")

            if "next" in deps:
                technologies.append("Next.js")

        except Exception:
            pass

    if "index.html" in names:
        technologies.append("HTML/CSS")

    if "alembic.ini" in names:
        technologies.append("Alembic/SQLAlchemy")

    if "Dockerfile" in names or "docker-compose.yml" in names or "docker-compose.yaml" in names:
        technologies.append("Docker")

    if ".git" in names:
        technologies.append("Git")

    # Heurística simples para FastAPI.
    main_py = project_path / "main.py"
    backend_main = project_path / "backend" / "main.py"

    for candidate in [main_py, backend_main]:
        if candidate.exists():
            try:
                content = candidate.read_text(encoding="utf-8", errors="ignore")
                if "FastAPI" in content:
                    technologies.append("FastAPI")
            except Exception:
                pass

    return sorted(set(technologies))


def detect_important_files(names: set[str]) -> list[str]:
    candidates = [
        "README.md",
        ".gitignore",
        ".env",
        ".env.example",
        "requirements.txt",
        "pyproject.toml",
        "package.json",
        "manage.py",
        "main.py",
        "Dockerfile",
        "docker-compose.yml",
        "alembic.ini",
    ]

    return [name for name in candidates if name in names]


def build_project_summary(
    project_path: Path,
    technologies: list[str],
    important_files: list[str],
) -> str:
    if technologies:
        tech_text = ", ".join(technologies)
    else:
        tech_text = "tecnologia não identificada com confiança"

    if important_files:
        files_text = ", ".join(important_files)
    else:
        files_text = "poucos arquivos marcadores encontrados"

    return (
        f"Projeto '{project_path.name}' detectado. "
        f"Tecnologias: {tech_text}. "
        f"Arquivos importantes: {files_text}."
    )


def build_project_recommendations(
    project_path: Path,
    names: set[str],
    technologies: list[str],
) -> list[str]:
    recommendations = []

    if "README.md" not in names:
        recommendations.append("Criar README.md para documentar objetivo, execução e stack do projeto.")

    if ".gitignore" not in names:
        recommendations.append("Criar .gitignore para evitar subir .venv, cache, logs e arquivos sensíveis.")

    if ".env" in names and ".env.example" not in names:
        recommendations.append("Criar .env.example para documentar variáveis sem expor segredos.")

    if "Python" in technologies and "requirements.txt" not in names and "pyproject.toml" not in names:
        recommendations.append("Adicionar requirements.txt ou pyproject.toml para registrar dependências Python.")

    if "Node/JavaScript" in technologies and "package.json" in names:
        recommendations.append("Verificar scripts em package.json para facilitar execução do projeto.")

    if not recommendations:
        recommendations.append("Estrutura inicial parece saudável. Revisão manual ainda recomendada.")

    return recommendations


def generate_dev_environment_report() -> dict:
    vscode = list_vscode_extensions()
    projects = scan_projects()

    return {
        "vscode": vscode,
        "projects": projects,
        "summary": {
            "vscode_extensions_count": vscode.get("count", 0),
            "projects_count": projects.get("count", 0),
        },
        "safety": (
            "Relatório apenas de leitura. Nenhuma extensão, arquivo ou projeto foi apagado, "
            "modificado ou desinstalado."
        ),
    }

def save_dev_environment_report_to_obsidian(report: dict | None = None) -> Path | None:
    try:
        if report is None:
            report = generate_dev_environment_report()

        reports_dir = HELIX_LOGS_DIR / "Dev Environment"
        reports_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        file_name = f"Dev Environment Report {now:%Y-%m-%d %H-%M-%S}.md"
        file_path = reports_dir / file_name

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

        content = f"""# Dev Environment Report — {now:%Y-%m-%d %H:%M:%S}

## Resumo

- **Extensões VS Code:** {vscode.get("count", 0)}
- **Fonte das extensões:** {vscode.get("source")}
- **Projetos detectados:** {projects.get("count", 0)}
- **Modo:** Apenas leitura. Nada foi apagado, alterado ou desinstalado.

---

## VS Code

### Classificação geral

- **Essenciais:** {len(essential)}
- **Úteis/opcionais:** {len(useful)}
- **Banco de dados:** {len(database)}
- **Temas/visuais:** {len(theme_or_visual)}
- **Para revisar:** {len(review)}
- **Desconhecidas:** {len(unknown)}

"""

        def add_extension_section(title: str, items: list[dict], limit: int | None = None):
            nonlocal content

            content += f"\n### {title}\n\n"

            if not items:
                content += "- Nenhum item encontrado.\n"
                return

            selected_items = items if limit is None else items[:limit]

            for item in selected_items:
                content += f"- `{item.get('id')}` — {item.get('reason')}\n"

            if limit is not None and len(items) > limit:
                content += f"- ... mais {len(items) - limit} itens.\n"

        add_extension_section("Extensões essenciais", essential)
        add_extension_section("Extensões úteis/opcionais", useful)
        add_extension_section("Extensões de banco de dados", database)
        add_extension_section("Temas e visuais", theme_or_visual)
        add_extension_section("Extensões para revisar primeiro", review)
        add_extension_section("Extensões desconhecidas", unknown, limit=30)

        content += "\n---\n\n## Projetos encontrados\n\n"

        if not project_list:
            content += "- Nenhum projeto detectado.\n"
        else:
            for project in project_list:
                technologies = ", ".join(project.get("technologies", [])) or "não identificado"
                important_files = ", ".join(project.get("important_files", [])) or "nenhum marcador importante"

                content += f"### {project.get('name')}\n\n"
                content += f"- **Caminho:** `{project.get('path')}`\n"
                content += f"- **Tecnologias:** {technologies}\n"
                content += f"- **Arquivos importantes:** {important_files}\n"
                content += f"- **Resumo:** {project.get('summary')}\n"

                recommendations = project.get("recommendations", [])

                if recommendations:
                    content += "- **Recomendações:**\n"
                    for recommendation in recommendations:
                        content += f"  - {recommendation}\n"

                content += "\n"

        content += """---

## Leitura do Helix

- O ambiente de desenvolvimento foi analisado em modo seguro.
- Nenhuma extensão foi removida.
- Nenhum projeto foi alterado.
- Nenhum arquivo foi apagado.
- As recomendações são pontos de revisão, não ordens de exclusão.

## Próximos passos sugeridos

- [ ] Revisar extensões classificadas como desconhecidas.
- [ ] Revisar extensões de linguagens que você não usa mais.
- [ ] Criar `.gitignore` nos projetos que ainda não possuem.
- [ ] Criar ou melhorar README.md nos projetos importantes.
- [ ] Decidir quais projetos antigos devem ser arquivados.
"""

        file_path.write_text(content, encoding="utf-8")

        return file_path

    except Exception as exc:
        print(f"Erro ao salvar relatório dev no Obsidian: {exc}")
        return None