from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.services.app_registry_service import (
    guess_app_type,
    normalize_app_name,
    refresh_known_apps_cache,
    upsert_known_app,
)


# -----------------------------------------------------------------------------
# Ideia principal
# -----------------------------------------------------------------------------
# Este scanner trabalha por camadas:
# 1. Menu Iniciar (.lnk)          -> fonte mais confiável para apps abríveis.
# 2. Registro de instalados       -> bom para apps instalados oficialmente.
# 3. Scan bruto de .exe           -> fallback, com filtro pesado.
#
# O objetivo não é salvar qualquer .exe que existe no PC. O objetivo é alimentar
# o known_apps com coisas que o usuário provavelmente espera abrir pelo Helix.
# -----------------------------------------------------------------------------


BAD_NAME_KEYWORDS = {
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
    "pwa",
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
    "stub",
    "cookie exporter",
    "cookie_exporter",
    "administrative tools",
    "ferramentas administrativas",
    "windows tools",
    "ferramentas do windows",
    "control panel",
    "painel de controle",
    "computer management",
    "event viewer",
    "disk cleanup",
    "character map",
    "iscsicpl",
    "iscsicpl.exe",
    "application verifier",
    "documentation for",
    "release notes",
    "unins000",
}

BAD_FOLDER_PARTS = {
    "windows",
    "system32",
    "syswow64",
    "winsxs",
    "temp",
    "tmp",
    "cache",
    "runtime",
    "redist",
    "redistributable",
    "installer",
    "setup",
    "crashpad",
    "logs",
}

INTERNAL_EXACT_NAMES = {
    # PostgreSQL internals
    "clusterdb",
    "createdb",
    "createuser",
    "dropdb",
    "dropuser",
    "ecpg",
    "initdb",
    "oid2name",
    "pg_amcheck",
    "pg_archivecleanup",
    "pg_basebackup",
    "pg_checksums",
    "pg_combinebackup",
    "pg_config",
    "pg_controldata",
    "pg_createsubscriber",
    "pg_ctl",
    "pg_dump",
    "pg_dumpall",
    "pg_isready",
    "pg_receivewal",
    "pg_recvlogical",
    "pg_resetwal",
    "pg_restore",
    "pg_rewind",
    "pg_test_fsync",
    "pg_test_timing",
    "pg_upgrade",
    "pg_verifybackup",
    "pg_walinspect",
    "pgbench",
    "postgres",
    "postmaster",
    "psql",
    "reindexdb",
    "vacuumdb",

    # Steam internals
    "easteamproxy",
    "fossilize-replay",
    "fossilize-replay64",
    "gameoverlayui",
    "gameoverlayui64",
    "gldriverquery",
    "gldriverquery64",
    "steamerrorreporter",
    "steamerrorreporter64",
    "steamservice",
    "steamwebhelper",
    "steamxboxutil",
    "steamxboxutil64",
}

COMMON_START_MENU_ROOTS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]


BAD_START_MENU_FOLDER_PARTS = {
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

BAD_START_MENU_EXACT_NAMES = {
    "administrative tools",
    "ferramentas administrativas",
    "control panel",
    "painel de controle",
    "command prompt",
    "prompt de comando",
    "computer management",
    "gerenciamento do computador",
    "event viewer",
    "visualizador de eventos",
    "disk cleanup",
    "limpeza de disco",
    "character map",
    "mapa de caracteres",
    "file explorer",
    "explorador de arquivos",
    "lixeira",
    "recycle bin",
    "magnify",
    "livecaptions",
    "dfrgui",
    "iscsi initiator",
    "application verifier wow",
    "application verifier x64",
    "documentation for desktop apps",
    "documentation for uwp apps",
    "developer command prompt for vs",
    "developer powershell for vs",
    "git release notes",
    "desinstalar o lightshot",
}

FALLBACK_SCAN_ROOTS = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
    # Spotify e alguns apps ficam aqui em instalações por usuário.
    Path(os.environ.get("APPDATA", "")),
]


