from src.const import multi_modal_config as cfg
from src.multi_modal.build_analysis import build_analysis


def question_text(state: dict) -> str:
    """이미지를 읽을 때 참고할 사용자의 질문 (없으면 빈 문자열)."""
    question = state.get("original_question")
    if isinstance(question, str) and question.strip():
        return question
    messages = state.get("messages") or []
    if not messages:
        return ""
    last = messages[-1]
    content = last.get("content") if isinstance(last, dict) else getattr(last, "content", "")
    return content if isinstance(content, str) else ""


def question_with_image(state: dict, analysis: str) -> str:
    """질문 글 뒤에 이미지에서 읽은 내용을 붙인다. 이후 RAG(검색어)와 MCP(도구 선택)가 이 글을 질문으로 쓴다.

    이미지만 올려서 질문이 "이미지를 확인해 주세요"뿐이어도, 읽은 오류 문구로 검색할 수 있게 하려는 것이다.
    """
    question = question_text(state)
    if cfg.IMAGE_CONTEXT_MARKER in question:
        return question
    text = analysis if len(analysis) <= cfg.QUESTION_IMAGE_MAX_CHARS else analysis[: cfg.QUESTION_IMAGE_MAX_CHARS] + cfg.QUESTION_CLIP_SUFFIX
    return question + "\n\n" + cfg.IMAGE_CONTEXT_MARKER + "\n" + text


def build_analysis_node(state):
    print("build_analysis_node 진입", end="\n\n")

    raw_text = state.get("raw_text")
    analysis = build_analysis(raw_text, state.get("notes", []))

    # 읽은 내용을 질문에 붙이는 것은 읽기에 성공한 경우에만 한다
    attached = question_with_image(state, analysis) if raw_text is not None else None
    return {"image_analysis": analysis, "question_with_image": attached}
