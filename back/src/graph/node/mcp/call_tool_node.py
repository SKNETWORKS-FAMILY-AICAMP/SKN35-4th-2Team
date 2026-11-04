"""
4단계: 도구를 실제로 부른다.

State.mcp_call  -->  [이 노드]  -->  성공하면 State.mcp_outcome, 실패하면 State.mcp_error와 mcp_failures

오류는 두 가지로 나눈다.
- 도구가 스스로 실패함 (is_error): 인자나 선택이 잘못됐을 수 있으므로 "다시 선택"할 수 있다. 오류 문구를 실패 기록에 남긴다.
- 서버를 못 띄움, 시간 초과 등: 도구를 바꿔도 소용없으므로 다시 선택하지 않는다.
"""

from src.const import mcp_config as cfg
from src.mcp_integration.client.tools import call_tool, describe_error


def _fail(state, kind: str, message: str) -> dict:
    call = state["mcp_call"]
    record = {"tool": call["display_name"], "arguments": call["arguments"], "kind": kind, "message": message}
    return {
        "mcp_failures": [*state.get("mcp_failures", []), record],
        "mcp_error": {"kind": kind, "message": message, "retryable": kind in cfg.ERROR_RETRYABLE},
    }


def call_tool_node(state):
    call = state["mcp_call"]
    server = next(s for s in cfg.MCP_SERVERS if s.name == call["server"])

    try:
        result = call_tool(server, call["name"], call["arguments"])
    except TimeoutError:
        return _fail(state, "timeout", f"도구 호출이 {cfg.CALL_TOOL_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다.")
    except Exception as exc:
        return _fail(state, "connection", describe_error(exc))

    if result["is_error"]:
        return _fail(state, "tool_error", result["text"])

    return {
        "mcp_error": None,
        "mcp_outcome": {
            "tool": call["display_name"],
            "server": call["server"],
            "arguments": call["arguments"],
            "text": result["text"],
        },
    }
