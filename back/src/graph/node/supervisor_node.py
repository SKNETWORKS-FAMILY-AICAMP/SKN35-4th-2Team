from typing import Literal

from pydantic import BaseModel, Field

from src.const.models import create_openai_model
from src.prompt.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT

model = create_openai_model()


class RouteDecision(BaseModel):
    route: Literal[
        "general",
        "rag",
        "mcp",
        "multi_modal",
        "answer",
    ] = Field(description="현재 상태를 바탕으로 다음에 수행할 작업을 선택합니다.")

    reason: str = Field(description="선택한 작업이 필요한 이유를 간단하게 설명합니다.")


def image_summary(state):
    """프롬프트에 넣어도 안전한 이미지 요약 (있는지와 장수만).

    이미지 원본 바이트를 문자열로 만들어 프롬프트에 넣으면 크기가 수 MB로 커져서 호출이 느려지고 비용이 크게 늘어난다.
    """
    images = state.get("image")
    if images is None:
        count = 0
    elif isinstance(images, (list, tuple)):
        count = len(images)
    else:
        count = 1
    return {"has_image": count > 0, "image_count": count}


QUESTION_MAX_CHARS = 3_000  # 첨부 파일이 붙은 긴 질문이 Supervisor 판단마다 통째로 들어가지 않게 한다 (답변 단계는 전체를 본다)


def _clip(content):
    if isinstance(content, str) and len(content) > QUESTION_MAX_CHARS:
        return content[:QUESTION_MAX_CHARS] + " …(이하 생략)"
    return content


def supervisor_node(state):
    print("supervisor 진입", end="\n\n")
    supervisor = model.with_structured_output(RouteDecision)

    decision = supervisor.invoke(
        [
            {
                "role": "system",
                "content": SUPERVISOR_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": str(
                    {
                        "messages": _clip(state["messages"][-1].content),
                        "image": image_summary(state),
                        "image_analysis": state.get("image_analysis"),
                        "retrieved_docs": state.get("retrieved_docs"),
                        "mcp_results": state.get("mcp_results"),
                        "completed_routes": state.get("completed_routes"),
                    }
                ),
            },
        ]
    )

    return {
        "route": decision.route,
        "reason": decision.reason,
    }
