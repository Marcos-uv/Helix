from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from backend.services.web_access_service import (
    fetch_page_text,
    build_web_page_response,
    fetch_web_search_results,
    build_web_search_response,
    build_search_and_summary_response,
    build_technical_web_answer,
    build_search_summary_payload,
    build_technical_web_answer_payload,
)


router = APIRouter(
    prefix="/web",
    tags=["web"],
)


class WebReadRequest(BaseModel):
    url: str


class WebSearchRequest(BaseModel):
    query: str


class WebExplainRequest(BaseModel):
    query: str
    
class WebAskRequest(BaseModel):
    query: str
    mode: str = "search"

@router.get("/health")
def web_health():
    return {
        "status": "ok",
        "service": "web",
        "features": [
            "read_url",
            "search_web",
            "summarize_best_source",
            "technical_explanation",
        ],
    }


@router.post("/read")
def read_web_page(payload: WebReadRequest):
    result = fetch_page_text(payload.url)

    return {
        "ok": result.ok,
        "url": result.url,
        "domain": result.domain,
        "title": result.title,
        "bytes_read": result.bytes_read,
        "risk": result.risk,
        "reason": result.reason,
        "response": build_web_page_response(result),
    }


@router.post("/search")
def search_web(payload: WebSearchRequest):
    results = fetch_web_search_results(payload.query)

    return {
        "ok": True,
        "query": payload.query,
        "count": len(results),
        "results": [
            {
                "title": item.title,
                "url": item.url,
                "domain": item.domain,
                "snippet": item.snippet,
            }
            for item in results
        ],
        "response": build_web_search_response(payload.query, results),
    }


@router.post("/summary")
def summarize_best_source(payload: WebSearchRequest):
    results = fetch_web_search_results(payload.query)
    return build_search_summary_payload(payload.query, results)


@router.post("/explain")
def explain_from_web(payload: WebExplainRequest):
    results = fetch_web_search_results(payload.query)
    return build_technical_web_answer_payload(payload.query, results)

@router.post("/ask")
def ask_web(payload: WebAskRequest):
    mode = payload.mode.lower().strip()
    query = payload.query.strip()

    if not query:
        return {
            "ok": False,
            "mode": mode,
            "query": query,
            "response": "Você precisa enviar uma query ou URL para o Helix pesquisar.",
            "reason": "Query vazia.",
        }

    if mode == "read":
        result = fetch_page_text(query)

        return {
            "ok": result.ok,
            "mode": mode,
            "query": query,
            "url": result.url,
            "domain": result.domain,
            "title": result.title,
            "bytes_read": result.bytes_read,
            "risk": result.risk,
            "reason": result.reason,
            "response": build_web_page_response(result),
        }

    if mode == "search":
        results = fetch_web_search_results(query)

        return {
            "ok": True,
            "mode": mode,
            "query": query,
            "count": len(results),
            "results": [
                {
                    "title": item.title,
                    "url": item.url,
                    "domain": item.domain,
                    "snippet": item.snippet,
                }
                for item in results
            ],
            "response": build_web_search_response(query, results),
        }

    if mode == "summary":
        results = fetch_web_search_results(query)
        payload_response = build_search_summary_payload(query, results)
        payload_response["mode"] = mode
        return payload_response

    if mode == "explain":
        results = fetch_web_search_results(query)
        payload_response = build_technical_web_answer_payload(query, results)
        payload_response["mode"] = mode
        return payload_response

    return {
        "ok": False,
        "mode": mode,
        "query": query,
        "response": (
            "Modo web inválido. Use: search, summary, explain ou read."
        ),
        "reason": "Modo inválido.",
        "allowed_modes": [
            "search",
            "summary",
            "explain",
            "read",
        ],
    }