"""Web-only conversation pins, stored in the same SQLAlchemy database as chats."""
from sqlalchemy import Column, Integer, MetaData, Table, delete, inspect, select
from src.db.models import Conversation

metadata = MetaData()
conversation_pins = Table(
    "conversation_pins", metadata,
    Column("conversation_id", Integer, primary_key=True),
    Column("user_id", Integer, nullable=False, index=True),
)


class PinsNotReadyError(RuntimeError):
    pass


def pins_ready(session):
    # Do not cache: a migration can finish while the application is running.
    return inspect(session.connection()).has_table("conversation_pins")


def set_conversation_pin(session, conversation_id, user_id, pinned):
    if type(pinned) is not bool:
        raise ValueError("고정 여부는 true 또는 false여야 합니다.")
    # Serialize changes to this conversation; repeated pin requests are idempotent.
    conv = session.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    ).with_for_update())
    if conv is None:
        raise PermissionError("대화가 없거나 접근할 수 없습니다.")
    if not pins_ready(session):
        raise PinsNotReadyError("대화 고정 기능이 아직 준비되지 않았습니다. 관리자에게 문의해 주세요.")
    existing = session.scalar(select(conversation_pins.c.conversation_id).where(
        conversation_pins.c.conversation_id == conversation_id))
    if pinned and existing is None:
        session.execute(conversation_pins.insert().values(conversation_id=conversation_id, user_id=user_id))
    elif not pinned:
        delete_pin(session, conversation_id, user_id)


def delete_pin(session, conversation_id, user_id):
    if not pins_ready(session):
        return
    session.execute(delete(conversation_pins).where(
        conversation_pins.c.conversation_id == conversation_id,
        conversation_pins.c.user_id == user_id,
    ))


def pinned_conversations(session, user_id):
    if not pins_ready(session):
        return []
    return list(session.scalars(select(Conversation).join(
        conversation_pins, conversation_pins.c.conversation_id == Conversation.id
    ).where(Conversation.user_id == user_id, conversation_pins.c.user_id == user_id)
      .order_by(Conversation.updated_at.desc(), Conversation.id.desc())))
