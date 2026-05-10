from pathlib import Path


DEFAULT_GITIGNORE_CONTENT = """# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
.venv/
venv/
env/

# Environment variables
.env
.env.*
!.env.example

# Logs
*.log
logs/

# Database / local files
*.sqlite3
*.db

# IDE
.idea/

# VS Code
.vscode/

# OS
.DS_Store
Thumbs.db

# Node / frontend
node_modules/
dist/
build/
.next/

# Cache
.cache/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Audio / temp
*.mp3
*.wav
*.webm
tmp/
temp/

# Obsidian local workspace
.obsidian/workspace.json
.obsidian/workspace-mobile.json
"""


def create_gitignore(
    project_path: str,
    overwrite: bool = False,
) -> dict:
    """
    Cria um .gitignore seguro em uma pasta de projeto.

    Regras:
    - Não cria se a pasta não existir.
    - Não sobrescreve .gitignore existente sem overwrite=True.
    - Não apaga nada.
    """

    path = Path(project_path).expanduser().resolve()

    if not path.exists():
        return {
            "created": False,
            "reason": "A pasta informada não existe.",
            "path": str(path),
        }

    if not path.is_dir():
        return {
            "created": False,
            "reason": "O caminho informado não é uma pasta.",
            "path": str(path),
        }

    gitignore_path = path / ".gitignore"

    if gitignore_path.exists() and not overwrite:
        return {
            "created": False,
            "reason": ".gitignore já existe. Não sobrescrevi por segurança.",
            "path": str(gitignore_path),
            "requires_confirmation": True,
        }

    gitignore_path.write_text(DEFAULT_GITIGNORE_CONTENT, encoding="utf-8")

    return {
        "created": True,
        "path": str(gitignore_path),
        "message": ".gitignore criado com sucesso.",
        "overwritten": gitignore_path.exists() and overwrite,
    }


def preview_gitignore() -> dict:
    return {
        "content": DEFAULT_GITIGNORE_CONTENT,
        "safety": "Prévia apenas. Nenhum arquivo foi criado.",
    }