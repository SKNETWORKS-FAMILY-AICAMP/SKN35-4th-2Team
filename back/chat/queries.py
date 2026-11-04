"""
3차 DB 계층에 없는 대화 기능: 대화 제목 검색. (제목 변경은 3차 DB 계층의 rename_conversation을 쓴다.) 코어의 모델(Conversation)을 그대로 쓴다.

- 모든 함수는 user_id를 받아 본인 대화만 다룬다 (남의 대화는 없는 것처럼 취급한다).
- 검색어의 % 와 _ 는 와일드카드가 아니라 글자 그대로 찾는다.
- 검색어를 공백으로 나눈 단어가 모두 제목에 있으면 찾는다 (순서와 제목 속 공백 개수는 상관없다).
"""

from sqlalchemy import and_, func, select

from src.db import Conversation

SEARCH_LIMIT = 50  # 한 번에 돌려주는 검색 결과 수
QUERY_MAX_CHARS = 100  # 검색어 최대 글자 수


def like_pattern(text):
    """LIKE 검색용 패턴. 대소문자는 무시하고, %, _, \\ 는 글자 그대로 찾는다."""
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_conversations(session, user_id, query):
    """제목에 검색어의 단어가 모두 있는 내 대화를 최근 수정순으로 찾는다. 대화 내용(질문, 답변)은 검색하지 않는다."""
    words = query.split()
    if not words:
        return []
    every_word = and_(*(func.lower(Conversation.title).like(like_pattern(word), escape="\\") for word in words))
    return list(
        session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id, every_word)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(SEARCH_LIMIT)
        )
    )
