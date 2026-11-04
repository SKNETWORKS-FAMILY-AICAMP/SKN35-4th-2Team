"""
4단계: 이미지 읽기 (모델 호출).

content 조각 목록 + 사용자 질문  -->  [이 단계]  -->  모델이 읽은 글 (항목 형식은 5단계에서 다듬는다)

- 모든 이미지를 한 번의 호출로 보낸다 (코드 화면과 오류 화면처럼 서로 이어지는 이미지를 함께 이해하게 하려고).
- 모델은 팀 공통 모델(src/const/models.py의 create_openai_model)을 쓴다. 호출할 때 만들어서, API 키가 없어도 import는 된다.
- 질문은 무엇을 중점적으로 읽을지 정하는 참고로만 쓴다. 답변은 이 노드가 아니라 answer 노드가 한다 (프롬프트에 적혀 있다).
- 실패하면 예외를 그대로 던진다. 처리는 read_images_node.py가 한다.
"""

from typing import Any

from src.const import multi_modal_config as cfg
from src.const.models import create_openai_model
from src.prompt.multi_modal_prompt import MULTI_MODAL_SYSTEM_PROMPT


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content).strip()


def read_images(parts: list[dict], question: str = "") -> str:
    question = question.strip()[: cfg.QUESTION_MAX_CHARS]
    question_text = f"사용자의 질문: {question}" if question else "사용자의 질문: (없음, 이미지만 올림)"

    messages = [
        {"role": "system", "content": MULTI_MODAL_SYSTEM_PROMPT},
        {"role": "user", "content": [{"type": "text", "text": question_text}, *parts]},
    ]
    model = create_openai_model(temperature=cfg.VISION_TEMPERATURE, timeout=cfg.VISION_TIMEOUT_SECONDS)
    response = model.invoke(messages, max_tokens=cfg.VISION_MAX_OUTPUT_TOKENS)
    return _response_text(response)
