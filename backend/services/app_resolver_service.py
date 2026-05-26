from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.orm import Session

from backend.models.known_app import KnownApp


ARTICLES_AND_NOISE = {
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "uns",
    "umas",
    "app",
    "aplicativo",
    "programa",
    "software",
    "abrir",
    "abre",
    "iniciar",
    "inicia",
    "executar",
    "executa",
    "rodar",
    "roda",
}


INTENT_ALIASES = {
    "navegador": [
        "opera gx",
        "opera",
        "google chrome",
        "chrome",
        "microsoft edge",
        "edge",
        "firefox",
    ],
    "browser": [
        "opera gx",
        "opera",
        "google chrome",
        "chrome",
        "microsoft edge",
        "edge",
        "firefox",
    ],
    "internet": [
        "opera gx",
        "opera",
        "google chrome",
        "chrome",
        "microsoft edge",
        "edge",
        "firefox",
    ],
    "musica": [
        "spotify",
    ],
    "música": [
        "spotify",
    ],
    "player": [
        "spotify",
        "vlc",
    ],
    "notas": [
        "obsidian",
        "notepad",
        "bloco de notas",
    ],
    "nota": [
        "obsidian",
        "notepad",
        "bloco de notas",
    ],
    "segundo cerebro": [
        "obsidian",
    ],
    "segundo cérebro": [
        "obsidian",
    ],
    "editor": [
        "visual studio code",
        "vscode",
        "code",
        "notepad++",
        "notepad",
    ],
    "codigo": [
        "visual studio code",
        "vscode",
        "code",
    ],
    "código": [
        "visual studio code",
        "vscode",
        "code",
    ],
    "terminal": [
        "windows terminal",
        "powershell",
        "cmd",
    ],
    "prompt": [
        "cmd",
        "powershell",
        "windows terminal",
    ],
    "calculadora": [
        "calculator",
        "calculadora",
    ],
}


PREFERRED_APP_BY_INTENT = {
    "navegador": "opera gx",
    "browser": "opera gx",
    "internet": "opera gx",
    "musica": "spotify",
    "música": "spotify",
    "player": "spotify",
    "notas": "obsidian",
    "nota": "obsidian",
    "segundo cerebro": "obsidian",
    "segundo cérebro": "obsidian",
    "editor": "visual studio code",
    "codigo": "visual studio code",
    "código": "visual studio code",
    "terminal": "windows terminal",
}


DANGEROUS_OR_SENSITIVE_KEYWORDS = {
    "regedit",
    "registry editor",
    "editor do registro",
    "powershell ise",
    "disk management",
    "gerenciamento de disco",
    "services",
    "servicos",
    "serviços",
    "uninstall",
    "desinstalar",
    "uninstaller",
    "desinstalador",
}


SOURCE_PRIORITY = {
    "manual": 100,
    "start_menu": 90,
    "desktop": 85,
    "scanner": 75,
    "windows_uninstall_registry": 60,
    "raw_exe_fallback": 45,
}


@dataclass
class AppResolveCandidate:
    app: KnownApp
    score: int
    match_score: int
    source_score: int
    confidence_score: int
    reason: str


@dataclass
class AppResolveResult:
    found: bool
    query: str
    cleaned_query: str
    status: str
    app: KnownApp | None = None
    candidates: list[AppResolveCandidate] | None = None
    message: str | None = None
    requires_confirmation: bool = False


