"""
1단계: 연결된 MCP 서버들에서 쓸 수 있는 도구 목록을 가져온다.

(시작)  -->  [이 노드]  -->  State.mcp_tools (도구 목록), 시도 횟수와 실패 기록을 비움

- 서버 목록은 src/const/mcp_config.py의 MCP_SERVERS다. 도구를 서버에 추가해도 이 코드는 바꾸지 않는다.
- 도구 목록은 TOOLS_CACHE_SECONDS 동안 기억해 둔다 (연결할 때마다 서버가 새로 떠서 시간이 걸리기 때문).
- 서버 하나가 안 떠도 나머지 서버의 도구는 쓴다. 쓸 수 있는 도구가 하나도 없으면 오류를 State에 남기고 바로 결과 정리로 간다.
"""

import re
import time

from src.const import mcp_config as cfg
from src.mcp_integration.client.tools import describe_error, list_tools

# 서버 이름 -> (가져온 시각, 도구 목록)
_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _safe_name(name: str) -> str:
    """모델에 도구 이름으로 줄 수 있는 글자(영문, 숫자, _, -)만 남긴다. 64자 제한."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64] or "tool"


def assign_display_names(tools: list[dict]) -> list[dict]:
    """모델에게 보여 줄 도구 이름(display_name)을 정한다. 서버가 달라도 이름이 겹치면 '서버이름__도구이름'으로 구분한다."""
    counts: dict[str, int] = {}
    for tool in tools:
        counts[_safe_name(tool["name"])] = counts.get(_safe_name(tool["name"]), 0) + 1
    named = []
    for tool in tools:
        base = _safe_name(tool["name"])
        display = base if counts[base] == 1 else _safe_name(f"{tool['server']}__{tool['name']}")
        named.append({**tool, "display_name": display})
    return named


def list_tools_node(state):
    tools: list[dict] = []
    problems: list[str] = []
    for server in cfg.MCP_SERVERS:
        cached = _CACHE.get(server.name)
        if cached and time.monotonic() - cached[0] < cfg.TOOLS_CACHE_SECONDS:
            tools.extend(cached[1])
            continue
        try:
            found = list_tools(server)
        except Exception as exc:  # 서버를 못 띄움, 시간 초과 등
            problems.append(f"{server.name}: {describe_error(exc)}")
            continue
        _CACHE[server.name] = (time.monotonic(), found)
        tools.extend(found)

    update = {
        "mcp_tools": assign_display_names(tools),
        "mcp_call": None,
        "mcp_attempts": 0,
        "mcp_failures": [],
        "mcp_error": None,
        "mcp_outcome": None,
    }
    if not tools:
        detail = "; ".join(problems) or "연결된 서버에 도구가 없습니다."
        update["mcp_error"] = {
            "kind": "connection",
            "message": f"사용할 수 있는 MCP 도구가 없습니다. {detail}",
            "retryable": False,
        }
    return update
