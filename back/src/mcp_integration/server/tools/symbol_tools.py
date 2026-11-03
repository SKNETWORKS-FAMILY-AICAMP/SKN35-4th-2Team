"""
심볼 존재 확인 도구 (서버에 설치된 패키지를 직접 살펴보는 도구, 키와 네트워크가 필요 없다).

check_symbol_exists("langgraph.graph.StateGraph") 처럼 함수, 클래스, 모듈이 설치된 버전에 실제로 있는지 확인한다.
모델이 존재하지 않는 함수나 옛 API를 지어내는 것을 막고(환각 방지), 없으면 비슷한 이름을 알려 준다.

- 이 서버가 설치된 환경(uv.lock의 버전) 기준이다. 사용자의 환경과 다를 수 있다.
- 아무 모듈이나 불러오면 그 모듈의 코드가 실행되므로, 허용된 패키지(SYMBOL_ALLOWED_PACKAGES)만 불러온다.
"""

import asyncio
import difflib
import importlib
import importlib.metadata as metadata
import inspect
import re

from mcp.server.mcpserver.exceptions import ToolError

from src.const import mcp_config as cfg
from src.mcp_integration.server.tools import common

_SYMBOL = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def _kind(obj) -> str:
    if inspect.ismodule(obj):
        return "module"
    if inspect.isclass(obj):
        return "class"
    if inspect.isfunction(obj) or inspect.ismethod(obj) or inspect.isbuiltin(obj):
        return "function"
    return type(obj).__name__


def _installed_version(top: str) -> str | None:
    try:
        dists = metadata.packages_distributions().get(top)
        return metadata.version(dists[0]) if dists else None
    except Exception:
        return None


def resolve_symbol(symbol: str) -> dict:
    """동기 함수 (모듈을 불러오는 일은 느려서 호출하는 쪽이 스레드에서 실행한다)."""
    symbol = (symbol or "").strip()
    if not _SYMBOL.fullmatch(symbol):
        raise ToolError(f"'{symbol}'는 올바른 심볼 이름이 아닙니다 (예: langgraph.graph.StateGraph).")
    parts = symbol.split(".")
    top = parts[0]
    if top not in cfg.SYMBOL_ALLOWED_PACKAGES:
        raise ToolError(f"'{top}' 패키지는 확인할 수 없습니다. 확인할 수 있는 패키지: {', '.join(cfg.SYMBOL_ALLOWED_PACKAGES)}")
    try:
        obj = importlib.import_module(top)
    except Exception as exc:
        raise ToolError(f"'{top}' 패키지를 이 서버에서 불러오지 못했습니다 (설치되어 있지 않을 수 있음): {type(exc).__name__}") from exc

    base = {"symbol": symbol, "installed_package_version": _installed_version(top), "retrieved_at": common.now_iso()}
    resolved = top
    for part in parts[1:]:
        if hasattr(obj, part):
            obj, resolved = getattr(obj, part), f"{resolved}.{part}"
            continue
        try:  # 하위 모듈일 수 있다 (아직 불러오지 않아서 속성으로 안 보이는 경우)
            obj = importlib.import_module(f"{resolved}.{part}")
            resolved = f"{resolved}.{part}"
            continue
        except ModuleNotFoundError:
            pass
        except Exception as exc:  # 모듈은 있는데 불러오다 실패 (선택 의존성 누락 등)
            return {**base, "exists": None, "resolved_up_to": resolved, "problem": f"'{part}'을(를) 불러오다 실패했습니다: {type(exc).__name__}"}
        names = [n for n in dir(obj) if not n.startswith("_")]
        return {
            **base,
            "exists": False,
            "resolved_up_to": resolved,
            "missing": part,
            "similar_names": difflib.get_close_matches(part, names, n=cfg.SYMBOL_SIMILAR_COUNT, cutoff=0.6),
            "note": f"설치된 버전에서 '{resolved}'에 '{part}'이(가) 없습니다. 이 서버에 설치된 버전 기준이며 사용자의 환경과 다를 수 있습니다.",
        }

    try:
        signature = str(inspect.signature(obj)) if callable(obj) and not inspect.ismodule(obj) else None
    except (TypeError, ValueError):
        signature = None
    doc = (inspect.getdoc(obj) or "").strip().splitlines()
    return {
        **base,
        "exists": True,
        "kind": _kind(obj),
        "signature": common.clip(signature, 300) if signature else None,
        "summary": common.clip(doc[0], 200) if doc else None,
        "note": "이 서버에 설치된 버전 기준이며 사용자의 환경과 다를 수 있습니다.",
    }


def register(mcp) -> None:
    @mcp.tool()
    async def check_symbol_exists(symbol: str) -> str:
        """LangChain, LangGraph, MCP 파이썬 패키지에 함수, 클래스, 모듈이 실제로 있는지 확인한다.

        "이 함수가 있나?", "이 import가 되나?"처럼 존재 여부가 의심되거나, 답변에 쓰려는 API 이름이 정확한지 확인할 때 쓴다.
        있으면 종류와 시그니처를, 없으면 비슷한 이름을 알려 준다. 서버에 설치된 버전 기준이다.
        존재 여부와 시그니처만 알려 주므로, 사용법이나 개념을 설명해 달라는 질문에는 쓰지 않는다 (그건 문서 검색의 일이다).

        Args:
            symbol: 점으로 이어진 전체 이름 (예: langgraph.graph.StateGraph, langchain.agents.create_agent, mcp.Client).
                허용된 패키지: langchain, langchain_core, langchain_openai, langchain_community, langgraph, mcp
        """
        return common.dump(await asyncio.to_thread(resolve_symbol, symbol))
