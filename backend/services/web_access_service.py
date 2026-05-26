from __future__ import annotations

import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus, unquote, urlparse
from urllib.request import Request, urlopen


# ============================================================
# Helix Web Access Service - Fase Web v4
#
# Recursos:
# - Lê páginas permitidas em modo somente leitura.
# - Pesquisa na web.
# - Prioriza fontes oficiais por assunto.
# - Resume melhor fonte.
# - Monta resposta técnica aplicada ao Helix.
# - Entrega payload estruturado para rotas /web.
#
# Regras:
# - Não baixa arquivos.
# - Não instala nada.
# - Não executa nada.
# - Não envia formulário.
# - Não usa login/senha/token.
# ============================================================

REQUEST_TIMEOUT_SECONDS = 8
SEARCH_TIMEOUT_SECONDS = 8

MAX_PAGE_BYTES = 700_000
MAX_EXTRACTED_CHARS = 14_000
MAX_SEARCH_RESULTS = 5

ALLOWED_DOMAINS = {
    # Docs / programação
    "docs.python.org",
    "fastapi.tiangolo.com",
    "docs.sqlalchemy.org",
    "www.postgresql.org",
    "postgresql.org",
    "pydantic.dev",
    "developer.mozilla.org",
    "react.dev",
    "vite.dev",
    "tailwindcss.com",
    "docs.github.com",
    "github.com",
    "code.visualstudio.com",
    "learn.microsoft.com",

    # IA / pesquisa
    "openai.com",
    "platform.openai.com",
    "ollama.com",
    "huggingface.co",
    "arxiv.org",
    "paperswithcode.com",
    "pytorch.org",
    "www.tensorflow.org",
    "tensorflow.org",
    "scikit-learn.org",

    # Obsidian / produtividade
    "help.obsidian.md",

    # Consulta geral segura
    "wikipedia.org",
    "pt.wikipedia.org",
    "en.wikipedia.org",
}

BLOCKED_EXTENSIONS = {
    ".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".scr",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".dll", ".iso", ".apk",
    ".py", ".js", ".jar",
}

SENSITIVE_KEYWORDS = {
    "login",
    "signin",
    "signup",
    "checkout",
    "payment",
    "token",
    "apikey",
    "api-key",
    "password",
    "senha",
}

NOISY_PHRASES = [
    "skip to content",
    "join the fastapi cloud waiting list",
    "follow @",
    "follow fastapi",
    "newsletter",
    "sponsor",
    "sponsors",
    "gold sponsors",
    "silver sponsors",
    "keystone sponsor",
    "search",
    "cookie",
    "privacy policy",
    "terms of service",
    "edit this page",
    "previous",
    "next",
    "on this page",
    "source code",
]

MENU_KEYWORDS = [
    "features",
    "learn",
    "reference",
    "resources",
    "about",
    "release notes",
    "path parameters",
    "query parameters",
    "request body",
    "response model",
    "middleware",
    "security",
    "deployment",
    "testing",
    "websockets",
    "openapi",
]

PRACTICAL_SUMMARY_KEYWORDS = [
    "is used to",
    "used to",
    "allows",
    "lets you",
    "you can",
    "define",
    "create",
    "validate",
    "validation",
    "serialize",
    "serialization",
    "data",
    "model",
    "request",
    "response",
    "example",
    "usage",
    "how to",
    "helps",
    "provides",
    "represents",
    "serves",
    "configure",
    "organize",
    "structure",
    "include",
    "import",
    "class",
    "function",
]

TECHNICAL_NOISE_KEYWORDS = [
    "__",
    "deprecated",
    "metadata",
    "generic",
    "alias",
    "aliases",
    "internals",
    "private",
    "attribute",
    "attributes",
    "parameter item",
    "origin and args",
    "trusted or pre-validated",
    "will not work",
    "replaces",
    "root_validators",
    "validators",
    "the open group",
    "base specifications",
    "paragraph",
]

SEARCH_RESULT_BLOCKED_DOMAINS = {
    "duckduckgo.com",
    "www.duckduckgo.com",
}

OFFICIAL_SOURCE_MAP = {
    "fastapi": [
        "fastapi.tiangolo.com",
    ],
    "pydantic": [
        "pydantic.dev",
    ],
    "python": [
        "docs.python.org",
    ],
    "sqlalchemy": [
        "docs.sqlalchemy.org",
    ],
    "postgres": [
        "www.postgresql.org",
        "postgresql.org",
    ],
    "postgresql": [
        "www.postgresql.org",
        "postgresql.org",
    ],
    "javascript": [
        "developer.mozilla.org",
    ],
    "html": [
        "developer.mozilla.org",
    ],
    "css": [
        "developer.mozilla.org",
    ],
    "mdn": [
        "developer.mozilla.org",
    ],
    "react": [
        "react.dev",
    ],
    "vite": [
        "vite.dev",
    ],
    "tailwind": [
        "tailwindcss.com",
    ],
    "github": [
        "docs.github.com",
        "github.com",
    ],
    "openai": [
        "platform.openai.com",
        "openai.com",
    ],
    "ollama": [
        "ollama.com",
    ],
    "obsidian": [
        "help.obsidian.md",
    ],
    "vscode": [
        "code.visualstudio.com",
    ],
    "visual studio code": [
        "code.visualstudio.com",
    ],
}