def normalize_text(text: str | None) -> str:
    if not text:
        return ""

    text = str(text).strip().lower()

    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")

    text = re.sub(r"[^a-z0-9\s\+\#\.\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def clean_app_target(target: str | None) -> str:
    normalized = normalize_text(target)

    if not normalized:
        return ""

    words = normalized.split()
    cleaned_words = [word for word in words if word not in ARTICLES_AND_NOISE]

    return " ".join(cleaned_words).strip()


def _split_aliases(raw_aliases: Any) -> list[str]:
    if not raw_aliases:
        return []

    if isinstance(raw_aliases, list):
        return [str(item) for item in raw_aliases if str(item).strip()]

    if isinstance(raw_aliases, tuple):
        return [str(item) for item in raw_aliases if str(item).strip()]

    if isinstance(raw_aliases, str):
        parts = re.split(r"[,;|]", raw_aliases)
        return [part.strip() for part in parts if part.strip()]

    return []


def _similarity(a: str, b: str) -> int:
    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return 0

    if a == b:
        return 100

    if a in b or b in a:
        shorter = min(len(a), len(b))
        longer = max(len(a), len(b))

        if shorter >= 4:
            return max(88, int((shorter / longer) * 100))

    return int(SequenceMatcher(None, a, b).ratio() * 100)


def _alias_queries(cleaned_query: str) -> list[str]:
    queries = [cleaned_query]

    if cleaned_query in INTENT_ALIASES:
        queries.extend(INTENT_ALIASES[cleaned_query])

    for alias, targets in INTENT_ALIASES.items():
        if alias in cleaned_query:
            queries.extend(targets)

    seen = set()
    unique_queries = []

    for query in queries:
        normalized = normalize_text(query)

        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_queries.append(normalized)

    return unique_queries


def _is_sensitive_app(app: KnownApp) -> bool:
    fields = [
        getattr(app, "name", None),
        getattr(app, "normalized_name", None),
        getattr(app, "exe_path", None),
        getattr(app, "process_name", None),
        getattr(app, "app_type", None),
        getattr(app, "source", None),
    ]

    haystack = normalize_text(" ".join(str(field) for field in fields if field))

    return any(keyword in haystack for keyword in DANGEROUS_OR_SENSITIVE_KEYWORDS)


def _app_names_for_matching(app: KnownApp) -> list[str]:
    names = []

    for field in ["name", "normalized_name", "process_name"]:
        value = getattr(app, field, None)

        if value:
            names.append(str(value))

    for alias in _split_aliases(getattr(app, "aliases", None)):
        names.append(alias)

    exe_path = getattr(app, "exe_path", None)

    if exe_path:
        exe_name = str(exe_path).replace("\\", "/").split("/")[-1]

        if exe_name:
            names.append(exe_name)
            names.append(exe_name.replace(".exe", ""))

    seen = set()
    result = []

    for name in names:
        normalized = normalize_text(name)

        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


def _preferred_app_bonus(app: KnownApp, cleaned_query: str) -> int:
    preferred_name = PREFERRED_APP_BY_INTENT.get(cleaned_query)

    if not preferred_name:
        return 0

    app_names = _app_names_for_matching(app)
    preferred_normalized = normalize_text(preferred_name)

    for name in app_names:
        if name == preferred_normalized:
            return 18

        if preferred_normalized in name or name in preferred_normalized:
            return 14

    return 0


def _is_preferred_candidate(
    candidate: AppResolveCandidate,
    cleaned_query: str,
) -> bool:
    preferred_name = PREFERRED_APP_BY_INTENT.get(cleaned_query)

    if not preferred_name:
        return False

    preferred_normalized = normalize_text(preferred_name)
    app_names = _app_names_for_matching(candidate.app)

    for name in app_names:
        if name == preferred_normalized:
            return True

        if preferred_normalized in name or name in preferred_normalized:
            return True

    return False


def _score_app(app: KnownApp, query_options: list[str]) -> AppResolveCandidate | None:
    names = _app_names_for_matching(app)

    if not names:
        return None

    best_match = 0
    best_reason = ""

    for query in query_options:
        for name in names:
            score = _similarity(query, name)

            if score > best_match:
                best_match = score
                best_reason = f"match '{query}' com '{name}'"

    if best_match < 45:
        return None

    source = getattr(app, "source", None) or ""
    source_score = SOURCE_PRIORITY.get(source, 50)

    confidence = getattr(app, "confidence", None)

    try:
        confidence_score = int(float(confidence) * 100)
    except Exception:
        confidence_score = 60

    is_active = bool(getattr(app, "is_active", True))

    cleaned_original_query = query_options[0] if query_options else ""

    final_score = int(
        (best_match * 0.62)
        + (source_score * 0.22)
        + (confidence_score * 0.16)
    )

    final_score += _preferred_app_bonus(app, cleaned_original_query)

    if not is_active:
        final_score -= 25

    if _is_sensitive_app(app):
        final_score -= 20

    if getattr(app, "requires_confirmation", False):
        final_score -= 5

    final_score = max(0, min(100, final_score))

    return AppResolveCandidate(
        app=app,
        score=final_score,
        match_score=best_match,
        source_score=source_score,
        confidence_score=confidence_score,
        reason=best_reason,
    )


def _candidate_identity(candidate: AppResolveCandidate) -> str:
    app = candidate.app

    normalized_name = normalize_text(getattr(app, "normalized_name", None))
    name = normalize_text(getattr(app, "name", None))
    process_name = normalize_text(getattr(app, "process_name", None))

    all_names = _app_names_for_matching(app)
    names_blob = " ".join(all_names)

    # Agrupamentos especiais para apps que aparecem duplicados com nomes diferentes.
    if "opera gx" in names_blob or (
        "opera" in names_blob and "opera.exe" in names_blob
    ):
        return "opera gx"

    if "obsidian" in names_blob:
        return "obsidian"

    if "spotify" in names_blob:
        return "spotify"

    if (
        "visual studio code" in names_blob
        or "vscode" in names_blob
        or "code.exe" in names_blob
    ):
        return "visual studio code"

    if "microsoft edge" in names_blob or "msedge" in names_blob:
        return "microsoft edge"

    if normalized_name:
        return normalized_name

    if name:
        return name

    if process_name:
        return process_name.replace(".exe", "")

    exe_path = getattr(app, "exe_path", None)

    if exe_path:
        exe_name = str(exe_path).replace("\\", "/").split("/")[-1]
        return normalize_text(exe_name).replace(".exe", "")

    return str(getattr(app, "id", ""))


def _deduplicate_resolve_candidates(
    candidates: list[AppResolveCandidate],
) -> list[AppResolveCandidate]:
    best_by_identity: dict[str, AppResolveCandidate] = {}

    for candidate in candidates:
        identity = _candidate_identity(candidate)

        current = best_by_identity.get(identity)

        if current is None:
            best_by_identity[identity] = candidate
            continue

        candidate_source_score = SOURCE_PRIORITY.get(
            getattr(candidate.app, "source", "") or "",
            50,
        )
        current_source_score = SOURCE_PRIORITY.get(
            getattr(current.app, "source", "") or "",
            50,
        )

        candidate_name_len = len(
            normalize_text(getattr(candidate.app, "name", ""))
        )
        current_name_len = len(
            normalize_text(getattr(current.app, "name", ""))
        )

        candidate_is_better = (
            candidate.score > current.score
            or (
                candidate.score == current.score
                and candidate_source_score > current_source_score
            )
            or (
                candidate.score == current.score
                and candidate_source_score == current_source_score
                and candidate_name_len > current_name_len
            )
        )

        if candidate_is_better:
            best_by_identity[identity] = candidate

    result = list(best_by_identity.values())
    result.sort(key=lambda item: item.score, reverse=True)

    return result


def _load_known_apps(db: Session) -> list[KnownApp]:
    return (
        db.query(KnownApp)
        .filter(KnownApp.is_active == True)  # noqa: E712
        .all()
    )


def resolve_app_target(target: str, db: Session) -> AppResolveResult:
    cleaned_query = clean_app_target(target)

    if not cleaned_query:
        return AppResolveResult(
            found=False,
            query=target,
            cleaned_query="",
            status="empty",
            message="Não encontrei um nome de aplicativo no comando.",
            candidates=[],
        )

    query_options = _alias_queries(cleaned_query)
    apps = _load_known_apps(db)

    scored: list[AppResolveCandidate] = []

    for app in apps:
        candidate = _score_app(app, query_options)

        if candidate:
            scored.append(candidate)

    scored.sort(key=lambda item: item.score, reverse=True)
    scored = _deduplicate_resolve_candidates(scored)

    top = scored[:5]

    if not top:
        return AppResolveResult(
            found=False,
            query=target,
            cleaned_query=cleaned_query,
            status="not_found",
            message=f"Não encontrei nenhum aplicativo parecido com '{cleaned_query}'.",
            candidates=[],
        )

    best = top[0]
    second = top[1] if len(top) > 1 else None

    if best.score < 60:
        return AppResolveResult(
            found=False,
            query=target,
            cleaned_query=cleaned_query,
            status="low_confidence",
            message=f"Encontrei candidatos fracos para '{cleaned_query}', mas nenhum confiável o bastante.",
            candidates=top,
        )

    if second and best.score - second.score <= 6:
        if not _is_preferred_candidate(best, cleaned_query):
            return AppResolveResult(
                found=False,
                query=target,
                cleaned_query=cleaned_query,
                status="ambiguous",
                message=f"Encontrei mais de um aplicativo parecido com '{cleaned_query}'.",
                candidates=top,
                requires_confirmation=True,
            )

    requires_confirmation = (
        best.score < 78
        or bool(getattr(best.app, "requires_confirmation", False))
        or _is_sensitive_app(best.app)
    )

    return AppResolveResult(
        found=True,
        query=target,
        cleaned_query=cleaned_query,
        status="resolved",
        app=best.app,
        candidates=top,
        message=f"Aplicativo resolvido: {best.app.name}",
        requires_confirmation=requires_confirmation,
    )


def resolve_app_target_as_dict(target: str, db: Session) -> dict[str, Any]:
    result = resolve_app_target(target, db)

    def app_to_dict(app: KnownApp | None) -> dict[str, Any] | None:
        if app is None:
            return None

        return {
            "id": app.id,
            "name": app.name,
            "normalized_name": app.normalized_name,
            "aliases": app.aliases,
            "exe_path": app.exe_path,
            "process_name": app.process_name,
            "app_type": app.app_type,
            "source": app.source,
            "confidence": app.confidence,
            "is_active": app.is_active,
        }

    return {
        "found": result.found,
        "query": result.query,
        "cleaned_query": result.cleaned_query,
        "status": result.status,
        "requires_confirmation": result.requires_confirmation,
        "message": result.message,
        "app": app_to_dict(result.app),
        "candidates": [
            {
                "app": app_to_dict(candidate.app),
                "score": candidate.score,
                "match_score": candidate.match_score,
                "source_score": candidate.source_score,
                "confidence_score": candidate.confidence_score,
                "reason": candidate.reason,
            }
            for candidate in (result.candidates or [])
        ],
    }