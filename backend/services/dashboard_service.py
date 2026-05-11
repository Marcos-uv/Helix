import re
from datetime import datetime
from html import escape
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from backend.core.database import Memory, SessionLocal
from backend.core.obsidian_service import HELIX_BRAIN_DIR, HELIX_LOGS_DIR
from backend.core.system_monitor import run_automatic_pc_checkup
from backend.services.dev_environment_service import scan_projects


PROJECTS_CACHE_TTL_SECONDS = 300

_PROJECTS_CACHE = {
    "updated_at": None,
    "projects": [],
}


def is_dashboard_update_question(message: str) -> bool:
    text = message.lower().strip()

    keywords = [
        "atualize o dashboard",
        "atualizar o dashboard",
        "atualiza o dashboard",
        "atualize meu dashboard",
        "atualizar meu dashboard",
        "atualiza meu dashboard",
        "sincronize o dashboard",
        "sincronizar o dashboard",
        "sincroniza o dashboard",
        "regenere o dashboard",
        "regenerar o dashboard",
        "dashboard do obsidian",
        "dashboard helix",
        "atualize o painel",
        "atualizar o painel",
        "atualiza o painel",
        "painel do helix",
    ]

    return any(keyword in text for keyword in keywords)


def _safe_value(value, default="N/A"):
    if value is None:
        return default

    return value


def _html(value) -> str:
    return escape(str(value), quote=True)


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_status_visual(status: str) -> tuple[str, str]:
    status = (status or "").lower().strip()

    if status in ["ok", "healthy", "success", "stable"]:
        return "success", "SYSTEM STABLE"

    if status in ["critical", "danger", "error"]:
        return "danger", "CRITICAL ATTENTION"

    return "warning", "ATTENTION REQUIRED"


def _get_latest_memories(limit: int = 4) -> list[Memory]:
    db = SessionLocal()

    try:
        memories = (
            db.query(Memory)
            .order_by(
                Memory.importance.desc(),
                Memory.created_at.desc(),
            )
            .limit(limit)
            .all()
        )

        return memories

    except SQLAlchemyError as exc:
        print(f"Erro ao carregar memórias para o dashboard: {exc}")
        db.rollback()
        return []

    finally:
        db.close()


def _build_memory_nodes(limit: int = 4) -> str:
    memories = _get_latest_memories(limit=limit)

    if not memories:
        return '<div class="sb-row">No PostgreSQL memories found yet.</div>'

    rows = []

    for memory in memories:
        content = _safe_value(memory.content, "Sem conteúdo")
        owner_type = _safe_value(memory.owner_type, "unknown")
        category = _safe_value(memory.category, "general")

        if len(str(content)) > 120:
            content = str(content)[:117] + "..."

        rows.append(
            '<div class="sb-row">'
            f'<span class="sb-row-kicker">{_html(owner_type)} / {_html(category)}</span>'
            f'<span>{_html(content)}</span>'
            "</div>"
        )

    return "\n".join(rows)