@dataclass
class WebFetchResult:
    ok: bool
    url: str
    title: str | None = None
    text: str | None = None
    headings: list[str] | None = None
    links: list[str] | None = None
    reason: str | None = None
    domain: str | None = None
    risk: str = "low"
    bytes_read: int = 0


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str
    domain: str | None = None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()

        self._skip_depth = 0
        self._skip_tags = {"script", "style", "noscript", "svg", "canvas"}

        self.title: str | None = None
        self._in_title = False

        self._current_heading: str | None = None
        self._heading_parts: list[str] = []
        self.headings: list[str] = []

        self._current_block_tag: str | None = None
        self._current_block_parts: list[str] = []
        self.blocks: list[str] = []

        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()

        if tag in self._skip_tags:
            self._skip_depth += 1

        if tag == "title":
            self._in_title = True

        if tag in {"h1", "h2", "h3"}:
            self._current_heading = tag
            self._heading_parts = []

        if tag in {"p", "li", "h1", "h2", "h3", "h4", "blockquote"}:
            self._flush_block()
            self._current_block_tag = tag
            self._current_block_parts = []

        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href")
            if href and href.startswith(("http://", "https://")):
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1

        if tag == "title":
            self._in_title = False

        if tag in {"h1", "h2", "h3"} and self._current_heading:
            heading = " ".join(" ".join(self._heading_parts).split()).strip()
            heading = clean_heading(heading)

            if heading and heading not in self.headings and not is_noise_line(heading):
                self.headings.append(heading)

            self._current_heading = None
            self._heading_parts = []

        if self._current_block_tag == tag:
            self._flush_block()

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())

        if not clean:
            return

        if self._in_title:
            self.title = clean
            return

        if self._skip_depth > 0:
            return

        if self._current_heading:
            self._heading_parts.append(clean)

        if self._current_block_tag:
            self._current_block_parts.append(clean)

    def _flush_block(self) -> None:
        if not self._current_block_parts:
            self._current_block_tag = None
            return

        block = " ".join(" ".join(self._current_block_parts).split()).strip()
        block = clean_block(block)

        if is_useful_block(block):
            self.blocks.append(block)

        self._current_block_tag = None
        self._current_block_parts = []

    def get_text(self) -> str:
        self._flush_block()
        blocks = dedupe_blocks(self.blocks)
        return "\n".join(blocks)[:MAX_EXTRACTED_CHARS]


class DuckDuckGoHTMLSearchParser(HTMLParser):
    def __init__(self):
        super().__init__()

        self.results: list[WebSearchResult] = []

        self._inside_result_link = False
        self._inside_snippet = False

        self._current_url = ""
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class", "") or ""

        if tag == "a" and "result__a" in class_name:
            self._inside_result_link = True
            self._current_url = attrs_dict.get("href", "") or ""
            self._current_title_parts = []
            self._current_snippet_parts = []

        if tag in {"a", "div"} and "result__snippet" in class_name:
            self._inside_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._inside_result_link:
            self._inside_result_link = False

            title = clean_block(" ".join(self._current_title_parts))
            url = self._clean_duckduckgo_url(self._current_url)

            if title and url:
                domain = get_domain(url)

                if domain not in SEARCH_RESULT_BLOCKED_DOMAINS:
                    self.results.append(
                        WebSearchResult(
                            title=title,
                            url=url,
                            snippet="",
                            domain=domain,
                        )
                    )

        if tag in {"a", "div"} and self._inside_snippet:
            self._inside_snippet = False

            snippet = clean_block(" ".join(self._current_snippet_parts))

            if snippet and self.results:
                last = self.results[-1]

                if not last.snippet:
                    last.snippet = snippet

    def handle_data(self, data: str) -> None:
        if self._inside_result_link:
            self._current_title_parts.append(data)

        if self._inside_snippet:
            self._current_snippet_parts.append(data)

    def _clean_duckduckgo_url(self, url: str) -> str:
        if not url:
            return ""

        url = url.strip()

        if url.startswith("//"):
            url = "https:" + url

        if url.startswith("/l/?"):
            url = "https://duckduckgo.com" + url

        if "duckduckgo.com/l/?" in url and "uddg=" in url:
            parsed = urlparse(url)
            query_parts = parsed.query.split("&")

            for part in query_parts:
                if part.startswith("uddg="):
                    return unquote(part.replace("uddg=", "", 1))

        return url


