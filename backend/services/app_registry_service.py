import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.models.known_app import KnownApp


DATA_DIR = Path("data")
KNOWN_APPS_CACHE_PATH = DATA_DIR / "known_apps.json"


MAIN_PROCESS_NAMES = {
    "steam.exe",
    "spotify.exe",
    "discord.exe",
    "opera.exe",
    "code.exe",
    "obsidian.exe",
    "pgadmin4.exe",
    "msedge.exe",
    "chrome.exe",
    "firefox.exe",
    "ollama.exe",
    "ollama app.exe",
}


MAIN_NORMALIZED_NAMES = {
    "steam",
    "spotify",
    "discord",
    "opera gx",
    "opera",
    "visual studio code",
    "vscode",
    "vs code",
    "obsidian",
    "pgadmin",
    "pgadmin 4",
    "microsoft edge",
    "edge",
    "google chrome",
    "chrome",
    "mozilla firefox",
    "firefox",
    "ollama",
    "ollama app",
    "epic games launcher",
    "epic games",
    "ea app",
    "ubisoft connect",
    "rockstar games launcher",
    "notion",
}


BLOCKED_EXACT_NAMES = {
    # PostgreSQL / database internals
    "clusterdb",
    "createdb",
    "createuser",
    "dropdb",
    "dropuser",
    "ecpg",
    "initdb",
    "oid2name",
    "pg amcheck",
    "pg archivecleanup",
    "pg basebackup",
    "pg checksums",
    "pg combinebackup",
    "pg config",
    "pg controldata",
    "pg createsubscriber",
    "pg ctl",
    "pg dump",
    "pg dumpall",
    "pg isready",
    "pg receivewal",
    "pg recvlogical",
    "pg resetwal",
    "pg restore",
    "pg rewind",
    "pg test fsync",
    "pg test timing",
    "pg upgrade",
    "pg verifybackup",
    "pg walinspect",
    "pgbench",
    "postgres",
    "postmaster",
    "psql",
    "reindexdb",
    "vacuumdb",

    # Steam / game internals
    "easteamproxy",
    "ea steam proxy",
    "fossilize replay",
    "fossilize replay64",
    "gameoverlayui",
    "gameoverlayui64",
    "gldriverquery",
    "gldriverquery64",
    "steam monitor",
    "steamerrorreporter",
    "steamerrorreporter64",
    "steamservice",
    "steamwebhelper",
    "steamxboxutil",
    "steamxboxutil64",

    # Browser / Windows internals
    "app recovery",
    "assistant installer",
    "browser assistant",
    "copilot setup",
    "copilotupdate",
    "elevated tracing service",
    "ie to edge stub",
    "microsoftedgecomregistershellarm64",
    "microsoftedgecomregistershell64",
    "microsoftedgeupdate",
    "microsoftedgeupdatecomregistershell64",
    "microsoftedgeupdatecore",
    "microsoftedgeupdateondemand",
    "mscopilot",
    "msedge proxy",
    "msedge pwa launcher",
    "msedgewebview2",
    "opera autoupdate",
    "opera gx splash",
    "passkey authenticator plugin",

    # Visual Studio / protocol internals
    "microsoft visualstudio githubprotocolhandler",
    "microsoft visualstudio vswebprotocolselector",

    # Windows/Admin/Menu Iniciar pseudo-apps
    "administrative tools",
    "ferramentas administrativas",
    "application verifier wow",
    "application verifier x64",
    "character map",
    "command prompt",
    "computer management",
    "control panel",
    "developer command prompt for vs",
    "developer powershell for vs",
    "dfrgui",
    "disk cleanup",
    "documentation for desktop apps",
    "documentation for uwp apps",
    "event viewer",
    "file explorer",
    "iscsi initiator",
    "lixeira",
    "magnify",
    "livecaptions",
    "git release notes",
    "desinstalar o lightshot",
    "configurar java",
    "console rar manual",

    # Generic helpers that are not useful as normal apps
    "drivers",
    "dump64",
    "dump64a",
    "kinit",
    "launcher",
}


BLOCKED_KEYWORDS = {
    "installer",
    "install",
    "uninstall",
    "updater",
    "update",
    "autoupdate",
    "setup",
    "crash",
    "helper",
    "service",
    "broker",
    "elevation",
    "notification",
    "maintenance",
    "runtime",
    "exporter",
    "tracing",
    "telemetry",
    "diagnostic",
    "diagnostics",
    "repair",
    "recovery",
    "redist",
    "redistributable",
    "dotnetfx",
    "dxsetup",
    "vcredist",
    "vc_redist",
    "webview",
    "pwa launcher",
    "proxy",
    "splash",
    "monitor",
    "reporter",
    "errorreporter",
    "xboxutil",
    "comregister",
    "registershell",
    "protocolhandler",
    "protocolselector",
    "protocol selector",
    "stub",
    "authenticator plugin",
    "cookie_exporter",
    "cookie exporter",
    "administrative tools",
    "windows tools",
    "system tools",
    "control panel",
    "computer management",
    "event viewer",
    "disk cleanup",
    "character map",
    "application verifier",
    "documentation for",
    "release notes",
    "unins000",
}


