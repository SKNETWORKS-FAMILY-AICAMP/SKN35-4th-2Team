"""관계형 DB (로그인, 대화 내역, 이력 반영, 답변 출처). 사용법은 repository.py 상단 참고."""

from .engine import init_db, make_engine, make_session_factory, session_scope
from .history import HistoryConfig, select_history
from .masking import mask_secrets
from .images import shrink_image
from .models import Base, Conversation, Message, MessageAttachment, MessageSource, User, UserProfile
from .session import db_session, get_engine, get_session_factory, reset_engine
from .sources import build_sources
from .turns import AssistantTurn, UserTurn, record_assistant_turn, record_user_turn
from .repository import (
    UsernameTakenError,
    add_image,
    add_message,
    add_sources,
    set_message_image_analysis,
    authenticate,
    change_password,
    create_conversation,
    create_user,
    delete_conversation,
    delete_image,
    get_conversation,
    get_history_context,
    get_image,
    get_message,
    image_bytes,
    get_sources,
    list_conversations,
    list_images,
    list_messages,
    list_users,
    reset_password,
    set_image_analysis,
    set_source_grounded,
    set_summary,
    set_user_active,
    thumbnail_bytes,
    update_profile,
)

__all__ = [
    "Base", "User", "UserProfile", "Conversation", "Message", "MessageSource", "MessageAttachment",
    "add_image", "list_images", "get_image", "image_bytes", "thumbnail_bytes", "set_image_analysis", "delete_image", "list_messages",
    "shrink_image", "set_message_image_analysis",
    "record_user_turn", "record_assistant_turn", "UserTurn", "AssistantTurn",
    "make_engine", "init_db", "make_session_factory", "session_scope",
    "db_session", "get_engine", "get_session_factory", "reset_engine",
    "HistoryConfig", "select_history", "mask_secrets",
    "UsernameTakenError", "create_user", "authenticate", "update_profile",
    "change_password", "set_user_active", "reset_password", "list_users",
    "create_conversation", "get_conversation", "list_conversations", "delete_conversation",
    "add_message", "get_message", "get_history_context", "set_summary",
    "add_sources", "get_sources", "set_source_grounded", "build_sources",
]