def clean_heading(text: str) -> str:
    text = text.replace("¶", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def clean_block(text: str) -> str:
    text = text.replace("¶", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def is_noise_line(line: str) -> bool:
    lowered = line.lower().strip()

    if not lowered:
        return True

    if any(phrase in lowered for phrase in NOISY_PHRASES):
        return True

    language_hits = sum(
        token in lowered
        for token in [
            "english", "deutsch", "español", "français", "日本語",
            "한국어", "português", "русский", "中文",
        ]
    )

    if language_hits >= 2:
        return True

    return False


def looks_like_menu_dump(line: str) -> bool:
    lowered = line.lower()
    menu_hits = sum(1 for keyword in MENU_KEYWORDS if keyword in lowered)

    if menu_hits >= 6 and len(line) > 350:
        return True

    if len(line) > 900:
        return True

    words = line.split()

    if len(words) > 90 and line.count(".") <= 2:
        return True

    return False


def is_useful_block(block: str) -> bool:
    if not block:
        return False

    if is_noise_line(block):
        return False

    if looks_like_menu_dump(block):
        return False

    if len(block) < 35:
        return False

    has_sentence_signal = any(mark in block for mark in [".", ":", ";", "—", "-"])
    has_technical_signal = any(
        word in block.lower()
        for word in [
            "fastapi", "python", "framework", "api", "documentation",
            "install", "example", "openapi", "pydantic", "database",
            "async", "security", "deployment", "model", "dataset",
            "postgresql", "sqlalchemy", "obsidian", "github", "react",
            "hook", "router", "validation", "request", "response",
        ]
    )

    if not has_sentence_signal and not has_technical_signal:
        return False

    return True


def dedupe_blocks(blocks: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for block in blocks:
        normalized = re.sub(r"\W+", " ", block.lower()).strip()

        if normalized in seen:
            continue

        if any(normalized and normalized in old for old in seen):
            continue

        seen.add(normalized)
        result.append(block)

    return result


def normalize_domain(domain: str) -> str:
    domain = domain.lower().strip()

    if domain.startswith("www."):
        return domain[4:]

    return domain


def get_domain(url: str) -> str | None:
    try:
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return None

        if not parsed.netloc:
            return None

        return normalize_domain(parsed.netloc)

    except Exception:
        return None


def is_domain_allowed(url: str) -> bool:
    domain = get_domain(url)

    if not domain:
        return False

    allowed_normalized = {normalize_domain(item) for item in ALLOWED_DOMAINS}

    if domain in allowed_normalized:
        return True

    for allowed in allowed_normalized:
        if domain.endswith("." + allowed):
            return True

    return False


def classify_url_risk(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    path = parsed.path.lower()
    lowered_url = url.lower()

    extension_risk = any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS)
    sensitive_risk = any(keyword in lowered_url for keyword in SENSITIVE_KEYWORDS)

    if extension_risk:
        return {
            "risk": "blocked",
            "reason": "A URL parece apontar para download/arquivo executável ou compactado.",
        }

    if sensitive_risk:
        return {
            "risk": "medium",
            "reason": "A URL parece envolver login, senha, token, pagamento ou área sensível.",
        }

    if not is_domain_allowed(url):
        return {
            "risk": "blocked",
            "reason": "Domínio não está na lista de leitura permitida do Helix.",
        }

    return {
        "risk": "low",
        "reason": "URL permitida para leitura básica.",
    }


def extract_url_from_message(message: str) -> str | None:
    match = re.search(r"https?://[^\s)>\]]+", message)

    if match:
        return match.group(0).strip().rstrip(".,;")

    return None


def fetch_page_text(url: str) -> WebFetchResult:
    risk_info = classify_url_risk(url)
    domain = get_domain(url)

    if risk_info["risk"] == "blocked":
        return WebFetchResult(
            ok=False,
            url=url,
            domain=domain,
            risk="blocked",
            reason=risk_info["reason"],
        )

    try:
        socket.setdefaulttimeout(REQUEST_TIMEOUT_SECONDS)

        request = Request(
            url,
            headers={
                "User-Agent": (
                    "HelixLocalAssistant/0.1 "
                    "(read-only research; local personal assistant)"
                ),
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            },
            method="GET",
        )

        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type and "text/plain" not in content_type:
                return WebFetchResult(
                    ok=False,
                    url=url,
                    domain=domain,
                    risk=risk_info["risk"],
                    reason=f"Tipo de conteúdo não permitido para leitura básica: {content_type}",
                )

            raw = response.read(MAX_PAGE_BYTES + 1)

        if len(raw) > MAX_PAGE_BYTES:
            raw = raw[:MAX_PAGE_BYTES]

        html = raw.decode("utf-8", errors="replace")

        parser = _TextExtractor()
        parser.feed(html)

        text = parser.get_text()
        headings = [
            heading for heading in parser.headings
            if 3 <= len(heading) <= 100 and not is_noise_line(heading)
        ][:10]
        links = list(dict.fromkeys(parser.links))[:8]

        if not text:
            return WebFetchResult(
                ok=False,
                url=url,
                domain=domain,
                risk=risk_info["risk"],
                bytes_read=len(raw),
                reason="A página foi acessada, mas não consegui extrair texto útil depois dos filtros.",
            )

        return WebFetchResult(
            ok=True,
            url=url,
            domain=domain,
            title=parser.title,
            text=text,
            headings=headings,
            links=links,
            risk=risk_info["risk"],
            bytes_read=len(raw),
            reason=risk_info["reason"],
        )

    except Exception as exc:
        return WebFetchResult(
            ok=False,
            url=url,
            domain=domain,
            risk=risk_info["risk"],
            reason=f"Erro ao acessar página: {type(exc).__name__}: {exc}",
        )


def score_block(block: str, domain: str | None) -> int:
    lowered = block.lower()
    score = 0

    strong_keywords = [
        "fastapi", "python", "framework", "api", "openapi", "type hints",
        "pydantic", "async", "database", "sqlalchemy", "postgresql",
        "security", "deployment", "testing", "model", "dataset", "agent",
        "memory", "rag", "obsidian", "github", "react", "hook",
        "router", "validation", "request", "response",
    ]

    for keyword in strong_keywords:
        if keyword in lowered:
            score += 3

    if 80 <= len(block) <= 420:
        score += 3
    elif len(block) > 700:
        score -= 4

    if "." in block:
        score += 1

    if ":" in block:
        score += 1

    if looks_like_menu_dump(block):
        score -= 10

    if any(phrase in lowered for phrase in NOISY_PHRASES):
        score -= 8

    return score


def score_practical_summary_block(block: str, domain: str | None = None) -> int:
    text = block.lower().strip()
    score = 0

    if not text:
        return -999

    length = len(text)

    if 80 <= length <= 420:
        score += 20
    elif 40 <= length < 80:
        score += 8
    elif length > 650:
        score -= 20

    for keyword in PRACTICAL_SUMMARY_KEYWORDS:
        if keyword in text:
            score += 8

    for keyword in TECHNICAL_NOISE_KEYWORDS:
        if keyword in text:
            score -= 18

    if text.count("__") >= 1:
        score -= 35

    if text.count("(") >= 4 or text.count(")") >= 4:
        score -= 10

    if text.count("{") >= 1 or text.count("}") >= 1:
        score -= 10

    if looks_like_menu_dump(text):
        score -= 30

    word_count = len(text.split())

    if word_count < 8:
        score -= 15

    if domain in {
        "fastapi.tiangolo.com",
        "pydantic.dev",
        "docs.python.org",
        "docs.sqlalchemy.org",
        "react.dev",
        "developer.mozilla.org",
    }:
        score += 5

    return score


def build_simple_summary(text: str, domain: str | None = None, max_items: int = 5) -> list[str]:
    blocks = [line.strip() for line in text.splitlines() if line.strip()]
    blocks = [block for block in blocks if is_useful_block(block)]

    if not blocks:
        return ["Consegui acessar a página, mas os filtros não encontraram parágrafos claros para resumir."]

    ranked = sorted(blocks, key=lambda item: score_block(item, domain), reverse=True)

    selected: list[str] = []

    for block in ranked:
        if len(block) > 420:
            block = block[:420].rsplit(" ", 1)[0].strip() + "..."

        if block not in selected:
            selected.append(block)

        if len(selected) >= max_items:
            break

    return selected


def build_practical_summary(text: str, domain: str | None = None, max_items: int = 6) -> list[str]:
    blocks = dedupe_blocks([
        clean_block(block)
        for block in re.split(r"\n+|(?<=[.!?])\s+", text)
        if clean_block(block)
    ])

    scored_blocks: list[tuple[int, str]] = []

    for block in blocks:
        if not is_useful_block(block):
            continue

        score = score_practical_summary_block(block, domain)

        if score <= 0:
            continue

        scored_blocks.append((score, block))

    scored_blocks.sort(key=lambda item: item[0], reverse=True)

    selected: list[str] = []

    for _, block in scored_blocks:
        if block in selected:
            continue

        selected.append(block)

        if len(selected) >= max_items:
            break

    if selected:
        return selected

    return build_simple_summary(text, domain, max_items=max_items)


def build_usefulness_notes(result: WebFetchResult) -> list[str]:
    domain = result.domain or ""
    text = (result.text or "").lower()
    notes: list[str] = []

    if "fastapi" in domain or "fastapi" in text:
        notes.extend([
            "Revisar a organização de rotas e separar melhor endpoints em routers.",
            "Verificar uso correto de Pydantic, CORS, lifespan, testes e deploy.",
            "Usar a documentação como referência para melhorar `/chat`, `/tts`, `/system` e futuros endpoints.",
        ])

    if "sqlalchemy" in domain or "sqlalchemy" in text:
        notes.extend([
            "Melhorar a camada de banco, sessões, queries e models do PostgreSQL.",
        ])

    if "postgresql" in domain or "postgresql" in text:
        notes.extend([
            "Pesquisar otimização, backup, índices e estrutura da memória do Helix.",
        ])

    if "huggingface" in domain or "model" in text or "dataset" in text:
        notes.extend([
            "Catalogar modelos, datasets e ideias de IA sem baixar nada automaticamente.",
        ])

    if "obsidian" in domain or "obsidian" in text:
        notes.extend([
            "Melhorar a integração com o Helix Brain e organização das notas.",
        ])

    if "github.com" in domain:
        notes.extend([
            "Ler README, issues e exemplos de implementação sem clonar ou executar código.",
        ])

    if not notes:
        notes.append("Usar como fonte de consulta, mas validar antes de transformar em decisão no projeto.")

    return list(dict.fromkeys(notes))[:4]


def is_web_search_intent(message: str) -> bool:
    text = message.lower().strip()

    search_triggers = [
        "pesquise na internet",
        "pesquisar na internet",
        "pesquisa na internet",
        "procure na internet",
        "procurar na internet",
        "busque na internet",
        "buscar na internet",
        "pesquise na web",
        "pesquisar na web",
        "procure na web",
        "busque na web",
        "pesquise sobre",
        "pesquisar sobre",
        "pesquisa sobre",
        "procure sobre",
        "buscar sobre",
        "busque sobre",
    ]

    return any(trigger in text for trigger in search_triggers)


def clean_search_query(query: str) -> str:
    query = query.strip()

    suffix_patterns = [
        r"\s+e\s+resuma\s*$",
        r"\s+e\s+resume\s*$",
        r"\s+e\s+leia\s*$",
        r"\s+e\s+ler\s*$",
        r"\s+e\s+explique\s*$",
        r"\s+e\s+me\s+explique\s*$",
        r"\s+e\s+resuma\s+a\s+melhor\s+fonte\s*$",
        r"\s+e\s+leia\s+a\s+melhor\s+fonte\s*$",
        r"\s+resuma\s+a\s+melhor\s+fonte\s*$",
        r"\s+leia\s+a\s+melhor\s+fonte\s*$",
        r"\s+resuma\s+o\s+melhor\s+resultado\s*$",
        r"\s+leia\s+o\s+melhor\s+resultado\s*$",
    ]

    for pattern in suffix_patterns:
        query = re.sub(pattern, "", query, flags=re.IGNORECASE).strip()

    query = re.sub(r"[?.!]+$", "", query).strip()

    return query


def extract_search_query(message: str) -> str:
    text = message.strip()

    patterns = [
        r"pesquise na internet sobre\s+(.+)",
        r"pesquisar na internet sobre\s+(.+)",
        r"pesquisa na internet sobre\s+(.+)",
        r"procure na internet sobre\s+(.+)",
        r"procurar na internet sobre\s+(.+)",
        r"busque na internet sobre\s+(.+)",
        r"buscar na internet sobre\s+(.+)",
        r"pesquise na web sobre\s+(.+)",
        r"pesquisar na web sobre\s+(.+)",
        r"procure na web sobre\s+(.+)",
        r"busque na web sobre\s+(.+)",
        r"pesquise sobre\s+(.+)",
        r"pesquisar sobre\s+(.+)",
        r"pesquisa sobre\s+(.+)",
        r"procure sobre\s+(.+)",
        r"buscar sobre\s+(.+)",
        r"busque sobre\s+(.+)",
    ]

    lowered = text.lower()

    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)

        if match:
            query = text[match.start(1):].strip()
            return clean_search_query(query)

    return ""


def fetch_web_search_results(query: str) -> list[WebSearchResult]:
    query = query.strip()

    if not query:
        return []

    search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"

    request = Request(
        search_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urlopen(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
            raw = response.read(400_000)

    except Exception as exc:
        print(f"Erro ao pesquisar na web: {exc}")
        return []

    html = raw.decode("utf-8", errors="ignore")

    parser = DuckDuckGoHTMLSearchParser()
    parser.feed(html)

    unique_results: list[WebSearchResult] = []
    seen_urls: set[str] = set()

    for result in parser.results:
        if not result.url or result.url in seen_urls:
            continue

        seen_urls.add(result.url)
        unique_results.append(result)

        if len(unique_results) >= MAX_SEARCH_RESULTS:
            break

    return unique_results


def get_expected_official_domains(query: str) -> list[str]:
    query_lower = query.lower()
    expected_domains: list[str] = []

    for keyword, domains in OFFICIAL_SOURCE_MAP.items():
        if keyword in query_lower:
            expected_domains.extend(domains)

    unique_domains: list[str] = []
    seen: set[str] = set()

    for domain in expected_domains:
        normalized = normalize_domain(domain)

        if normalized in seen:
            continue

        seen.add(normalized)
        unique_domains.append(normalized)

    return unique_domains


def score_search_result_for_summary(result: WebSearchResult, query: str) -> int:
    score = 0

    domain = (result.domain or "").lower()
    title = (result.title or "").lower()
    url = (result.url or "").lower()
    snippet = (result.snippet or "").lower()
    query_lower = query.lower()

    expected_official_domains = get_expected_official_domains(query)

    general_official_domains = [
        "fastapi.tiangolo.com",
        "pydantic.dev",
        "docs.python.org",
        "docs.sqlalchemy.org",
        "postgresql.org",
        "developer.mozilla.org",
        "react.dev",
        "vite.dev",
        "tailwindcss.com",
        "docs.github.com",
        "learn.microsoft.com",
        "platform.openai.com",
        "openai.com",
        "ollama.com",
        "help.obsidian.md",
        "code.visualstudio.com",
    ]

    lower_quality_domains = [
        "medium.com",
        "geeksforgeeks.org",
        "datacamp.com",
    ]

    if domain in expected_official_domains:
        score += 90

    elif domain in general_official_domains:
        score += 45

    if any(part in url for part in ["/docs", "/documentation", "/tutorial", "/reference", "/learn", "/guide"]):
        score += 18

    if "docs" in title or "documentation" in title:
        score += 14

    if "reference" in title or "api" in title:
        score += 10

    if "tutorial" in title or "guide" in title:
        score += 8

    query_words = [
        word
        for word in re.split(r"\W+", query_lower)
        if len(word) >= 4
    ]

    for word in query_words:
        if word in title:
            score += 8

        if word in url:
            score += 5

        if word in snippet:
            score += 3

    if domain in lower_quality_domains:
        score -= 25

    if "medium.com" in url:
        score -= 20

    if "login" in url or "signin" in url or "signup" in url:
        score -= 30

    return score


def web_search_result_to_dict(result: WebSearchResult) -> dict[str, Any]:
    return {
        "title": result.title,
        "url": result.url,
        "domain": result.domain,
        "snippet": result.snippet,
    }


def rank_web_search_results(query: str, results: list[WebSearchResult]) -> list[WebSearchResult]:
    return sorted(
        results,
        key=lambda item: score_search_result_for_summary(item, query),
        reverse=True,
    )


def get_source_type(query: str, domain: str | None) -> str:
    expected_domains = get_expected_official_domains(query)

    if (domain or "").lower() in expected_domains:
        return "fonte oficial esperada"

    return "melhor fonte encontrada"


def wants_search_and_summary(message: str) -> bool:
    text = message.lower().strip()

    summary_triggers = [
        "e resuma",
        "e resume",
        "e leia",
        "e ler",
        "resuma a melhor fonte",
        "resuma o melhor resultado",
        "leia a melhor fonte",
        "leia o melhor resultado",
        "resuma a fonte oficial",
        "resuma automaticamente",
        "me dê um resumo",
        "me de um resumo",
    ]

    return any(trigger in text for trigger in summary_triggers)


def wants_technical_answer(message: str) -> bool:
    text = message.lower().strip()

    technical_triggers = [
        "me explique",
        "explique",
        "explica",
        "me ensine",
        "ensine",
        "como funciona",
        "como usar",
        "para que serve",
        "o que é",
        "o que e",
        "resposta prática",
        "resposta tecnica",
        "resposta técnica",
    ]

    return any(trigger in text for trigger in technical_triggers)


def build_helix_application_notes(query: str) -> str:
    query_lower = query.lower()

    if "fastapi" in query_lower and ("router" in query_lower or "apirouter" in query_lower):
        return (
            "- Separar rotas do Helix em arquivos próprios deixa o backend mais organizado.\n"
            "- `/chat` pode ficar em `chat_routes.py`.\n"
            "- `/system` pode ficar em `system_routes.py`.\n"
            "- `/apps` pode ficar em `app_registry_routes.py`.\n"
            "- Futuramente, `/web/search` e `/web/read` poderiam ficar em `web_routes.py`.\n"
        )

    if "pydantic" in query_lower or "basemodel" in query_lower:
        return (
            "- Usar `BaseModel` ajuda a validar entradas dos endpoints do Helix.\n"
            "- Com isso, comandos, mensagens, buscas web e configurações ficam mais previsíveis.\n"
            "- Também melhora a documentação automática do FastAPI.\n"
        )

    if "pathlib" in query_lower:
        return (
            "- `pathlib` pode deixar os módulos de arquivos do Helix mais limpos.\n"
            "- É útil para scanner de projetos, leitura de pastas, Obsidian Vault e manipulação segura de caminhos.\n"
            "- Também reduz gambiarra com string de caminho no Windows. E isso, sinceramente, já é terapia.\n"
        )

    if "react" in query_lower and "hook" in query_lower:
        return (
            "- Hooks podem organizar estados do frontend do Helix, como chat, voz, orb, sistema e modo web.\n"
            "- `useState` pode cuidar de estados simples.\n"
            "- `useEffect` pode buscar status do backend e atualizar painéis.\n"
            "- Hooks customizados podem separar lógica como `useHelixChat`, `useSystemStatus` e `useVoiceMode`.\n"
        )

    return (
        "- Esse conteúdo pode servir como referência técnica para decisões futuras do Helix.\n"
        "- O ideal é transformar o aprendizado em uma melhoria concreta no código, rota, serviço ou arquitetura.\n"
    )


def build_web_page_response(result: WebFetchResult) -> str:
    if not result.ok:
        return (
            "Não consegui acessar essa página com segurança.\n\n"
            f"URL: `{result.url}`\n"
            f"Domínio: `{result.domain or 'desconhecido'}`\n"
            f"Risco: `{result.risk}`\n"
            f"Motivo: {result.reason}"
        )

    title = result.title or "sem título detectado"
    text = result.text or ""
    headings = result.headings or []

    summary_items = build_simple_summary(text, result.domain, max_items=5)
    usefulness_notes = build_usefulness_notes(result)

    response = (
        "Acessei a página em modo somente leitura.\n\n"
        f"URL: `{result.url}`\n"
        f"Domínio: `{result.domain}`\n"
        f"Título: {title}\n"
        f"Bytes lidos: {result.bytes_read}\n\n"
    )

    if headings:
        response += "Seções úteis detectadas:\n"

        for heading in headings[:6]:
            response += f"- {heading}\n"

        response += "\n"

    response += "Resumo limpo:\n"

    for item in summary_items:
        response += f"- {item}\n"

    response += "\nPossível utilidade para o Helix:\n"

    for note in usefulness_notes:
        response += f"- {note}\n"

    return response


def build_web_search_response(query: str, results: list[WebSearchResult]) -> str:
    if not results:
        return (
            "Não encontrei resultados úteis para essa pesquisa.\n\n"
            f"Busca: `{query}`\n\n"
            "Pode ser bloqueio do mecanismo de busca, termo muito genérico ou o HTML da busca mudou. "
            "A internet sendo a internet: uma bagunça com protocolo."
        )

    response = (
        "Pesquisei na web e encontrei estes resultados:\n\n"
        f"Busca: `{query}`\n\n"
    )

    for index, result in enumerate(results, start=1):
        response += f"{index}. **{result.title}**\n"
        response += f"   - Domínio: `{result.domain or 'desconhecido'}`\n"
        response += f"   - URL: `{result.url}`\n"

        if result.snippet:
            response += f"   - Resumo: {result.snippet}\n"

        response += "\n"

    response += "Posso ler/resumir um desses links depois, se você mandar a URL específica."

    return response.strip()


def build_search_and_summary_response(query: str, results: list[WebSearchResult]) -> str:
    if not results:
        return build_web_search_response(query, results)

    ranked_results = rank_web_search_results(query, results)
    best = ranked_results[0]

    page_result = fetch_page_text(best.url)

    if not page_result.ok:
        response = (
            "Pesquisei na web, mas não consegui ler a melhor fonte com segurança.\n\n"
            f"Busca: `{query}`\n\n"
            "Melhor resultado encontrado:\n"
            f"- **{best.title}**\n"
            f"- Domínio: `{best.domain or 'desconhecido'}`\n"
            f"- URL: `{best.url}`\n\n"
            f"Motivo da falha ao ler: {page_result.reason}\n\n"
            "Resultados alternativos:\n"
        )

        for index, result in enumerate(ranked_results[1:4], start=1):
            response += (
                f"{index}. **{result.title}** — `{result.domain or 'desconhecido'}`\n"
                f"   - URL: `{result.url}`\n"
            )

        return response.strip()

    summary_items = build_practical_summary(
        page_result.text or "",
        page_result.domain,
        max_items=6,
    )

    source_note = get_source_type(query, best.domain)

    response = (
        "Pesquisei na web e resumi a melhor fonte que encontrei.\n\n"
        f"Busca: `{query}`\n"
        f"Fonte escolhida: **{best.title}**\n"
        f"Tipo de fonte: {source_note}\n"
        f"Domínio: `{best.domain or page_result.domain or 'desconhecido'}`\n"
        f"URL: `{best.url}`\n\n"
        "Resumo:\n"
    )

    for item in summary_items:
        response += f"- {item}\n"

    response += "\nOutras fontes encontradas:\n"

    for index, result in enumerate(ranked_results[1:4], start=1):
        response += (
            f"{index}. **{result.title}** — `{result.domain or 'desconhecido'}`\n"
            f"   - URL: `{result.url}`\n"
        )

    return response.strip()


def build_technical_web_answer(query: str, results: list[WebSearchResult]) -> str:
    if not results:
        return build_web_search_response(query, results)

    ranked_results = rank_web_search_results(query, results)
    best = ranked_results[0]

    page_result = fetch_page_text(best.url)

    if not page_result.ok:
        return (
            "Pesquisei na web, achei uma fonte promissora, mas não consegui ler a página com segurança.\n\n"
            f"Busca: `{query}`\n"
            f"Fonte encontrada: **{best.title}**\n"
            f"Domínio: `{best.domain or 'desconhecido'}`\n"
            f"URL: `{best.url}`\n\n"
            f"Motivo: {page_result.reason}"
        )

    summary_items = build_practical_summary(
        page_result.text or "",
        page_result.domain,
        max_items=6,
    )

    source_note = get_source_type(query, best.domain)

    response = (
        "Pesquisei na web e montei uma resposta técnica com base na melhor fonte.\n\n"
        f"Busca: `{query}`\n"
        f"Fonte usada: **{best.title}**\n"
        f"Tipo de fonte: {source_note}\n"
        f"Domínio: `{best.domain or page_result.domain or 'desconhecido'}`\n"
        f"URL: `{best.url}`\n\n"
        "Resumo prático:\n"
    )

    for item in summary_items[:3]:
        response += f"- {item}\n"

    response += "\nPontos importantes:\n"

    for item in summary_items[3:6]:
        response += f"- {item}\n"

    response += "\nComo isso pode se aplicar ao Helix:\n"
    response += build_helix_application_notes(query)

    response += "\nOutras fontes encontradas:\n"

    for index, result in enumerate(ranked_results[1:4], start=1):
        response += (
            f"{index}. **{result.title}** — `{result.domain or 'desconhecido'}`\n"
            f"   - URL: `{result.url}`\n"
        )

    return response.strip()


def build_search_summary_payload(query: str, results: list[WebSearchResult]) -> dict[str, Any]:
    if not results:
        return {
            "ok": False,
            "query": query,
            "count": 0,
            "source": None,
            "summary": [],
            "other_sources": [],
            "response": build_web_search_response(query, results),
            "reason": "Nenhum resultado útil encontrado.",
        }

    ranked_results = rank_web_search_results(query, results)
    best = ranked_results[0]

    page_result = fetch_page_text(best.url)

    if not page_result.ok:
        return {
            "ok": False,
            "query": query,
            "count": len(results),
            "source": web_search_result_to_dict(best),
            "summary": [],
            "other_sources": [
                web_search_result_to_dict(item)
                for item in ranked_results[1:4]
            ],
            "response": build_search_and_summary_response(query, results),
            "reason": page_result.reason,
        }

    summary_items = build_practical_summary(
        page_result.text or "",
        page_result.domain,
        max_items=6,
    )

    source = web_search_result_to_dict(best)
    source["type"] = get_source_type(query, best.domain)

    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "source": source,
        "summary": summary_items,
        "other_sources": [
            web_search_result_to_dict(item)
            for item in ranked_results[1:4]
        ],
        "response": build_search_and_summary_response(query, results),
        "reason": None,
    }


def build_technical_web_answer_payload(query: str, results: list[WebSearchResult]) -> dict[str, Any]:
    if not results:
        return {
            "ok": False,
            "query": query,
            "count": 0,
            "source": None,
            "summary": [],
            "helix_notes": [],
            "other_sources": [],
            "response": build_web_search_response(query, results),
            "reason": "Nenhum resultado útil encontrado.",
        }

    ranked_results = rank_web_search_results(query, results)
    best = ranked_results[0]

    page_result = fetch_page_text(best.url)

    if not page_result.ok:
        return {
            "ok": False,
            "query": query,
            "count": len(results),
            "source": web_search_result_to_dict(best),
            "summary": [],
            "helix_notes": [],
            "other_sources": [
                web_search_result_to_dict(item)
                for item in ranked_results[1:4]
            ],
            "response": build_technical_web_answer(query, results),
            "reason": page_result.reason,
        }

    summary_items = build_practical_summary(
        page_result.text or "",
        page_result.domain,
        max_items=6,
    )

    helix_notes_text = build_helix_application_notes(query)
    helix_notes = [
        line.strip("- ").strip()
        for line in helix_notes_text.splitlines()
        if line.strip()
    ]

    source = web_search_result_to_dict(best)
    source["type"] = get_source_type(query, best.domain)

    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "source": source,
        "summary": summary_items,
        "helix_notes": helix_notes,
        "other_sources": [
            web_search_result_to_dict(item)
            for item in ranked_results[1:4]
        ],
        "response": build_technical_web_answer(query, results),
        "reason": None,
    }


def infer_web_mode_from_message(message: str) -> str | None:
    """
    Infere o modo web a partir da mensagem natural do usuário.

    Retornos:
    - read
    - search
    - summary
    - explain
    - None
    """

    url = extract_url_from_message(message)

    if url:
        return "read"

    if not is_web_search_intent(message):
        return None

    if wants_technical_answer(message):
        return "explain"

    if wants_search_and_summary(message):
        return "summary"

    return "search"


def handle_web_chat_intent(message: str) -> str | None:
    """
    Handler principal para o /chat usar o motor web.

    - detecta modo
    - extrai URL/query
    - executa leitura/busca/resumo/explicação
    """

    mode = infer_web_mode_from_message(message)

    if not mode:
        return None

    if mode == "read":
        lowered = message.lower()
        url = extract_url_from_message(message)

        if not url:
            return None

        trigger_words = [
            "leia",
            "ler",
            "consulta",
            "consulte",
            "acessa",
            "acesse",
            "abre",
            "abra",
            "olha",
            "veja",
            "resume",
            "resuma",
            "o que tem",
            "o que diz",
        ]

        if not any(word in lowered for word in trigger_words):
            return None

        result = fetch_page_text(url)
        return build_web_page_response(result)

    query = extract_search_query(message)

    if not query:
        return "Entendi que você quer usar a web, mas não achei o termo da busca."

    results = fetch_web_search_results(query)

    if mode == "explain":
        return build_technical_web_answer(query, results)

    if mode == "summary":
        return build_search_and_summary_response(query, results)

    if mode == "search":
        return build_web_search_response(query, results)

    return None


def handle_web_access_intent(message: str) -> str | None:
    """
    Compatibilidade com o chat_service atual.

    Internamente delega para handle_web_chat_intent.
    """

    return handle_web_chat_intent(message)