PROTECTED_MAIN_APPS = {
    "steam",
    "spotify",
    "discord",
    "obsidian",
    "opera gx",
    "opera",
    "visual studio code",
    "pgadmin 4",
    "pgadmin",
    "microsoft edge",
    "google chrome",
    "mozilla firefox",
    "ollama",
    "ollama app",
    "epic games launcher",
    "rockstar games launcher",
    "ubisoft connect",
    "ea app",
}


def normalize_app_name(value: str) -> str:
    if not value:
        return ""

    value = value.lower().strip()
    value = value.replace(".exe", "")
    value = value.replace(".lnk", "")
    value = value.replace("-", " ")
    value = value.replace("_", " ")
    value = re.sub(r"[^a-z0-9áàâãéèêíïóôõöúçñ\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    return value


def _normalize_exe_name(value: str | None) -> str:
    if not value:
        return ""

    return Path(value).name.lower().strip()


def build_aliases_from_name(name: str) -> list[str]:
    normalized = normalize_app_name(name)

    aliases = {
        normalized,
        normalized.replace(" ", ""),
        normalized.replace(" ", "-"),
        normalized.replace(" ", "_"),
    }

    manual_aliases = {
        "visual studio code": ["vscode", "vs code", "code"],
        "opera gx": ["opera", "navegador", "browser"],
        "opera": ["opera gx", "navegador", "browser"],
        "discord": ["dc"],
        "spotify": ["music", "musica", "música", "spotfy", "spoti"],
        "pgadmin 4": ["pgadmin", "postgres", "postgresql"],
        "pgadmin": ["pgadmin 4", "postgres", "postgresql"],
        "obsidian": ["vault", "notas", "cofre"],
        "steam": ["jogos"],
        "epic games launcher": ["epic", "epic games"],
        "epic games": ["epic", "epic games launcher"],
        "google chrome": ["chrome"],
        "microsoft edge": ["edge"],
        "firefox": ["mozilla firefox"],
        "ollama app": ["ollama"],
    }

    for key, values in manual_aliases.items():
        if key in normalized:
            aliases.update(values)

    return sorted(alias for alias in aliases if alias)


def guess_app_type(name: str, path: str) -> str:
    text = f"{name} {path}".lower()

    if any(x in text for x in ["code", "visual studio", "pycharm", "git", "node", "python", "ollama"]):
        return "development"

    if any(x in text for x in ["postgres", "pgadmin", "mysql", "database"]):
        return "database"

    if any(x in text for x in ["opera", "chrome", "firefox", "edge", "browser"]):
        return "browser"

    if any(x in text for x in ["discord", "spotify", "steam", "epic games", "ea app", "ubisoft"]):
        return "user_app"

    if any(x in text for x in ["obsidian", "notion"]):
        return "knowledge"

    return "unknown"


def app_to_dict(app: KnownApp) -> dict[str, Any]:
    return {
        "id": app.id,
        "name": app.name,
        "normalized_name": app.normalized_name,
        "aliases": app.aliases or [],
        "exe_path": app.exe_path,
        "process_name": app.process_name,
        "app_type": app.app_type,
        "source": app.source,
        "confidence": app.confidence,
        "is_active": app.is_active,
        "first_seen_at": app.first_seen_at.isoformat() if app.first_seen_at else None,
        "last_seen_at": app.last_seen_at.isoformat() if app.last_seen_at else None,
        "updated_at": app.updated_at.isoformat() if app.updated_at else None,
    }


def _path_text(name: str, exe_path: str, process_name: str | None = None) -> str:
    return f"{name} {exe_path} {process_name or ''}".lower()


def _is_start_menu_shortcut(exe_path: str | None) -> bool:
    if not exe_path:
        return False

    path = exe_path.lower()
    return path.endswith(".lnk") and "start menu" in path


def _is_main_process(name: str, exe_path: str, process_name: str | None = None) -> bool:
    normalized = normalize_app_name(name)
    exe_name = _normalize_exe_name(exe_path) or _normalize_exe_name(process_name)
    process = (process_name or "").lower().strip()

    if exe_name in MAIN_PROCESS_NAMES:
        return True

    if process in MAIN_PROCESS_NAMES:
        return True

    if normalized in MAIN_NORMALIZED_NAMES:
        return True

    return False


def _is_blocked_utility_name(name: str, exe_path: str = "", process_name: str | None = None) -> bool:
    """
    Decide se um executável deve ficar fora do mapa operacional do Helix.

    Isso NÃO apaga nada do PC. Só impede que o Helix trate componentes internos
    como apps principais.
    """
    normalized = normalize_app_name(name)
    exe_name = _normalize_exe_name(exe_path) or _normalize_exe_name(process_name)
    exe_normalized = normalize_app_name(exe_name)
    text = _path_text(name, exe_path, process_name)

    # Proteção: apps principais conhecidos não devem ser bloqueados só porque
    # o caminho contém alguma palavra genérica.
    if normalized in PROTECTED_MAIN_APPS or exe_name in MAIN_PROCESS_NAMES:
        return False

    if normalized in BLOCKED_EXACT_NAMES or exe_normalized in BLOCKED_EXACT_NAMES:
        return True

    # MicrosoftEdge_X64_148.0... é instalador/artefato do Edge, não o app msedge.exe.
    if normalized.startswith("microsoftedge") and exe_name != "msedge.exe":
        return True

    # Ferramentas pg_* quase sempre são utilitários internos do PostgreSQL.
    if normalized.startswith("pg ") and "pgadmin" not in normalized:
        return True

    # Componentes Steam auxiliares. O app principal é steam.exe.
    if normalized.startswith("steam") and exe_name != "steam.exe":
        return True

    # Componentes Opera auxiliares. O app principal é opera.exe.
    if "opera" in normalized and exe_name != "opera.exe" and normalized not in {"opera", "opera gx"}:
        return True

    # Componentes Edge auxiliares. O app principal é msedge.exe.
    if "edge" in normalized and exe_name != "msedge.exe" and normalized not in {"edge", "microsoft edge"}:
        return True

    # Atalhos de pastas administrativas do Menu Iniciar não são apps de usuário.
    path_text = (exe_path or "").lower().replace("\\", "/")
    blocked_start_menu_folders = {
        "administrative tools",
        "windows tools",
        "system tools",
        "accessibility",
        "maintenance",
        "startup",
        "ferramentas administrativas",
        "ferramentas do windows",
        "ferramentas do sistema",
        "acessibilidade",
        "inicializar",
    }

    if any(f"/{folder}/" in path_text for folder in blocked_start_menu_folders):
        return True

    if any(keyword in text for keyword in BLOCKED_KEYWORDS):
        return True

    return False


def is_primary_launchable_app(app: KnownApp) -> bool:
    """
    Define se o app parece ser um programa principal que o usuário realmente
    esperaria abrir pelo Helix.

    Regra principal: só aparece na resposta "o que você sabe abrir?" quando:
    - é um executável principal conhecido; ou
    - é um atalho do Menu Iniciar com nome humano; e
    - não parece helper/updater/setup/proxy/monitor/etc.
    """
    if _is_blocked_utility_name(app.name, app.exe_path, app.process_name):
        return False

    normalized = normalize_app_name(app.name)
    exe_name = _normalize_exe_name(app.exe_path) or _normalize_exe_name(app.process_name)

    if exe_name in MAIN_PROCESS_NAMES:
        return True

    if normalized in MAIN_NORMALIZED_NAMES:
        return True

    # Só libera atalhos .lnk quando vierem do Menu Iniciar e não forem utilitários.
    if _is_start_menu_shortcut(app.exe_path):
        return True

    return False


def save_known_apps_cache(db: Session) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    apps = (
        db.query(KnownApp)
        .filter(KnownApp.is_active == True)
        .order_by(KnownApp.name.asc())
        .all()
    )

    # O cache fica com todos os apps ativos, não só os "bonitos" da listagem.
    # Assim o executor ainda consegue abrir um app específico salvo, se for útil.
    payload = [app_to_dict(app) for app in apps]

    KNOWN_APPS_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def upsert_known_app(
    db: Session,
    *,
    name: str,
    exe_path: str,
    process_name: str | None = None,
    aliases: list[str] | None = None,
    app_type: str | None = None,
    source: str = "scanner",
    confidence: float = 0.7,
) -> KnownApp:
    normalized_name = normalize_app_name(name)
    exe_path = str(Path(exe_path))

    final_aliases = set(aliases or [])
    final_aliases.update(build_aliases_from_name(name))

    detected_type = app_type or guess_app_type(name, exe_path)
    should_be_active = not _is_blocked_utility_name(name, exe_path, process_name)

    # Dá um bônus leve para apps principais.
    if _is_main_process(name, exe_path, process_name):
        confidence = max(confidence, 0.9)

    existing = db.query(KnownApp).filter(KnownApp.exe_path == exe_path).first()

    if existing:
        existing.name = name
        existing.normalized_name = normalized_name
        existing.aliases = sorted(final_aliases)
        existing.process_name = process_name
        existing.app_type = detected_type
        existing.source = source
        existing.confidence = max(existing.confidence or 0, confidence)
        existing.is_active = should_be_active
        existing.last_seen_at = datetime.now()
        existing.updated_at = datetime.now()

        db.commit()
        db.refresh(existing)
        return existing

    app = KnownApp(
        name=name,
        normalized_name=normalized_name,
        aliases=sorted(final_aliases),
        exe_path=exe_path,
        process_name=process_name,
        app_type=detected_type,
        source=source,
        confidence=confidence,
        is_active=should_be_active,
    )

    db.add(app)
    db.commit()
    db.refresh(app)

    return app


def list_known_apps(db: Session, limit: int = 200) -> list[dict[str, Any]]:
    apps = (
        db.query(KnownApp)
        .filter(KnownApp.is_active == True)
        .order_by(KnownApp.name.asc())
        .limit(limit)
        .all()
    )

    return [app_to_dict(app) for app in apps]


def list_launchable_apps(db: Session, limit: int = 80) -> list[dict[str, Any]]:
    apps = (
        db.query(KnownApp)
        .filter(KnownApp.is_active == True)
        .order_by(KnownApp.name.asc())
        .all()
    )

    filtered = [app for app in apps if is_primary_launchable_app(app)]

    # Remove duplicados visuais. Preferimos executáveis principais e nomes mais humanos.
    unique_by_process: dict[str, KnownApp] = {}

    for app in filtered:
        exe_name = _normalize_exe_name(app.exe_path) or _normalize_exe_name(app.process_name)
        normalized = normalize_app_name(app.name)
        key = exe_name or normalized

        if not key:
            continue

        current = unique_by_process.get(key)

        if current is None:
            unique_by_process[key] = app
            continue

        current_name = normalize_app_name(current.name)

        # Troca nomes genéricos por nomes mais amigáveis quando possível.
        if normalized in MAIN_NORMALIZED_NAMES and current_name not in MAIN_NORMALIZED_NAMES:
            unique_by_process[key] = app

    result = sorted(
        unique_by_process.values(),
        key=lambda item: normalize_app_name(item.name),
    )

    return [app_to_dict(app) for app in result[:limit]]


def _score_app_match(app: KnownApp, query: str) -> int:
    candidates = {
        app.normalized_name,
        normalize_app_name(app.name),
        normalize_app_name(Path(app.exe_path).stem if app.exe_path else ""),
        *(normalize_app_name(alias) for alias in (app.aliases or [])),
    }

    score = 0

    for candidate in candidates:
        if not candidate:
            continue

        if query == candidate:
            score = max(score, 100)
        elif query in candidate:
            score = max(score, 85)
        elif candidate in query:
            score = max(score, 75)
        else:
            similarity = SequenceMatcher(None, query, candidate).ratio()

            if similarity >= 0.82:
                score = max(score, int(similarity * 100))

    if is_primary_launchable_app(app):
        score += 8

    return score


def find_known_app(db: Session, name: str) -> dict[str, Any] | None:
    query = normalize_app_name(name)

    if not query:
        return None

    apps = db.query(KnownApp).filter(KnownApp.is_active == True).all()

    best_app = None
    best_score = 0

    for app in apps:
        score = _score_app_match(app, query)

        if score > best_score:
            best_score = score
            best_app = app

    if not best_app or best_score < 70:
        return None

    return app_to_dict(best_app)


def deactivate_known_app(db: Session, app_id: int) -> dict[str, Any]:
    app = db.query(KnownApp).filter(KnownApp.id == app_id).first()

    if not app:
        return {
            "found": False,
            "message": f"App com id {app_id} não encontrado.",
        }

    app.is_active = False
    app.updated_at = datetime.now()

    db.commit()
    save_known_apps_cache(db)

    return {
        "found": True,
        "message": f"App desativado: {app.name}",
        "app": app_to_dict(app),
    }


def cleanup_known_apps(db: Session) -> dict[str, Any]:
    apps = db.query(KnownApp).filter(KnownApp.is_active == True).all()

    deactivated = []

    for app in apps:
        if _is_blocked_utility_name(app.name, app.exe_path, app.process_name):
            app.is_active = False
            app.updated_at = datetime.now()
            deactivated.append(app_to_dict(app))

    db.commit()
    save_known_apps_cache(db)

    return {
        "status": "ok",
        "deactivated_count": len(deactivated),
        "deactivated": deactivated,
    }


def refresh_known_apps_cache(db: Session) -> dict[str, Any]:
    save_known_apps_cache(db)

    apps = list_known_apps(db, limit=1000)
    launchable_apps = list_launchable_apps(db, limit=1000)

    return {
        "status": "ok",
        "message": "Cache de aplicativos conhecidos atualizado.",
        "count": len(apps),
        "launchable_count": len(launchable_apps),
    }
