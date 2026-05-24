from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy.orm import Session

from backend.services.app_registry_service import (
    guess_app_type,
    normalize_app_name,
    refresh_known_apps_cache,
    upsert_known_app,
)


SYSTEM_ROOT = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()

PROGRAM_FILES = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
]

BLOCKED_PROCESS_NAMES = {
    "system",
    "registry",
    "idle",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "fontdrvhost.exe",
    "dwm.exe",
    "spoolsv.exe",
    "sihost.exe",
    "runtimebroker.exe",
    "searchindexer.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "securityhealthservice.exe",
    "wudfhost.exe",
    "ctfmon.exe",
    "conhost.exe",
    "dllhost.exe",
    "taskhostw.exe",
    "taskmgr.exe",
    "audiodg.exe",
}

BLOCKED_KEYWORDS = {
    "helper",
    "service",
    "updater",
    "update",
    "crash",
    "reporter",
    "errorreporter",
    "broker",
    "runtime",
    "webview",
    "proxy",
    "overlay",
    "monitor",
    "telemetry",
    "tracing",
    "installer",
    "setup",
    "uninstall",
    "autoupdate",
    "splash",
    "notification",
    "maintenance",
}

SUSPICIOUS_OR_INTERNAL_FOLDER_NAMES = {
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
}

GENERIC_EXE_NAMES = {
    "launcher.exe",
    "app.exe",
    "client.exe",
    "main.exe",
    "update.exe",
    "helper.exe",
}

KNOWN_FRIENDLY_NAMES = {
    "code.exe": "Visual Studio Code",
    "obsidian.exe": "Obsidian",
    "opera.exe": "Opera GX",
    "steam.exe": "Steam",
    "spotify.exe": "Spotify",
    "discord.exe": "Discord",
    "pgadmin4.exe": "pgAdmin 4",
    "msedge.exe": "Microsoft Edge",
    "chrome.exe": "Google Chrome",
    "firefox.exe": "Mozilla Firefox",
    "ollama.exe": "Ollama",
    "ollama app.exe": "Ollama",
}


@dataclass
class ProcessAppCandidate:
    pid: int
    name: str
    exe_path: str
    process_name: str
    cpu_percent: float
    memory_mb: float
    score: int
    reasons: list[str]
    seen_instances: int = 1


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except Exception:
        return path


def _looks_inside(path: Path, base: Path) -> bool:
    try:
        resolved_path = _safe_resolve(path)
        resolved_base = _safe_resolve(base)
        return resolved_base in resolved_path.parents or resolved_path == resolved_base
    except Exception:
        return str(path).lower().startswith(str(base).lower())


def _humanize_process_name(process_name: str, exe_path: str) -> str:
    process_lower = process_name.lower().strip()

    if process_lower in KNOWN_FRIENDLY_NAMES:
        return KNOWN_FRIENDLY_NAMES[process_lower]

    stem = Path(process_name).stem.strip()

    # Quando o exe é genérico, usar o nome da pasta costuma ser mais humano.
    if process_lower in GENERIC_EXE_NAMES and exe_path:
        parent_name = Path(exe_path).parent.name.strip()
        if parent_name:
            stem = parent_name

    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()

    if not stem:
        return process_name

    small_words = {"de", "do", "da", "dos", "das", "and", "or"}
    words = []

    for word in stem.split(" "):
        if word.lower() in small_words:
            words.append(word.lower())
        elif word.isupper():
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:])

    return " ".join(words)