@dataclass
class AppCandidate:
    name: str
    exe_path: str
    process_name: str | None
    source: str
    confidence: float
    aliases: list[str]
    score: int
    reasons: list[str]


def _run_powershell_json(script: str, timeout: int = 25) -> list[dict[str, Any]]:
    """Executa um script PowerShell e tenta ler saída JSON.

    Em Linux/container isso não roda, mas no Windows do Helix roda sem dependências extras.
    """
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception:
        return []

    output = (completed.stdout or "").strip()
    if not output:
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict):
        return [data]

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    return []


def _resolve_start_menu_shortcuts() -> list[dict[str, Any]]:
    roots = [str(root) for root in COMMON_START_MENU_ROOTS if str(root)]
    roots_json = json.dumps(roots)

    script = rf"""
$roots = ConvertFrom-Json '{roots_json}'
$shell = New-Object -ComObject WScript.Shell
$items = @()
foreach ($root in $roots) {{
    if (Test-Path $root) {{
        Get-ChildItem -Path $root -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | ForEach-Object {{
            try {{
                $shortcut = $shell.CreateShortcut($_.FullName)
                $items += [PSCustomObject]@{{
                    Name = $_.BaseName
                    ShortcutPath = $_.FullName
                    TargetPath = $shortcut.TargetPath
                    Arguments = $shortcut.Arguments
                    WorkingDirectory = $shortcut.WorkingDirectory
                }}
            }} catch {{}}
        }}
    }}
}}
$items | ConvertTo-Json -Depth 4
"""

    return _run_powershell_json(script)


def _read_uninstall_registry() -> list[dict[str, Any]]:
    script = r"""
$roots = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$items = @()
foreach ($root in $roots) {
    Get-ItemProperty $root -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.DisplayName) {
            $items += [PSCustomObject]@{
                DisplayName = $_.DisplayName
                DisplayIcon = $_.DisplayIcon
                InstallLocation = $_.InstallLocation
                Publisher = $_.Publisher
            }
        }
    }
}
$items | ConvertTo-Json -Depth 4
"""
    return _run_powershell_json(script)


def _clean_display_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name


def _contains_bad_keyword(value: str) -> bool:
    normalized = normalize_app_name(value)
    text = value.lower()

    if normalized in {normalize_app_name(item) for item in INTERNAL_EXACT_NAMES}:
        return True

    return any(keyword in text or keyword in normalized for keyword in BAD_NAME_KEYWORDS)


def _is_bad_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.stem.lower()

    if name in INTERNAL_EXACT_NAMES:
        return True

    if any(part in BAD_FOLDER_PARTS for part in parts):
        return True

    return _contains_bad_keyword(path.name)


