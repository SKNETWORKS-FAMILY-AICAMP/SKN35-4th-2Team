"""
한 번의 질문-답변을 DB에 기록하는 함수 두 개. UI(또는 그래프를 실행하는 쪽)가 그래프 실행 전과 후에 하나씩 부른다.

    with db_session() as s:
        turn = record_user_turn(s, user_id, "State가 전달되지 않아요", conversation_id=cid, images=[png_bytes])
    # ... 그래프 실행 (turn.conversation_id, 이력 get_history_context 사용) ...
    with db_session() as s:
        record_assistant_turn(s, user_id, turn.conversation_id, answer, sources=docs,
                              user_message_id=turn.message_id, image_analysis=state.get("image_analysis"))

왜 두 번으로 나누나
- 사용자 입력은 그래프가 실패해도 남아야 하므로, 그래프를 실행하기 전에 먼저 저장한다.
- 답변과 출처는 그래프가 끝난 뒤에 저장한다.
- 그래프(LangGraph)가 DB 코드를 몰라도 되게, 저장은 그래프 바깥에서 한다.

각 함수는 저장하기 전에 입력을 먼저 검사한다. 검사에 실패하면 아무것도 쓰지 않고 ValueError를 낸다.
(호출한 쪽은 이 예외를 잡지 말고 db_session 블록 밖으로 내보내면, 일부만 저장되는 일이 없다.)
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .images import max_images_per_message, validate_image
from .limits import message_max_chars
from .masking import mask_secrets
from .models import UserProfile
from .repository import (
    add_image,
    add_message,
    add_sources,
    create_conversation,
    get_conversation,
    get_message,
    set_message_image_analysis,
)


@dataclass(frozen=True)
class UserTurn:
    conversation_id: int
    message_id: int
    attachment_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class AssistantTurn:
    message_id: int
    source_ids: list[int] = field(default_factory=list)


def _profile_snapshot(session: Session, user_id: int) -> dict | None:
    """사용자가 환경 정보를 직접 주지 않았을 때, 프로필에 저장된 기본 환경을 질문 시점의 스냅샷으로 쓴다."""
    profile = session.get(UserProfile, user_id)
    if profile is None:
        return None
    snap = {
        "python_version": profile.python_version,
        "os": profile.os,
        "lib_versions": profile.lib_versions,
    }
    snap = {k: v for k, v in snap.items() if v}
    return snap or None


def record_user_turn(
    session: Session,
    user_id: int,
    text: str,
    *,
    conversation_id: int | None = None,
    images: list[bytes] | None = None,
    env_snapshot: dict | None = None,
) -> UserTurn:
    """사용자의 질문(텍스트와 이미지)을 저장한다.

    - conversation_id가 없으면 새 대화를 만들고, 있으면 그 대화(소유자 확인)에 이어서 저장한다.
    - 텍스트나 이미지 중 하나는 있어야 한다. 이미지는 최대 장수와 크기, 형식을 먼저 검사한다.
    - env_snapshot을 주지 않으면 사용자 프로필의 기본 환경(파이썬 버전, OS, 라이브러리 버전)을 쓴다.
    """
    text = text or ""
    images = list(images or [])
    if not text.strip() and not images:
        raise ValueError("질문 텍스트나 이미지 중 하나는 있어야 합니다.")

    # ---- 쓰기 전에 모두 검사한다 (일부만 저장되는 일을 막는다)
    if len(images) > max_images_per_message():
        raise ValueError(f"한 번에 이미지를 {max_images_per_message()}장까지 보낼 수 있습니다.")
    for data in images:
        validate_image(data)
    limit = message_max_chars()
    masked_len = len(mask_secrets(text))
    if masked_len > limit:
        raise ValueError(f"메시지는 {limit}자 이하여야 합니다 (현재 {masked_len}자).")
    if conversation_id is not None and get_conversation(session, conversation_id, user_id) is None:
        raise PermissionError("대화가 없거나 이 사용자의 대화가 아닙니다.")

    # ---- 저장
    conv = (
        create_conversation(session, user_id)
        if conversation_id is None
        else get_conversation(session, conversation_id, user_id)
    )
    msg = add_message(
        session,
        conv.id,
        user_id,
        "user",
        text,
        input_type="image" if images else "text",
        env_snapshot=env_snapshot if env_snapshot is not None else _profile_snapshot(session, user_id),
    )
    if not text.strip() and conv.title == "새 대화":
        conv.title = "이미지 질문"
    attachment_ids = [add_image(session, msg.id, user_id, data).id for data in images]
    return UserTurn(conversation_id=conv.id, message_id=msg.id, attachment_ids=attachment_ids)


def record_assistant_turn(
    session: Session,
    user_id: int,
    conversation_id: int,
    answer: str,
    *,
    sources: list[dict] | None = None,
    user_message_id: int | None = None,
    image_analysis: str | None = None,
) -> AssistantTurn:
    """답변과 출처를 저장한다.

    - sources: add_sources와 같은 형식 [{"url"(필수), "title", "tech", "version", "doc_type", "snippet", "score"}, ...]
    - image_analysis: 그래프가 이미지에서 읽어 낸 텍스트. user_message_id(그 질문 메시지)에 저장되어,
      이후 질문에 이력을 붙일 때 함께 쓰인다. 주려면 user_message_id가 필요하다.
    - 너무 긴 답변은 잘라서 저장한다 (답변을 잃지 않게). 사용자 입력과 달리 거부하지 않는다.
    """
    if image_analysis and user_message_id is None:
        raise ValueError("image_analysis를 저장하려면 user_message_id가 필요합니다.")
    if get_conversation(session, conversation_id, user_id) is None:
        raise PermissionError("대화가 없거나 이 사용자의 대화가 아닙니다.")
    if user_message_id is not None:
        um = get_message(session, user_message_id, user_id)
        if um is None:
            raise PermissionError("메시지가 없거나 이 사용자의 메시지가 아닙니다.")
        if um.role != "user" or um.conversation_id != conversation_id:
            raise ValueError("user_message_id는 이 대화의 사용자 메시지여야 합니다.")

    msg = add_message(session, conversation_id, user_id, "assistant", answer)
    rows = add_sources(session, msg.id, user_id, sources) if sources else []
    if image_analysis:
        set_message_image_analysis(session, user_message_id, user_id, image_analysis)
    return AssistantTurn(message_id=msg.id, source_ids=[r.id for r in rows])
