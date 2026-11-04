"""
5단계: 읽은 결과를 항목이 있는 글로 정리하기.

모델이 읽은 글 + 안내 문구  -->  [이 단계]  -->  State.image_analysis에 넣을 문자열 하나

결과 모양 (항목 제목은 src/const/multi_modal_config.py의 SECTION_HEADINGS):
    ※ (처리 중 남긴 안내 문구가 있으면 맨 앞에)

    [화면 설명]
    ...
    [오류 메시지]
    ...
    (정해진 5개 항목이 항상 이 순서로 나온다. 내용이 없는 항목은 "없음")

- 화면에 찍힌 API 키나 비밀번호가 결과에 섞이지 않게 가린다 (src/db/masking.py의 mask_secrets).
  알려진 패턴만 가리는 방식이라 완벽한 보호는 아니다.
- 모델이 항목 형식을 지키지 않았으면 항목을 지어내지 않고 읽은 글을 그대로 두고 그 사실을 안내 문구로 남긴다.
- 너무 길면 잘라서 표시를 남긴다 (DB의 이미지 분석 텍스트 상한과 같은 값).
"""

from src.const import db_config as limits
from src.const import multi_modal_config as cfg
from src.db.masking import mask_secrets


def _split_sections(text: str) -> dict[str, str]:
    """모델이 쓴 글에서 항목 제목별 내용을 뽑는다. 제목이 하나도 없으면 빈 딕셔너리."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip().lstrip("#* ").strip()
        heading = next((h for h in cfg.SECTION_HEADINGS if stripped.startswith(h)), None)
        if heading is not None:
            current = heading
            sections.setdefault(current, [])
            rest = stripped[len(heading) :].lstrip("*: ").strip()
            if rest:
                sections[current].append(rest)
        elif current is not None:
            sections[current].append(line)  # 코드의 들여쓰기를 지키려고 줄은 그대로 둔다
    return {heading: "\n".join(lines).strip("\n").strip() for heading, lines in sections.items()}


def _clip(text: str) -> str:
    if len(text) > limits.IMAGE_ANALYSIS_MAX_CHARS:
        return text[: limits.IMAGE_ANALYSIS_MAX_CHARS] + limits.CLIP_SUFFIX
    return text


def build_analysis(raw_text: str | None, notes: list[str]) -> str:
    """raw_text가 None이면 모델을 부르지 못한 경우다 (이미지가 없거나, 모두 건너뛰었거나, 호출에 실패함)."""
    notes = list(notes)

    if raw_text is None:
        if not notes:
            return cfg.NO_IMAGE_NOTICE
        return "\n".join(f"※ {note}" for note in notes)

    text = mask_secrets(raw_text.strip())
    sections = _split_sections(text)
    if not sections:
        if text:
            notes.append("읽은 결과가 정해진 항목 형식이 아니어서 읽은 글을 그대로 둡니다.")
        body = text or cfg.EMPTY_RESULT_NOTICE
    else:
        body = "\n\n".join(
            f"{heading}\n{sections.get(heading) or cfg.EMPTY_SECTION_TEXT}" for heading in cfg.SECTION_HEADINGS
        )

    header = "\n".join(f"※ {note}" for note in notes)
    return _clip(f"{header}\n\n{body}" if header else body)
