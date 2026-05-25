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
# 2. Área de Trabalho (.lnk)      -> fonte muito confiável para apps usados.
# 3. Registro de instalados       -> bom, mas sujo; exige cautela.
# 4. Scan bruto de .exe           -> fallback, com filtro pesado.
#
# O objetivo não é salvar qualquer .exe que existe no PC.
# O objetivo é alimentar o known_apps com coisas que o usuário provavelmente
# espera abrir pelo Helix.
# -----------------------------------------------------------------------------


BAD_NAME_KEYWORDS = {
    "installer",
    "install",
    "uninstall",
    "uninstaller",
    "uninst",
    "desinstalar",
    "desinstalador",
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

    # CLI/tools que geralmente não são apps gráficos principais
    "rar",
    "unrar",
}


SUSPICIOUS_EXE_NAMES = {
    "launcher.exe",
    "update.exe",
    "updater.exe",
    "helper.exe",
    "service.exe",
    "log-uploader.exe",
    "log_uploader.exe",
    "compatibilitytool.exe",
    "amdsoftwarecompatibilitytool.exe",
}


COMMON_START_MENU_ROOTS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]


COMMON_DESKTOP_ROOTS = [
    Path(os.environ.get("USERPROFILE", "")) / "Desktop",
    Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
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

    # Caminho que o Helix deve usar para abrir.
    # Pode ser um .lnk do Menu Iniciar/Desktop ou um .exe direto.
    launch_path: str

    # Caminho real do executável, quando conhecido.
    target_path: str | None

    # Caminho do atalho, quando o candidato veio de .lnk.
    shortcut_path: str | None

    # Nome do processo esperado, ex: Spotify.exe, Discord.exe, Code.exe.
    process_name: str | None

    # Origem: start_menu, desktop, windows_uninstall_registry, raw_exe_fallback.
    source: str

    # Tipo: shortcut, app_principal, launcher, helper, updater, uninstaller, unknown.
    candidate_type: str

    # Tipo lógico usado pelo app_registry: browser, music, dev_tool etc.
    app_type: str | None

    # Apelidos/nomes alternativos usados para busca.
    aliases: list[str]

    # Scores separados.
    app_confidence: int
    launch_quality: int
    user_relevance: int
    risk_score: int
    final_score: int

    # Compatibilidade com app_registry atual.
    confidence: float

    # Decisão do scanner.
    is_launcher_candidate: bool
    is_blocked: bool
    requires_confirmation: bool

    # Explicação.
    reasons: list[str]
    penalties: list[str]
    blocked_reason: str | None = None


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


def _resolve_shortcuts(roots: list[Path]) -> list[dict[str, Any]]:
    roots_clean = [str(root) for root in roots if root and str(root)]
    roots_json = json.dumps(roots_clean)

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


def _resolve_start_menu_shortcuts() -> list[dict[str, Any]]:
    return _resolve_shortcuts(COMMON_START_MENU_ROOTS)


def _resolve_desktop_shortcuts() -> list[dict[str, Any]]:
    return _resolve_shortcuts(COMMON_DESKTOP_ROOTS)


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


def _is_suspicious_exe_name(path: Path) -> bool:
    name = path.name.lower()
    compact_name = name.replace("-", "").replace("_", "").replace(" ", "")
    return name in SUSPICIOUS_EXE_NAMES or compact_name in {
        item.replace("-", "").replace("_", "").replace(" ", "")
        for item in SUSPICIOUS_EXE_NAMES
    }


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


def _is_bad_shortcut(shortcut_path: str, name: str) -> bool:
    normalized_name = normalize_app_name(name)

    if normalized_name in BAD_START_MENU_EXACT_NAMES:
        return True

    path_text = str(shortcut_path).lower().replace("\\", "/")

    if any(f"/{folder}/" in path_text for folder in BAD_START_MENU_FOLDER_PARTS):
        return True

    return False


def _score_shortcut(item: dict[str, Any], source: str) -> tuple[int, list[str], list[str]]:
    name = _clean_display_name(str(item.get("Name") or ""))
    shortcut_path = str(item.get("ShortcutPath") or "")
    target_path = str(item.get("TargetPath") or "")

    if source == "desktop":
        score = 92
        reasons = ["atalho da Área de Trabalho"]
    else:
        score = 95
        reasons = ["atalho do Menu Iniciar"]

    penalties: list[str] = []

    if not name or not shortcut_path:
        return 0, ["atalho sem nome ou caminho"], []

    if _is_bad_shortcut(shortcut_path, name):
        return 0, ["atalho administrativo/do Windows ignorado"], []

    if _contains_bad_keyword(name):
        return 0, ["atalho parece instalador, updater, helper ou utilitário"], []

    if target_path:
        target = Path(target_path)

        if _contains_bad_keyword(target.name):
            # Não bloqueia automaticamente se o nome do atalho for humano,
            # porque launchers como Discord podem usar Update.exe por baixo.
            score -= 15
            penalties.append("destino parece launcher auxiliar, mas atalho é humano")

        if _is_suspicious_exe_name(target):
            score -= 10
            penalties.append("executável de destino tem nome genérico/suspeito")

    return max(score, 0), reasons, penalties


def _candidate_type_from_path(path: str | None, fallback: str = "app_principal") -> str:
    if not path:
        return fallback

    p = Path(path)
    name = p.name.lower()

    if any(word in name for word in ["uninstall", "uninst", "desinstalar"]):
        return "uninstaller"

    if any(word in name for word in ["update", "updater", "autoupdate"]):
        return "updater"

    if any(word in name for word in ["helper", "service", "broker"]):
        return "helper"

    if "launcher" in name:
        return "launcher"

    return fallback


def _collect_shortcut_candidates(
    items: list[dict[str, Any]],
    source: str,
) -> list[AppCandidate]:
    candidates: list[AppCandidate] = []

    for item in items:
        name = _clean_display_name(str(item.get("Name") or ""))
        shortcut_path = str(item.get("ShortcutPath") or "")
        target_path = str(item.get("TargetPath") or "")
        arguments = str(item.get("Arguments") or "")

        score, reasons, penalties = _score_shortcut(item, source=source)
        if score < 70:
            continue

        shortcut = Path(shortcut_path)
        if not shortcut.exists():
            continue

        process_name = _parse_process_from_shortcut(target_path, arguments)
        candidate_type = _candidate_type_from_path(target_path, fallback="shortcut")

        risk_score = 5
        if penalties:
            risk_score += 10

        candidates.append(
            AppCandidate(
                name=name,
                launch_path=str(shortcut),
                target_path=target_path or None,
                shortcut_path=shortcut_path or str(shortcut),
                process_name=process_name,
                source=source,
                candidate_type=candidate_type,
                app_type=None,
                aliases=_aliases_for_shortcut(name, target_path, process_name),
                app_confidence=score,
                launch_quality=95 if source == "start_menu" else 92,
                user_relevance=55 if source == "desktop" else 50,
                risk_score=risk_score,
                final_score=score,
                confidence=round(score / 100, 2),
                is_launcher_candidate=True,
                is_blocked=False,
                requires_confirmation=score < 85,
                reasons=reasons,
                penalties=penalties,
                blocked_reason=None,
            )
        )

    return candidates


def _collect_start_menu_candidates() -> list[AppCandidate]:
    return _collect_shortcut_candidates(
        items=_resolve_start_menu_shortcuts(),
        source="start_menu",
    )


def _collect_desktop_candidates() -> list[AppCandidate]:
    return _collect_shortcut_candidates(
        items=_resolve_desktop_shortcuts(),
        source="desktop",
    )


def _extract_icon_exe(display_icon: str | None) -> str | None:
    if not display_icon:
        return None

    value = os.path.expandvars(str(display_icon)).strip().strip('"')

    # DisplayIcon costuma vir como:
    # "C:\\Path\\App.exe",0
    match = re.search(r"(.+?\.exe)", value, flags=re.IGNORECASE)
    if not match:
        return None

    raw_path = match.group(1).strip().strip('"')
    candidate = Path(raw_path)

    try:
        if not candidate.exists():
            return None

        if _is_bad_path(candidate):
            return None

        if _contains_bad_keyword(candidate.name):
            return None

        return str(candidate)

    except (PermissionError, OSError):
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

            if _is_suspicious_exe_name(exe):
                score -= 25

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

        if _is_bad_path(path) or _contains_bad_keyword(path.name):
            continue

        process_name = path.name if path.suffix.lower() == ".exe" else None

        penalties = ["fonte menos confiável que Menu Iniciar"]
        app_confidence = 78
        launch_quality = 75
        user_relevance = 40
        risk_score = 20
        final_score = 76
        requires_confirmation = True

        if _is_suspicious_exe_name(path):
            penalties.append("executável genérico/suspeito vindo do registro")
            launch_quality -= 10
            risk_score += 15
            final_score -= 15

        final_score = max(final_score, 0)
        confidence = round(final_score / 100, 2)

        candidates.append(
            AppCandidate(
                name=name,
                launch_path=str(path),
                target_path=str(path),
                shortcut_path=None,
                process_name=process_name,
                source="windows_uninstall_registry",
                candidate_type=_candidate_type_from_path(str(path), fallback="app_principal"),
                app_type=None,
                aliases=[alias for alias in [name, path.stem, process_name or ""] if alias],
                app_confidence=app_confidence,
                launch_quality=launch_quality,
                user_relevance=user_relevance,
                risk_score=risk_score,
                final_score=final_score,
                confidence=confidence,
                is_launcher_candidate=final_score >= 60,
                is_blocked=False,
                requires_confirmation=requires_confirmation,
                reasons=["registro de programas instalados do Windows"],
                penalties=penalties,
                blocked_reason=None,
            )
        )

    return candidates


def _score_raw_exe(path: Path, root: Path) -> tuple[int, list[str], list[str]]:
    if not path.exists() or path.suffix.lower() != ".exe":
        return 0, ["não é executável"], []

    if _is_bad_path(path):
        return 0, ["parece auxiliar, setup, updater, cache ou ferramenta interna"], []

    score = 30
    reasons = ["executável encontrado por fallback"]
    penalties: list[str] = []

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

    path_text = str(path).lower()

    # Apps instalados por usuário, especialmente Spotify, ficam fora de Program Files.
    if "\\spotify\\" in path_text or "/spotify/" in path_text:
        score += 35
        reasons.append("caminho típico do Spotify")

    if "\\programs\\" in path_text or "/programs/" in path_text:
        score += 15
        reasons.append("pasta Programs do usuário")

    if "\\windowsapps\\" in path_text or "/windowsapps/" in path_text:
        score -= 10
        penalties.append("WindowsApps pode exigir abertura por atalho/URI")

    if _is_suspicious_exe_name(path):
        score -= 20
        penalties.append("executável genérico/suspeito")

    return min(max(score, 0), 95), reasons, penalties


def _iter_exes_limited(root: Path, max_depth: int, limit: int) -> list[Path]:
    results: list[Path] = []

    if not root.exists() or not root.is_dir():
        return results

    try:
        root = root.resolve()
    except Exception:
        return results

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
            score, reasons, penalties = _score_raw_exe(exe, root)
            if score < 70:
                continue

            name = exe.stem.replace("_", " ").replace("-", " ").strip()
            name = re.sub(r"\s+", " ", name).title()

            risk_score = 15
            if penalties:
                risk_score += 10

            candidates.append(
                AppCandidate(
                    name=name,
                    launch_path=str(exe),
                    target_path=str(exe),
                    shortcut_path=None,
                    process_name=exe.name,
                    source="raw_exe_fallback",
                    candidate_type=_candidate_type_from_path(str(exe), fallback="app_principal"),
                    app_type=None,
                    aliases=[name, exe.stem, exe.name],
                    app_confidence=score,
                    launch_quality=score,
                    user_relevance=30,
                    risk_score=risk_score,
                    final_score=score,
                    confidence=round(score / 100, 2),
                    is_launcher_candidate=score >= 70,
                    is_blocked=False,
                    requires_confirmation=True,
                    reasons=reasons,
                    penalties=penalties,
                    blocked_reason=None,
                )
            )

    return candidates


def _candidate_key(candidate: AppCandidate) -> str:
    return str(Path(candidate.launch_path)).lower()


def _deduplicate_candidates(candidates: list[AppCandidate]) -> list[AppCandidate]:
    priority = {
        "start_menu": 4,
        "desktop": 3,
        "windows_uninstall_registry": 2,
        "raw_exe_fallback": 1,
    }

    best_by_key: dict[str, AppCandidate] = {}
    best_by_name: dict[str, AppCandidate] = {}

    for candidate in candidates:
        key = _candidate_key(candidate)
        name_key = normalize_app_name(candidate.name)

        current = best_by_key.get(key)
        if current is None or (
            priority.get(candidate.source, 0),
            candidate.final_score,
        ) > (
            priority.get(current.source, 0),
            current.final_score,
        ):
            best_by_key[key] = candidate

        current_name = best_by_name.get(name_key)
        if current_name is None or (
            priority.get(candidate.source, 0),
            candidate.final_score,
        ) > (
            priority.get(current_name.source, 0),
            current_name.final_score,
        ):
            best_by_name[name_key] = candidate

    merged = list(best_by_key.values())

    # Remove duplicação visual simples: mesmo nome vindo de registry e exe bruto.
    final: dict[str, AppCandidate] = {}
    for candidate in merged:
        name_key = normalize_app_name(candidate.name)
        preferred = best_by_name.get(name_key, candidate)
        final[_candidate_key(preferred)] = preferred

    return sorted(
        final.values(),
        key=lambda item: (
            item.source != "start_menu",
            item.source != "desktop",
            item.name.lower(),
        ),
    )


def scan_apps(db: Session, max_depth: int = 5, limit: int = 500) -> dict[str, Any]:
    errors: list[dict[str, str]] = []

    candidates: list[AppCandidate] = []

    try:
        candidates.extend(_collect_start_menu_candidates())
    except Exception as exc:
        errors.append({"source": "start_menu", "error": str(exc)})

    try:
        candidates.extend(_collect_desktop_candidates())
    except Exception as exc:
        errors.append({"source": "desktop", "error": str(exc)})

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
                exe_path=candidate.launch_path,
                process_name=candidate.process_name,
                aliases=candidate.aliases,
                app_type=candidate.app_type or guess_app_type(candidate.name, candidate.launch_path),
                source=candidate.source,
                confidence=candidate.confidence,
            )

            item = {
                "id": app.id,
                "name": candidate.name,

                # Compatibilidade com o app_registry atual.
                "exe_path": candidate.launch_path,

                # Novo modelo rico do scanner.
                "launch_path": candidate.launch_path,
                "target_path": candidate.target_path,
                "shortcut_path": candidate.shortcut_path,

                "process_name": candidate.process_name,
                "source": candidate.source,
                "candidate_type": candidate.candidate_type,
                "app_type": candidate.app_type,

                "app_confidence": candidate.app_confidence,
                "launch_quality": candidate.launch_quality,
                "user_relevance": candidate.user_relevance,
                "risk_score": candidate.risk_score,
                "final_score": candidate.final_score,

                # Compatibilidade visual antiga.
                "score": candidate.final_score,

                "confidence": candidate.confidence,
                "is_launcher_candidate": candidate.is_launcher_candidate,
                "is_blocked": candidate.is_blocked,
                "requires_confirmation": candidate.requires_confirmation,
                "is_active": app.is_active,

                "aliases": candidate.aliases,
                "reasons": candidate.reasons,
                "penalties": candidate.penalties,
                "blocked_reason": candidate.blocked_reason,
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
            "desktop": len([item for item in candidates if item.source == "desktop"]),
            "windows_uninstall_registry": len(
                [item for item in candidates if item.source == "windows_uninstall_registry"]
            ),
            "raw_exe_fallback": len([item for item in candidates if item.source == "raw_exe_fallback"]),
        },
        "saved_preview": saved_apps[:30],
        "ignored_preview": ignored_apps[:20],
    }