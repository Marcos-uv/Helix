from fastapi import APIRouter

from backend.services.dev_environment_service import (
    analyze_project_folder,
    generate_dev_environment_report,
    list_vscode_extensions,
    save_dev_environment_report_to_obsidian,
    scan_projects,
)
from pydantic import BaseModel

from backend.services.project_creator_service import (
    create_gitignore,
    preview_gitignore,
)

router = APIRouter()
class CreateGitignoreRequest(BaseModel):
    project_path: str
    overwrite: bool = False

@router.get("/dev/vscode/extensions")
def dev_vscode_extensions():
    return list_vscode_extensions()

@router.get("dev/projects/scan")
def dev_project_scan(
    max_deth: int = 3,
    max_projects: int = 50,
):
    return scan_projects(
        max_depth=max_deth,
        max_projects=max_projects,
    )

@router.get("/dev/project/analyze")
def dev_project_analyze(path: str):
    return analyze_project_folder(path)


@router.get("/dev/environment/report")
def dev_environment_report():
    return generate_dev_environment_report()

@router.post("/dev/environment/report/obsidian")
def dev_environment_report_obsidian():
    report = generate_dev_environment_report()
    note_path = save_dev_environment_report_to_obsidian(report)

    if not note_path:
        return {
            "saved": False,
            "error": "Não foi possível salvar o relatório no Obsidian.",
        }

    return {
        "saved": True,
        "note_path": str(note_path),
        "vscode_extensions_count": report.get("summary", {}).get("vscode_extensions_count"),
        "projects_count": report.get("summary", {}).get("projects_count"),
    }

@router.get("/dev/project/gitignore/preview")
def dev_project_gitignore_preview():
    return preview_gitignore()


@router.post("/dev/project/gitignore/create")
def dev_project_gitignore_create(request: CreateGitignoreRequest):
    return create_gitignore(
        project_path=request.project_path,
        overwrite=request.overwrite,
    )