def _parse_process_from_shortcut(target_path: str | None, arguments: str | None) -> str | None:
    args = arguments or ""

    # Discord e alguns launchers usam Update.exe --processStart App.exe.
    match = re.search(r"--processStart\s+['\"]?([^'\"\s]+\.exe)", args, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()

    if target_path:
        target = Path(target_path)
        if target.suffix.lower() == ".exe" and not _contains_bad_keyword(target.name):
            return target.name

    return None


def _aliases_for_shortcut(name: str, target_path: str | None, process_name: str | None) -> list[str]:
    aliases = {name, normalize_app_name(name)}

    if process_name:
        aliases.add(process_name)
        aliases.add(Path(process_name).stem)

    if target_path:
        target = Path(target_path)
        aliases.add(target.stem)

    # Atalhos costumam vir com sufixos chatos.
    cleaned = re.sub(r"\b(shortcut|atalho)\b", "", name, flags=re.IGNORECASE).strip()
    if cleaned:
        aliases.add(cleaned)

    return sorted({alias for alias in aliases if alias})


def _is_bad_start_menu_shortcut(shortcut_path: str, name: str) -> bool:
    normalized_name = normalize_app_name(name)

    if normalized_name in BAD_START_MENU_EXACT_NAMES:
        return True

    path_text = str(shortcut_path).lower().replace("\\", "/")

    if any(f"/{folder}/" in path_text for folder in BAD_START_MENU_FOLDER_PARTS):
        return True

    return False


def _score_shortcut(item: dict[str, Any]) -> tuple[int, list[str]]:
    name = _clean_display_name(str(item.get("Name") or ""))
    shortcut_path = str(item.get("ShortcutPath") or "")
    target_path = str(item.get("TargetPath") or "")

    score = 95
    reasons = ["atalho do Menu Iniciar"]

    if not name or not shortcut_path:
        return 0, ["atalho sem nome ou caminho"]

    if _is_bad_start_menu_shortcut(shortcut_path, name):
        return 0, ["atalho administrativo/do Windows ignorado"]

    if _contains_bad_keyword(name):
        return 0, ["atalho parece instalador, updater, helper ou utilitário"]

    if target_path and _contains_bad_keyword(Path(target_path).name):
        # Não bloqueia automaticamente se o nome do atalho for humano, porque
        # launchers como Discord podem usar Update.exe por baixo. Só reduz score.
        score -= 15
        reasons.append("destino parece launcher auxiliar, mas atalho é humano")

    return max(score, 0), reasons


def _collect_start_menu_candidates() -> list[AppCandidate]:
    candidates: list[AppCandidate] = []

    for item in _resolve_start_menu_shortcuts():
        name = _clean_display_name(str(item.get("Name") or ""))
        shortcut_path = str(item.get("ShortcutPath") or "")
        target_path = str(item.get("TargetPath") or "")
        arguments = str(item.get("Arguments") or "")

        score, reasons = _score_shortcut(item)
        if score < 70:
            continue

        path = Path(shortcut_path)
        if not path.exists():
            continue

        process_name = _parse_process_from_shortcut(target_path, arguments)

        candidates.append(
            AppCandidate(
                name=name,
                exe_path=str(path),
                process_name=process_name,
                source="start_menu",
                confidence=round(score / 100, 2),
                aliases=_aliases_for_shortcut(name, target_path, process_name),
                score=score,
                reasons=reasons,
            )
        )

    return candidates


def _extract_icon_exe(display_icon: str | None) -> str | None:
    if not display_icon:
        return None

    value = os.path.expandvars(str(display_icon)).strip().strip('"')

    # DisplayIcon costuma vir como: "C:\\Path\\App.exe",0
    match = re.search(r"(.+?\.exe)", value, flags=re.IGNORECASE)
    if not match:
        return None

    candidate = Path(match.group(1).strip().strip('"'))
    if candidate.exists() and not _is_bad_path(candidate):
        return str(candidate)

    return None


def _find_main_exe_in_install_location(location: str | None, display_name: str) -> str | None:
    if not location:
        return None

    root = Path(os.path.expandvars(str(location)).strip().strip('"'))
    if not root.exists() or not root.is_dir():
        return None

    normalized_display = normalize_app_name(display_name).replace(" ", "")
    candidates = []

    try:
        for exe in root.rglob("*.exe"):
            if _is_bad_path(exe):
                continue

            normalized_exe = normalize_app_name(exe.stem).replace(" ", "")
            score = 0

            if normalized_exe and normalized_exe in normalized_display:
                score += 40
            if normalized_display and normalized_display in normalized_exe:
                score += 40
            if exe.parent == root:
                score += 20

            candidates.append((score, exe))

            if len(candidates) >= 80:
                break
    except Exception:
        return None

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_path = candidates[0]

    if best_score < 20:
        return None

    return str(best_path)


def _collect_registry_candidates() -> list[AppCandidate]:
    candidates: list[AppCandidate] = []

    for item in _read_uninstall_registry():
        name = _clean_display_name(str(item.get("DisplayName") or ""))
        if not name or _contains_bad_keyword(name):
            continue

        exe_path = _extract_icon_exe(item.get("DisplayIcon"))
        if not exe_path:
            exe_path = _find_main_exe_in_install_location(item.get("InstallLocation"), name)

        if not exe_path:
            continue

        path = Path(exe_path)
        process_name = path.name if path.suffix.lower() == ".exe" else None

        candidates.append(
            AppCandidate(
                name=name,
                exe_path=str(path),
                process_name=process_name,
                source="windows_uninstall_registry",
                confidence=0.86,
                aliases=[name, path.stem, process_name or ""],
                score=86,
                reasons=["registro de programas instalados do Windows"],
            )
        )

    return candidates


def _score_raw_exe(path: Path, root: Path) -> tuple[int, list[str]]:
    if not path.exists() or path.suffix.lower() != ".exe":
        return 0, ["não é executável"]

    if _is_bad_path(path):
        return 0, ["parece auxiliar, setup, updater, cache ou ferramenta interna"]

    score = 30
    reasons = ["executável encontrado por fallback"]

    try:
        relative_parts = path.relative_to(root).parts
        depth = len(relative_parts) - 1
    except Exception:
        depth = 99

    if depth <= 2:
        score += 25
        reasons.append("profundidade baixa em pasta de programa")

    parent_name = normalize_app_name(path.parent.name).replace(" ", "")
    exe_name = normalize_app_name(path.stem).replace(" ", "")

    if parent_name and exe_name and (parent_name in exe_name or exe_name in parent_name):
        score += 25
        reasons.append("nome do exe combina com a pasta")

    # Apps instalados por usuário, especialmente Spotify, ficam fora de Program Files.
    path_text = str(path).lower()
    if "\\spotify\\" in path_text or "/spotify/" in path_text:
        score += 35
        reasons.append("caminho típico do Spotify")

    if "\\programs\\" in path_text or "/programs/" in path_text:
        score += 15
        reasons.append("pasta Programs do usuário")

    return min(score, 95), reasons


def _iter_exes_limited(root: Path, max_depth: int, limit: int) -> list[Path]:
    results: list[Path] = []

    if not root.exists() or not root.is_dir():
        return results

    root = root.resolve()

    stack = [(root, 0)]

    while stack and len(results) < limit:
        current, depth = stack.pop()

        if depth > max_depth:
            continue

        try:
            children = list(current.iterdir())
        except Exception:
            continue

        for child in children:
            if len(results) >= limit:
                break

            try:
                if child.is_dir():
                    if child.name.lower() not in BAD_FOLDER_PARTS:
                        stack.append((child, depth + 1))
                elif child.suffix.lower() == ".exe":
                    results.append(child)
            except Exception:
                continue

    return results


def _collect_raw_exe_candidates(max_depth: int, limit: int) -> list[AppCandidate]:
    candidates: list[AppCandidate] = []
    per_root_limit = max(50, limit // max(len(FALLBACK_SCAN_ROOTS), 1))

    for root in FALLBACK_SCAN_ROOTS:
        if not root or not root.exists():
            continue

        for exe in _iter_exes_limited(root, max_depth=max_depth, limit=per_root_limit):
            score, reasons = _score_raw_exe(exe, root)
            if score < 70:
                continue

            name = exe.stem.replace("_", " ").replace("-", " ").strip()
            name = re.sub(r"\s+", " ", name).title()

            candidates.append(
                AppCandidate(
                    name=name,
                    exe_path=str(exe),
                    process_name=exe.name,
                    source="raw_exe_fallback",
                    confidence=round(score / 100, 2),
                    aliases=[name, exe.stem, exe.name],
                    score=score,
                    reasons=reasons,
                )
            )

    return candidates


def _candidate_key(candidate: AppCandidate) -> str:
    # Para atalhos, o caminho do .lnk é a melhor chave, porque abre direto.
    return str(Path(candidate.exe_path)).lower()


def _deduplicate_candidates(candidates: list[AppCandidate]) -> list[AppCandidate]:
    priority = {
        "start_menu": 3,
        "windows_uninstall_registry": 2,
        "raw_exe_fallback": 1,
    }

    best_by_key: dict[str, AppCandidate] = {}
    best_by_name: dict[str, AppCandidate] = {}

    for candidate in candidates:
        key = _candidate_key(candidate)
        name_key = normalize_app_name(candidate.name)

        current = best_by_key.get(key)
        if current is None or (priority.get(candidate.source, 0), candidate.score) > (priority.get(current.source, 0), current.score):
            best_by_key[key] = candidate

        current_name = best_by_name.get(name_key)
        if current_name is None or (priority.get(candidate.source, 0), candidate.score) > (priority.get(current_name.source, 0), current_name.score):
            best_by_name[name_key] = candidate

    merged = list(best_by_key.values())

    # Remove duplicação visual simples: mesmo nome vindo de registry e exe bruto.
    final: dict[str, AppCandidate] = {}
    for candidate in merged:
        name_key = normalize_app_name(candidate.name)
        preferred = best_by_name.get(name_key, candidate)
        final[_candidate_key(preferred)] = preferred

    return sorted(final.values(), key=lambda item: (item.source != "start_menu", item.name.lower()))


def scan_apps(db: Session, max_depth: int = 5, limit: int = 500) -> dict[str, Any]:
    errors: list[dict[str, str]] = []

    candidates: list[AppCandidate] = []

    try:
        candidates.extend(_collect_start_menu_candidates())
    except Exception as exc:
        errors.append({"source": "start_menu", "error": str(exc)})

    try:
        candidates.extend(_collect_registry_candidates())
    except Exception as exc:
        errors.append({"source": "windows_uninstall_registry", "error": str(exc)})

    try:
        remaining_limit = max(limit - len(candidates), 100)
        candidates.extend(_collect_raw_exe_candidates(max_depth=max_depth, limit=remaining_limit))
    except Exception as exc:
        errors.append({"source": "raw_exe_fallback", "error": str(exc)})

    candidates = _deduplicate_candidates(candidates)[:limit]

    saved_apps = []
    ignored_apps = []

    for candidate in candidates:
        try:
            app = upsert_known_app(
                db,
                name=candidate.name,
                exe_path=candidate.exe_path,
                process_name=candidate.process_name,
                aliases=candidate.aliases,
                app_type=guess_app_type(candidate.name, candidate.exe_path),
                source=candidate.source,
                confidence=candidate.confidence,
            )

            item = {
                "id": app.id,
                "name": candidate.name,
                "exe_path": candidate.exe_path,
                "process_name": candidate.process_name,
                "source": candidate.source,
                "score": candidate.score,
                "is_active": app.is_active,
                "reasons": candidate.reasons,
            }

            if app.is_active:
                saved_apps.append(item)
            else:
                ignored_apps.append({**item, "ignored_reason": "bloqueado pelo filtro do registro"})

        except Exception as exc:
            db.rollback()
            errors.append({"source": candidate.source, "name": candidate.name, "error": str(exc)})

    try:
        cache_result = refresh_known_apps_cache(db)
    except Exception as exc:
        cache_result = {"status": "error", "error": str(exc)}
        errors.append({"source": "cache", "error": str(exc)})

    return {
        "status": "ok",
        "scanned_files": len(candidates),
        "saved_apps": len(saved_apps),
        "ignored_apps": len(ignored_apps),
        "errors": errors,
        "cache": cache_result,
        "sources": {
            "start_menu": len([item for item in candidates if item.source == "start_menu"]),
            "windows_uninstall_registry": len([item for item in candidates if item.source == "windows_uninstall_registry"]),
            "raw_exe_fallback": len([item for item in candidates if item.source == "raw_exe_fallback"]),
        },
        "saved_preview": saved_apps[:30],
        "ignored_preview": ignored_apps[:20],
    }
