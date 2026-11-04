"""
3차 DB 계층에 없는 대화 기능: 대화 제목 검색, 제목 변경. 3차 코어(back/src)는 수정하지 않고, 코어의 모델(Conversation, Message)을 그대로 쓴다.

- 모든 함수는 user_id를 받아 본인 대화만 다룬다 (남의 대화는 없는 것처럼 취급한다).
- 검색어의 % 와 _ 는 와일드카드가 아니라 글자 그대로 찾는다.
"""

import re

from sqlalchemy import func, select
from sqlalchemy.orm.attributes import flag_modified

from src.db import Conversation, get_conversation, mask_secrets

SEARCH_LIMIT = 50  # 한 번에 돌려주는 검색 결과 수
QUERY_MAX_CHARS = 100  # 검색어 최대 글자 수
TITLE_MAX_CHARS = 100  # 제목 최대 글자 수 (DB 컬럼은 200자)
DB_TITLE_MAX_CHARS = 200
EMPTY_TITLE = "제목을 입력해 주세요."


def like_pattern(text):
    """LIKE 검색용 패턴. 대소문자는 무시하고, %, _, \\ 는 글자 그대로 찾는다."""
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_conversations(session, user_id, query):
    """제목에 검색어가 있는 내 대화를 최근 수정순으로 찾는다. 대화 내용(질문, 답변)은 검색하지 않는다."""
    pattern = like_pattern(" ".join(query.split()))
    return list(
        session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id, func.lower(Conversation.title).like(pattern, escape="\\"))
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(SEARCH_LIMIT)
        )
    )


def normalize_title(title):
    """제목을 정리한다 (줄바꿈, 탭, 제어문자 제거, 공백 정리, 비밀값 가리기). 문제가 있으면 사용자에게 보여 줄 문장으로 ValueError."""
    if not isinstance(title, str):
        raise ValueError(EMPTY_TITLE)
    cleaned = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", title).split())
    if not cleaned:
        raise ValueError(EMPTY_TITLE)
    if len(cleaned) > TITLE_MAX_CHARS:
        raise ValueError(f"제목은 {TITLE_MAX_CHARS}자 이하로 입력해 주세요.")
    return mask_secrets(cleaned)[:DB_TITLE_MAX_CHARS]  # 질문과 답변처럼 API 키 같은 비밀은 가려서 저장한다


def rename_conversation(session, user_id, conversation_id, title):
    """내 대화의 제목을 바꾼다. 없거나 남의 대화면 None, 바꿨으면 대화를 돌려준다. 제목이 올바르지 않으면 ValueError."""
    cleaned = normalize_title(title)
    conversation = get_conversation(session, conversation_id, user_id)
    if conversation is None:
        return None
    conversation.title = cleaned
    flag_modified(conversation, "updated_at")  # 제목만 바꿨을 때 "마지막 수정 시각"이 바뀌어 목록 순서가 달라지지 않게 한다
    session.flush()
    return conversation