def _get_latest_log_files(limit: int = 4) -> list[Path]:
    try:
        if not HELIX_LOGS_DIR.exists():
            return []

        log_files = [
            path
            for path in HELIX_LOGS_DIR.rglob("*.md")
            if path.is_file()
        ]

        log_files.sort(
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        return log_files[:limit]

    except Exception as exc:
        print(f"Erro ao carregar logs para o dashboard: {exc}")
        return []


def _build_log_nodes(limit: int = 4) -> str:
    log_files = _get_latest_log_files(limit=limit)

    if not log_files:
        return '<div class="sb-row">No Helix logs found yet.</div>'

    rows = []

    for path in log_files:
        try:
            relative_path = path.relative_to(HELIX_LOGS_DIR)
        except ValueError:
            relative_path = path

        modified_at = datetime.fromtimestamp(
            path.stat().st_mtime
        ).strftime("%d/%m %H:%M")

        rows.append(
            '<div class="sb-row">'
            f'<span class="sb-row-kicker">{_html(modified_at)}</span>'
            f'<span>{_html(path.stem)}</span>'
            f'<code>{_html(relative_path)}</code>'
            "</div>"
        )

    return "\n".join(rows)


def _get_detected_projects(limit: int = 4) -> list[dict]:
    now = datetime.now()

    cached_at = _PROJECTS_CACHE.get("updated_at")
    cached_projects = _PROJECTS_CACHE.get("projects", [])

    if cached_at and cached_projects:
        cache_age = (now - cached_at).total_seconds()

        if cache_age < PROJECTS_CACHE_TTL_SECONDS:
            return cached_projects[:limit]

    try:
        result = scan_projects(
            max_depth=2,
            max_projects=limit,
        )

        projects = result.get("projects", [])

        _PROJECTS_CACHE["updated_at"] = now
        _PROJECTS_CACHE["projects"] = projects

        return projects[:limit]

    except Exception as exc:
        print(f"Erro ao carregar projetos para o dashboard: {exc}")

        if cached_projects:
            print("Usando projetos do cache por causa de erro no scanner.")
            return cached_projects[:limit]

        return []


def _build_project_nodes(projects: list[dict]) -> str:
    if not projects:
        return '<div class="sb-row">No projects detected yet.</div>'

    rows = []

    for project in projects[:4]:
        name = _safe_value(project.get("name"), "Projeto sem nome")
        path = _safe_value(project.get("path"), "caminho desconhecido")
        technologies = project.get("technologies", [])

        tech_text = ", ".join(technologies) if technologies else "unknown"

        rows.append(
            '<div class="sb-row">'
            f'<span class="sb-row-kicker">{_html(tech_text)}</span>'
            f'<span>{_html(name)}</span>'
            f'<code>{_html(path)}</code>'
            "</div>"
        )

    return "\n".join(rows)


def _build_alert_rows(alerts: list[str]) -> str:
    if not alerts:
        return '<div class="sb-row">No critical alerts.</div>'

    rows = []

    for alert in alerts[:4]:
        rows.append(
            '<div class="sb-row sb-alert-row">'
            f"<span>{_html(alert)}</span>"
            "</div>"
        )

    return "\n".join(rows)


def _build_suggestions(
    status: str,
    memory_percent,
    disk_percent,
    disk_free,
    alerts: list[str],
    projects: list[dict],
) -> str:
    suggestions = []

    memory_value = _to_float(memory_percent)
    disk_value = _to_float(disk_percent)
    free_value = _to_float(disk_free)

    if disk_value >= 85 or free_value < 30:
        suggestions.append("Prioritize safe C: cleanup analysis.")

    if memory_value >= 75:
        suggestions.append("Watch RAM before running heavy local AI workloads.")

    if alerts:
        suggestions.append("Review active system alerts before adding new automation.")

    if projects:
        suggestions.append("Pick one detected project for a deeper structure audit.")

    if status and str(status).lower() == "warning":
        suggestions.append("Keep Helix in cautious mode: functional, but attention needed.")

    if not suggestions:
        suggestions.append("System looks stable. Continue monitoring.")

    rows = []

    for suggestion in suggestions[:4]:
        rows.append(
            '<div class="sb-row">'
            f"<span>{_html(suggestion)}</span>"
            "</div>"
        )

    return "\n".join(rows)


def _build_command_matrix() -> str:
    groups = {
        "SYSTEM": "open apps · close apps · PC check-up",
        "OBSIDIAN": "create notes · update dashboard · read logs",
        "MEMORY": "PostgreSQL · rules · technical decisions",
        "PROJECTS": "scan projects · analyze structure · create .gitignore",
    }

    rows = []

    for key, value in groups.items():
        rows.append(
            '<div class="sb-mini-line">'
            f"<strong>{_html(key)}</strong>"
            f"<span>{_html(value)}</span>"
            "</div>"
        )

    return "\n".join(rows)


def build_helix_dashboard_auto_block(checkup: dict) -> str:
    now = datetime.now()

    status = checkup.get("status", "warning")
    summary = checkup.get(
        "summary",
        "O PC está funcional, mas há pontos de atenção.",
    )
    mode = checkup.get("mode", "automatic_pc_checkup")

    status_class, status_label = _get_status_visual(status)

    metrics = checkup.get("metrics", {})
    cpu = metrics.get("cpu", {})
    memory = metrics.get("memory", {})
    disk = metrics.get("disk", {})

    cpu_percent = _safe_value(cpu.get("percent"))
    memory_percent = _safe_value(memory.get("percent"))
    memory_used = _safe_value(memory.get("used_gb"))
    memory_total = _safe_value(memory.get("total_gb"))
    disk_percent = _safe_value(disk.get("percent"))
    disk_free = _safe_value(disk.get("free_gb"))

    alerts = checkup.get("alerts", [])
    actions_taken = checkup.get("actions_taken", [])
    storage_findings = checkup.get("storage_findings", [])

    projects = _get_detected_projects(limit=4)

    memories_html = _build_memory_nodes(limit=4)
    logs_html = _build_log_nodes(limit=4)
    projects_html = _build_project_nodes(projects)
    alerts_html = _build_alert_rows(alerts)
    suggestions_html = _build_suggestions(
        status=status,
        memory_percent=memory_percent,
        disk_percent=disk_percent,
        disk_free=disk_free,
        alerts=alerts,
        projects=projects,
    )
    commands_html = _build_command_matrix()

    action_text = " · ".join(actions_taken[:2]) if actions_taken else "No automatic action required."
    storage_count = len(storage_findings)

    memories_count = len(_get_latest_memories(limit=50))
    logs_count = len(_get_latest_log_files(limit=50))
    projects_count = len(projects)

    return f"""<!-- HELIX_AUTO_STATUS_START -->
<div class="sb-showcase">
<div class="sb-title">Showcase of my second<br>brain</div>
<div class="sb-stage">
<div class="sb-brand"><span class="sb-dot"></span><strong>HELIX</strong><small>{_html(mode)}</small></div>
<div class="sb-left-hud">
<div class="sb-hud-label">NOTES</div><div class="sb-hud-number">566</div>
<div class="sb-hud-label">MEMORIES</div><div class="sb-hud-number">{memories_count}</div>
<div class="sb-hud-label">PROJECTS</div><div class="sb-hud-number">{projects_count}</div>
<div class="sb-hud-label">LOGS</div><div class="sb-hud-number">{logs_count}</div>
<div class="sb-hud-label">STATUS</div><div class="sb-status {status_class}">{_html(status_label)}</div>
</div>
<div class="sb-brain-space">
<div class="sb-orbit orbit-one"></div><div class="sb-orbit orbit-two"></div><div class="sb-orbit orbit-three"></div>
<div class="sb-node node-a"></div><div class="sb-node node-b"></div><div class="sb-node node-c"></div><div class="sb-node node-d"></div><div class="sb-node node-e"></div><div class="sb-node node-f"></div>
<div class="sb-brain-core"><div class="sb-core-inner"></div></div>
</div>
<div class="sb-right-hud">
<div class="sb-panel-title">SYSTEM</div>
<div class="sb-metric"><span>CPU</span><strong>{_html(cpu_percent)}%</strong></div>
<div class="sb-metric"><span>RAM</span><strong>{_html(memory_percent)}%</strong></div>
<div class="sb-metric"><span>DISK C</span><strong>{_html(disk_percent)}%</strong></div>
<div class="sb-metric"><span>FREE</span><strong>{_html(disk_free)} GB</strong></div>
<div class="sb-small-note">{_html(summary)}</div>
</div>
<div class="sb-bottom-graph"><span></span><span></span><span></span><span></span><span></span></div>
</div>
<div class="sb-subtitle">Integration of<br>PostgreSQL, Obsidian and local APIs<br>to make a smart second brain<br>assistant</div>
<div class="sb-data-strip">
<div><strong>Last update</strong><span>{now:%d/%m/%Y %H:%M:%S}</span></div>
<div><strong>Memory</strong><span>{_html(memory_used)} GB / {_html(memory_total)} GB</span></div>
<div><strong>Storage findings</strong><span>{storage_count} detected</span></div>
<div><strong>Last action</strong><span>{_html(action_text)}</span></div>
</div>
<div class="sb-detail-grid">
<div class="sb-detail-panel"><h3>Memory stream</h3>{memories_html}</div>
<div class="sb-detail-panel"><h3>Detected projects</h3>{projects_html}</div>
<div class="sb-detail-panel"><h3>Recent logs</h3>{logs_html}</div>
<div class="sb-detail-panel"><h3>Alerts</h3>{alerts_html}</div>
<div class="sb-detail-panel"><h3>Command matrix</h3>{commands_html}</div>
<div class="sb-detail-panel"><h3>Helix suggestions</h3>{suggestions_html}</div>
</div>
</div>
<!-- HELIX_AUTO_STATUS_END -->"""


def update_helix_dashboard(checkup: dict | None = None) -> Path | None:
    try:
        dashboard_path = HELIX_BRAIN_DIR / "Dashboard Helix.md"
        dashboard_path.parent.mkdir(parents=True, exist_ok=True)

        if checkup is None:
            checkup = run_automatic_pc_checkup(
                drive_path="C:/",
                low_free_space_gb=30,
            )

        auto_block = build_helix_dashboard_auto_block(checkup)

        if dashboard_path.exists():
            current_content = dashboard_path.read_text(encoding="utf-8")
        else:
            current_content = "# 🧠 Dashboard Helix\n\nPainel principal do sistema Helix.\n\n"

        pattern = re.compile(
            r"<!-- HELIX_AUTO_STATUS_START -->.*?<!-- HELIX_AUTO_STATUS_END -->",
            re.DOTALL,
        )

        if pattern.search(current_content):
            new_content = pattern.sub(lambda _: auto_block.strip(), current_content)
        else:
            new_content = current_content.rstrip() + "\n\n" + auto_block.strip() + "\n"

        dashboard_path.write_text(new_content, encoding="utf-8")

        return dashboard_path

    except Exception as exc:
        print(f"Erro ao atualizar Dashboard Helix: {exc}")
        return None


def build_dashboard_update_response() -> str:
    checkup = run_automatic_pc_checkup(
        drive_path="C:/",
        low_free_space_gb=30,
    )

    dashboard_path = update_helix_dashboard(checkup)

    if not dashboard_path:
        return (
            "Tentei atualizar o Dashboard Helix, mas algo falhou no caminho.\n\n"
            "Nada foi apagado ou alterado fora da tentativa de escrita do dashboard. "
            "Verifique se o Obsidian Vault está acessível e se o arquivo não está bloqueado."
        )

    metrics = checkup.get("metrics", {})
    cpu = metrics.get("cpu", {})
    memory = metrics.get("memory", {})
    disk = metrics.get("disk", {})

    response = "Dashboard Helix atualizado no Obsidian.\n\n"
    response += f"Arquivo: `{dashboard_path}`\n\n"

    response += "Resumo do check-up usado no dashboard:\n"
    response += f"- Status: {checkup.get('status')}\n"
    response += f"- Resumo: {checkup.get('summary')}\n"
    response += f"- CPU: {cpu.get('percent')}%\n"
    response += (
        f"- RAM: {memory.get('percent')}% "
        f"({memory.get('used_gb')} GB de {memory.get('total_gb')} GB)\n"
    )
    response += (
        f"- Disco C: {disk.get('percent')}% usado "
        f"({disk.get('free_gb')} GB livres)\n\n"
    )

    response += (
        "Atualizei o Dashboard Helix no estilo second brain showcase. "
        "Menos painel genérico, mais central neural futurista."
    )

    return response