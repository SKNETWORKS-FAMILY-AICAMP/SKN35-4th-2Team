"""
2단계: 모델이 질문을 보고 쓸 도구와 인자를 고른다.

State.mcp_tools + 질문  -->  [이 노드]  -->  State.mcp_call ({"display_name", "arguments"})

- 팀 공통 모델(create_openai_model)에 도구 목록을 함수 호출(tool calling) 형식으로 넘긴다. 도구의 입력 규칙(스키마)을 그대로 쓴다.
- 도구를 고르지 않았으면 mcp_call이 None이다. 처음부터 그랬다면 "맞는 도구 없음"이고, 실패한 뒤라면 "고칠 수 없다고 판단"한 것이다
  (어느 쪽인지는 결과 정리 노드가 실패 기록으로 구분한다).
- 다시 고르는 경우(앞선 시도가 실패한 경우)에는 실패 기록을 모델에게 보여 준다. 그냥 다시 시키면 같은 선택을 반복하기 때문이다.
- 질문에 오류 문구가 없고 이미지에만 있는 경우를 위해, 멀티모달 노드가 읽은 글(State.image_analysis)이 있으면 질문 뒤에 함께 보여 준다.
- 모델은 호출할 때 만들어서, API 키가 없어도 import는 된다.
"""

from src.const import mcp_config as cfg
from src.const.models import create_openai_model
from src.const.multi_modal_config import IMAGE_CONTEXT_MARKER, NO_IMAGE_NOTICE
from src.mcp_integration.client.tools import describe_error
from src.prompt.mcp_prompt import MCP_RETRY_NOTICE, MCP_SELECT_SYSTEM_PROMPT


def _tool_definitions(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["display_name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in tools
    ]


def _failure_lines(failures: list[dict]) -> str:
    return "\n".join(
        f"- 도구 {f['tool']}, 인자 {f['arguments']}: {f['message']}" for f in failures
    )


def _image_text(state) -> str:
    """멀티모달 노드가 읽은 글 (없거나 "분석할 이미지가 없음" 안내뿐이면 빈 문자열)."""
    text = (state.get("image_analysis") or "").strip()
    if not text or text == NO_IMAGE_NOTICE:
        return ""
    if IMAGE_CONTEXT_MARKER in (state.get("original_question") or ""):
        return ""  # 멀티모달 노드가 이미 질문에 붙여 두었다 (같은 글을 두 번 보여 주지 않는다)
    return text if len(text) <= cfg.IMAGE_CONTEXT_MAX_CHARS else text[: cfg.IMAGE_CONTEXT_MAX_CHARS] + cfg.CLIP_SUFFIX


def select_tool_node(state):
    attempts = state.get("mcp_attempts", 0)
    failures = state.get("mcp_failures", [])

    user_text = f"사용자의 질문: {state['original_question']}"
    image_text = _image_text(state)
    if image_text:
        user_text += f"\n\n이미지에서 읽은 내용:\n{image_text}"
    if failures:
        user_text += "\n\n" + MCP_RETRY_NOTICE.format(failures=_failure_lines(failures))

    try:
        model = create_openai_model(temperature=cfg.SELECT_TEMPERATURE, timeout=cfg.SELECT_TIMEOUT_SECONDS)
        response = model.bind_tools(_tool_definitions(state["mcp_tools"]), parallel_tool_calls=False).invoke(
            [
                {"role": "system", "content": MCP_SELECT_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ]
        )
    except Exception as exc:  # 네트워크, 한도, 키 오류 등: 도구를 바꿔도 소용없으므로 다시 시도하지 않는다
        return {
            "mcp_call": None,
            "mcp_attempts": attempts + 1,
            "mcp_error": {"kind": "model_error", "message": describe_error(exc), "retryable": False},
        }

    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
        return {
            "mcp_call": None,
            "mcp_attempts": attempts + 1,
            "mcp_error": {"kind": "no_tool", "message": "도구를 고르지 않았습니다.", "retryable": False},
        }

    chosen = tool_calls[0]  # 한 번에 하나만 쓴다
    return {
        "mcp_call": {"display_name": chosen["name"], "arguments": chosen.get("args") or {}},
        "mcp_attempts": attempts + 1,
        "mcp_error": None,
    }
