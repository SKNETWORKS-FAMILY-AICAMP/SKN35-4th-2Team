"""
답변에 붙일 출처 목록 만들기: 그래프 결과(RAG 문서, MCP 결과)를 DB의 출처 형식으로 바꾼다.

    result["retrieved_docs"] (RAG 문서)  +  result["mcp_results"] (MCP 결과)   -->  [출처, ...]

- 이 목록 하나를 화면(render_sources)과 DB(record_assistant_turn의 sources=)가 같이 쓴다.
- 출처의 모양은 DB의 add_sources가 정한다: {"url"(필수), "title", "tech", "version", "doc_type", "snippet", "score"}.
- 이 파일은 다른 팀원의 코드를 불러오지 않는다. RAG 문서는 metadata와 page_content만 읽고(LangChain Document나 같은 모양의 dict),
  MCP 결과는 항목마다 이미 들어 있는 "sources"를 모은다 (도구 결과에서 뽑는 일은 src/mcp_integration/client/sources.py가 한다).
- RAG 문서의 메타데이터 키(2026-10 확인): source_url(공식 문서 주소), title, technology, document_type, score.

하는 일
- http, https 주소만 받는다 (javascript:, file: 같은 주소가 화면의 링크가 되는 것을 막는다).
- DB 열의 길이(URL 1000자 등)에 맞춰 글자를 줄이고, 주소가 너무 길면 그 출처는 뺀다 (줄이면 잘못된 주소가 되므로).
- 같은 주소는 하나로 합치고(먼저 나온 것을 남김), 개수 상한(SOURCES_MAX_PER_ANSWER)을 지킨다.
- 제목과 발췌문의 비밀값(API 키 등)은 가린다.
- 이상한 항목(None, 문자열 등)은 조용히 건너뛴다. 출처가 없다고 답변 전체가 실패하면 안 되기 때문이다.

한계: 출처를 붙이는 것과 "그 출처가 실제로 답변의 근거였는가"는 다른 문제다 (그건 DB의 is_grounded 칸에 나중에 채운다).
"""

import math
from typing import Any, Iterable

from src.const import db_config as cfg

from .masking import mask_secrets
from .models import MessageSource

_COLUMNS = MessageSource.__table__.c
_URL_MAX = _COLUMNS.url.type.length


def _text(value: Any, limit: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value if limit is None or len(value) <= limit else value[:limit]


def _score(value: Any) -> float | None:
    """점수는 유한한 숫자만 받는다 (NaN, 무한대는 MySQL/TiDB에 저장할 수 없어서 저장할 때 오류가 난다)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize(item: dict) -> dict | None:
    """출처 한 건을 DB 형식으로 맞춘다. 쓸 수 없는 항목이면 None."""
    url = _text(item.get("url"))
    if url is None or len(url) > _URL_MAX or any(ch.isspace() for ch in url):
        return None
    if not url.lower().startswith(("http://", "https://")):
        return None
    snippet = _text(item.get("snippet"), cfg.SOURCES_SNIPPET_CHARS)
    title = _text(item.get("title"), _COLUMNS.title.type.length)
    return {
        "url": url,
        "title": mask_secrets(title) if title else None,
        "tech": _text(item.get("tech"), _COLUMNS.tech.type.length),
        "version": _text(item.get("version"), _COLUMNS.version.type.length),
        "doc_type": _text(item.get("doc_type"), _COLUMNS.doc_type.type.length),
        "snippet": mask_secrets(snippet) if snippet else None,
        "score": _score(item.get("score")),
    }


def _from_document(doc: Any) -> dict | None:
    """RAG 문서(LangChain Document 또는 {"metadata":..., "page_content":...} 모양의 dict) 하나를 출처 항목으로."""
    metadata = doc.get("metadata") if isinstance(doc, dict) else getattr(doc, "metadata", None)
    content = doc.get("page_content") if isinstance(doc, dict) else getattr(doc, "page_content", None)
    if not isinstance(metadata, dict):
        return None
    url = metadata.get("source_url") or metadata.get("url")
    return {
        "url": url,
        "title": metadata.get("title") or metadata.get("file_name") or url,
        "tech": metadata.get("technology"),
        "version": metadata.get("version"),
        "doc_type": metadata.get("document_type"),
        "snippet": content,
        "score": metadata.get("score"),
    }


def build_sources(
    retrieved_docs: Iterable[Any] | None = None,
    mcp_results: Iterable[Any] | None = None,
    *,
    limit: int = cfg.SOURCES_MAX_PER_ANSWER,
) -> list[dict]:
    """RAG 문서와 MCP 결과에서 출처 목록을 만든다 (RAG 문서가 먼저, 그다음 MCP 결과 순)."""
    candidates: list[Any] = []
    for doc in retrieved_docs or []:
        candidates.append(_from_document(doc))
    for record in mcp_results or []:
        # 실패하거나 도구가 필요 없었던 결과의 출처는 쓰지 않는다 (근거가 아니므로)
        if isinstance(record, dict) and record.get("status") == "success":
            candidates.extend(record.get("sources") or [])

    sources: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        source = _normalize(candidate)
        if source is None or source["url"] in seen:
            continue
        seen.add(source["url"])
        sources.append(source)
        if len(sources) >= limit:
            break
    return sources
