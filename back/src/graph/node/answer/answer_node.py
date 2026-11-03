from src.const.models import create_openai_model
from src.prompt.answer_prompt import ANSWER_SYSTEM_PROMPT

model = create_openai_model()

FOLLOW_UP_NOTICE = (
    "아래는 이번 질문과 이번 턴에 모은 자료다. 앞의 대화 내용은 그대로 참고한다. "
    "이번 질문이 앞 대화를 가리키면(예: '위 내용', '다른 해결책', '그걸') 앞 대화를 바탕으로 답한다. "
    "자료가 비어 있어도 앞 대화로 답할 수 있으면 답한다."
)
NEW_IMAGE_NOTICE = (
    "이번 턴에 새 이미지가 첨부되었다. image_analysis에 적힌 이번 이미지의 내용이 답변의 기준이다. "
    "앞 대화의 이전 이미지에 대한 답변은 이번 이미지와 다를 수 있으니 그대로 되풀이하지 말고, "
    "이번 이미지의 내용을 새로 읽어 답한다."
)


def _role(message):
    if isinstance(message, dict):
        return message.get("role") or message.get("type")
    return getattr(message, "type", None)


def _history(messages):
    """이전 대화를 실제 대화 메시지로 넘긴다. 마지막 사용자 질문은 이번 턴 자료와 함께 따로 보내므로 뺀다."""
    messages = list(messages or [])
    if messages and _role(messages[-1]) in ("user", "human"):
        messages = messages[:-1]
    return messages


def answer_node(state):
    current = {
        "original_question": state.get("original_question", ""),
        "image_analysis": state.get("image_analysis"),
        "retrieved_docs": state.get("retrieved_docs", []),
        "mcp_results": state.get("mcp_results"),
    }
    notice = NEW_IMAGE_NOTICE if current["image_analysis"] else FOLLOW_UP_NOTICE
    response = model.invoke(
        [{"role": "system", "content": ANSWER_SYSTEM_PROMPT}]
        + _history(state.get("messages", []))
        + [{"role": "user", "content": notice + "\n" + str(current)}]
    )

    return {
        "messages": [response],
        "answer": response.content,
    }
