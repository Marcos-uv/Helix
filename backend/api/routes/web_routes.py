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