def _score_running_process(process_name: str, exe_path: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    process_lower = process_name.lower().strip()
    normalized = normalize_app_name(process_name)
    path = Path(exe_path) if exe_path else None
    path_text = exe_path.lower()

    if not process_lower or process_lower in BLOCKED_PROCESS_NAMES:
        return 0, ["processo do sistema ou sem nome útil"]

    if not exe_path:
        return 0, ["processo sem caminho de executável acessível"]

    if any(keyword in process_lower or keyword in path_text for keyword in BLOCKED_KEYWORDS):
        return 0, ["parece helper, updater, serviço ou componente auxiliar"]

    if path:
        parts = {part.lower() for part in path.parts}

        if any(part in SUSPICIOUS_OR_INTERNAL_FOLDER_NAMES for part in parts):
            return 0, ["caminho parece pasta interna/cache/runtime"]

        if _looks_inside(path, SYSTEM_ROOT):
            score -= 40
            reasons.append("está dentro da pasta do Windows")

        for program_dir in PROGRAM_FILES:
            if str(program_dir) and _looks_inside(path, program_dir):
                score += 35
                reasons.append("está em uma pasta típica de programas")
                break

        parent_name = normalize_app_name(path.parent.name)
        exe_stem = normalize_app_name(path.stem)

        if parent_name and exe_stem and (exe_stem in parent_name or parent_name in exe_stem):
            score += 20
            reasons.append("nome da pasta combina com o executável")

    if process_lower in KNOWN_FRIENDLY_NAMES:
        score += 45
        reasons.append("processo principal conhecido")

    # Nomes curtos, humanos e sem sufixo técnico tendem a ser apps principais.
    if normalized and len(normalized) >= 3 and not re.search(r"\d{3,}|64$|32$", normalized):
        score += 15
        reasons.append("nome do processo parece app humano")

    # Penalidade para CLI/ferramentas técnicas comuns que aparecem rodando por acaso.
    if normalized.startswith("pg ") or normalized in {"python", "node", "git", "cmd", "powershell", "pwsh"}:
        score -= 30
        reasons.append("parece ferramenta CLI ou processo técnico")

    score = max(0, min(100, score))

    return score, reasons


def _dedup_key(candidate: ProcessAppCandidate) -> str:
    """Chave estável para evitar salvar o mesmo app 30 vezes."""
    exe_path = (candidate.exe_path or "").strip().lower()

    if exe_path:
        return exe_path

    return (candidate.process_name or candidate.name or "").strip().lower()


def _merge_candidate(existing: ProcessAppCandidate, new: ProcessAppCandidate) -> ProcessAppCandidate:
    """Mantém uma entrada por app, somando ocorrências e guardando a mais útil."""
    existing.seen_instances += new.seen_instances

    # Mantém maior consumo observado só para relatório.
    existing.memory_mb = max(existing.memory_mb, new.memory_mb)
    existing.cpu_percent = max(existing.cpu_percent, new.cpu_percent)

    # Mantém o melhor score e as razões mais completas.
    if new.score > existing.score:
        existing.score = new.score
        existing.reasons = new.reasons
        existing.pid = new.pid

    # Se o nome antigo for genérico e o novo for melhor, troca.
    generic_names = {"app", "launcher", "client", "main"}
    if normalize_app_name(existing.name) in generic_names and new.name:
        existing.name = new.name

    return existing


def _deduplicate_candidates(candidates: list[ProcessAppCandidate]) -> list[ProcessAppCandidate]:
    grouped: dict[str, ProcessAppCandidate] = {}

    for candidate in candidates:
        key = _dedup_key(candidate)

        if not key:
            continue

        if key in grouped:
            grouped[key] = _merge_candidate(grouped[key], candidate)
        else:
            grouped[key] = candidate

    unique = list(grouped.values())
    unique.sort(key=lambda item: (item.score, item.memory_mb), reverse=True)
    return unique


def collect_running_process_candidates(limit: int = 300) -> list[ProcessAppCandidate]:
    raw_candidates: list[ProcessAppCandidate] = []

    for proc in psutil.process_iter(["pid", "name", "exe", "memory_info"]):
        try:
            info = proc.info
            pid = int(info.get("pid") or 0)
            process_name = str(info.get("name") or "").strip()
            exe_path = str(info.get("exe") or "").strip()

            if not process_name or not exe_path:
                continue

            score, reasons = _score_running_process(process_name, exe_path)

            if score <= 0:
                continue

            memory_info = info.get("memory_info")
            memory_mb = 0.0

            if memory_info:
                memory_mb = round((memory_info.rss or 0) / 1024 / 1024, 2)

            # cpu_percent sem intervalo usa o último valor medido; aqui é só informativo.
            try:
                cpu_percent = float(proc.cpu_percent(interval=None))
            except Exception:
                cpu_percent = 0.0

            display_name = _humanize_process_name(process_name, exe_path)

            raw_candidates.append(
                ProcessAppCandidate(
                    pid=pid,
                    name=display_name,
                    exe_path=exe_path,
                    process_name=process_name,
                    cpu_percent=cpu_percent,
                    memory_mb=memory_mb,
                    score=score,
                    reasons=reasons,
                )
            )

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue

    unique_candidates = _deduplicate_candidates(raw_candidates)
    return unique_candidates[:limit]


def learn_apps_from_running_processes(
    db: Session,
    *,
    min_score: int = 70,
    limit: int = 300,
    refresh_cache: bool = True,
) -> dict[str, Any]:
    """
    Aprende caminhos de apps a partir dos processos rodando agora.

    Não fecha nada, não apaga nada e não mexe em arquivos do PC.
    Apenas atualiza o registro known_apps quando o processo parece um app principal.
    """
    candidates = collect_running_process_candidates(limit=limit)

    learned = []
    ignored = []
    errors = []
    saved_keys: set[str] = set()

    for candidate in candidates:
        item = {
            "pid": candidate.pid,
            "name": candidate.name,
            "exe_path": candidate.exe_path,
            "process_name": candidate.process_name,
            "score": candidate.score,
            "memory_mb": candidate.memory_mb,
            "cpu_percent": candidate.cpu_percent,
            "seen_instances": candidate.seen_instances,
            "reasons": candidate.reasons,
        }

        if candidate.score < min_score:
            ignored.append(item)
            continue

        key = _dedup_key(candidate)

        if key in saved_keys:
            # Camada extra de proteção caso o coletor mude no futuro.
            ignored.append({**item, "ignored_reason": "duplicado no mesmo ciclo"})
            continue

        saved_keys.add(key)

        try:
            app = upsert_known_app(
                db,
                name=candidate.name,
                exe_path=candidate.exe_path,
                process_name=candidate.process_name,
                aliases=[
                    candidate.process_name,
                    Path(candidate.process_name).stem,
                    candidate.name,
                ],
                app_type=guess_app_type(candidate.name, candidate.exe_path),
                source="process_scanner",
                confidence=round(candidate.score / 100, 2),
            )

            item["app_id"] = app.id
            learned.append(item)

        except Exception as exc:
            db.rollback()
            item["error"] = str(exc)
            errors.append(item)

    if refresh_cache:
        try:
            refresh_known_apps_cache(db)
        except Exception as exc:
            errors.append({"error": f"Falha ao atualizar cache: {exc}"})

    return {
        "status": "ok",
        "scanned_processes": len(candidates),
        "learned_count": len(learned),
        "ignored_count": len(ignored),
        "error_count": len(errors),
        "learned": learned,
        "ignored_preview": ignored[:20],
        "errors": errors[:20],
        "updated_at": datetime.now().isoformat(),
    }


def build_process_learning_summary(result: dict[str, Any], max_items: int = 8) -> str:
    learned = result.get("learned", []) or []

    if not learned:
        return (
            "\n\nAprendizado de processos: não encontrei nenhum app novo confiável rodando agora. "
            "Nada foi alterado além da verificação."
        )

    lines = [
        "\n\nAprendizado de processos:",
        f"- Processos candidatos únicos analisados: `{result.get('scanned_processes', 0)}`",
        f"- Apps aprendidos/atualizados: `{result.get('learned_count', 0)}`",
    ]

    lines.append("\nApps atualizados no registro:")

    for item in learned[:max_items]:
        instances = item.get("seen_instances", 1)
        instance_text = f" — instâncias `{instances}`" if instances and instances > 1 else ""

        lines.append(
            f"- {item.get('name')} — `{item.get('process_name')}` — score `{item.get('score')}`{instance_text}"
        )

    if len(learned) > max_items:
        lines.append(f"- ... e mais {len(learned) - max_items} app(s).")

    return "\n".join(lines)
