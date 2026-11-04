"""
3단계: 부르기 전에 모델이 고른 도구와 인자를 검사한다.

State.mcp_call  -->  [이 노드]  -->  검사를 통과하면 서버와 원래 도구 이름을 채움, 아니면 State.mcp_error

- 검사하는 것: 목록에 있는 도구인지, 인자가 도구의 입력 규칙(스키마)에 맞는지, 이미 실패한 호출(같은 도구와 같은 인자)을 반복하는지.
- 호출 전에 걸러내면 서버를 띄우는 시간과 비용을 아낄 수 있다.
- 실패하면 이유를 State.mcp_failures에 남긴다. 다시 고를 때 모델이 이걸 읽는다.
"""

import json

from jsonschema.validators import validator_for

from src.const import mcp_config as cfg


def _call_key(display_name: str, arguments: dict) -> str:
    return f"{display_name}|{json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)}"


def _argument_problems(schema: dict, arguments: dict) -> str:
    validator = validator_for(schema)(schema)
    problems = []
    for error in sorted(validator.iter_errors(arguments), key=lambda e: list(map(str, e.path))):
        where = ".".join(str(p) for p in error.path) or "(전체)"
        problems.append(f"{where}: {error.message}")
    return "; ".join(problems[:3])


def _fail(state, kind: str, message: str) -> dict:
    call = state["mcp_call"]
    record = {"tool": call["display_name"], "arguments": call["arguments"], "kind": kind, "message": message}
    return {
        "mcp_failures": [*state.get("mcp_failures", []), record],
        "mcp_error": {"kind": kind, "message": message, "retryable": kind in cfg.ERROR_RETRYABLE},
    }


def validate_call_node(state):
    call = state["mcp_call"]
    tool = next((t for t in state["mcp_tools"] if t["display_name"] == call["display_name"]), None)
    if tool is None:
        names = ", ".join(t["display_name"] for t in state["mcp_tools"])
        return _fail(state, "unknown_tool", f"'{call['display_name']}'라는 도구는 없습니다. 쓸 수 있는 도구: {names}")

    arguments = call["arguments"]
    if not isinstance(arguments, dict):
        return _fail(state, "invalid_arguments", "인자는 {이름: 값} 형태여야 합니다.")
    problems = _argument_problems(tool["input_schema"], arguments)
    if problems:
        return _fail(state, "invalid_arguments", f"인자가 도구의 입력 규칙과 맞지 않습니다. {problems}")

    key = _call_key(call["display_name"], arguments)
    if any(_call_key(f["tool"], f["arguments"]) == key for f in state.get("mcp_failures", [])):
        return _fail(state, "repeated_call", "이미 실패한 호출과 같은 도구, 같은 인자입니다. 다른 도구나 다른 인자를 쓰세요.")

    return {
        "mcp_call": {**call, "server": tool["server"], "name": tool["name"]},
        "mcp_error": None,
    }
