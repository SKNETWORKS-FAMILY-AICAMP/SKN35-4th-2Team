"""
DB 읽기/쓰기 함수 (로그인, 대화, 메시지, 이력 조회).

모든 함수는 Session을 첫 인자로 받는다. commit은 호출하는 쪽(session_scope)이 한다.

보안 원칙
- 대화와 메시지는 항상 user_id로 소유자를 확인한다. conversation_id만 알아서는
  다른 사람의 대화를 읽거나 쓸 수 없다 (소유자가 아니면 None / PermissionError).
- 로그인 실패 원인(없는 아이디 vs 틀린 비밀번호)을 구분해서 알려 주지 않고,
  없는 아이디일 때도 해시 계산을 한 번 해서 응답 시간 차이로 아이디 존재를 알 수 없게 한다.
"""

import re

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .history import HistoryConfig, estimate_tokens, select_history
from .limits import clip_text, message_max_chars, snippet_max_chars, summary_max_chars
from .images import (
    clip_analysis,
    make_thumbnail,
    max_images_per_message,
    sha256_hex,
    validate_image,
)
from . import storage
from .masking import mask_secrets
from .models import (
    Conversation,
    Message,
    MessageAttachment,
    MessageSource,
    User,
    UserProfile,
    utcnow,
)
from .security import hash_password, verify_password

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")
_VALID_ROLES = {"user", "assistant"}
_VALID_INPUT_TYPES = {"text", "image"}
# 없는 아이디로 로그인할 때 비교용으로 쓰는 가짜 해시 (응답 시간을 맞추기 위함)
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class UsernameTakenError(Exception):
    pass


def normalize_username(username: str) -> str:
    return username.strip().lower()


# ---------------------------------------------------------------- 사용자 / 로그인
def create_user(
    session: Session, username: str, password: str, *, is_admin: bool = False
) -> User:
    name = normalize_username(username)
    if not _USERNAME_RE.match(name):
        raise ValueError("아이디는 영문 소문자, 숫자, 밑줄(_) 3~30자여야 합니다.")
    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    user = User(username=name, password_hash=hash_password(password), is_admin=is_admin)
    session.add(user)
    try:
        session.flush()  # 중복이면 여기서 IntegrityError가 난다
    except IntegrityError as exc:
        session.rollback()
        raise UsernameTakenError(name) from exc
    return user


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(
        select(User).where(User.username == normalize_username(username))
    )
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    # 비활성 계정도 비밀번호 검증을 거친 뒤 같은 실패(None)로 돌려준다.
    # (비활성인지 여부가 로그인 실패 응답으로 드러나지 않게 하려는 것)
    password_ok = verify_password(password, user.password_hash)
    if not password_ok or not user.is_active:
        return None
    user.last_login_at = utcnow()
    return user


# ---------------------------------------------------------------- 계정 관리
def change_password(session: Session, user_id: int, old_password: str, new_password: str) -> bool:
    """현재 비밀번호를 확인한 뒤 바꾼다. 틀리면 False."""
    user = session.get(User, user_id)
    if user is None or not user.is_active or not verify_password(old_password, user.password_hash):
        return False
    if len(new_password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    user.password_hash = hash_password(new_password)
    return True


def _require_admin(session: Session, admin_id: int) -> User:
    admin = session.get(User, admin_id)
    if admin is None or not admin.is_admin or not admin.is_active:
        raise PermissionError("관리자만 할 수 있습니다.")
    return admin


def set_user_active(session: Session, admin_id: int, target_username: str, active: bool) -> bool:
    """관리자가 계정을 비활성화/활성화한다. 자기 자신은 비활성화할 수 없다."""
    admin = _require_admin(session, admin_id)
    target = session.scalar(select(User).where(User.username == normalize_username(target_username)))
    if target is None:
        return False
    if target.id == admin.id and not active:
        raise ValueError("자기 자신은 비활성화할 수 없습니다.")
    target.is_active = active
    return True


def reset_password(session: Session, admin_id: int, target_username: str, new_password: str) -> bool:
    """관리자가 비밀번호를 초기화한다 (이메일이 없어서 '비밀번호 찾기' 대신 쓰는 방법)."""
    _require_admin(session, admin_id)
    target = session.scalar(select(User).where(User.username == normalize_username(target_username)))
    if target is None:
        return False
    if len(new_password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    target.password_hash = hash_password(new_password)
    return True


def list_users(session: Session, admin_id: int) -> list[User]:
    _require_admin(session, admin_id)
    return list(session.scalars(select(User).order_by(User.id)))


def update_profile(
    session: Session,
    user_id: int,
    *,
    python_version: str | None = None,
    os: str | None = None,
    lib_versions: dict | None = None,
) -> UserProfile:
    """넘긴 값만 바꾼다 (None은 '변경 없음'). 프로필이 없으면 만든다."""
    profile = session.get(UserProfile, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id)
        session.add(profile)
    if python_version is not None:
        profile.python_version = python_version
    if os is not None:
        profile.os = os
    if lib_versions is not None:
        profile.lib_versions = lib_versions
    return profile


# ---------------------------------------------------------------- 대화
def create_conversation(
    session: Session, user_id: int, title: str | None = None
) -> Conversation:
    conv = Conversation(user_id=user_id, title=title or "새 대화")
    session.add(conv)
    session.flush()
    return conv


def get_conversation(
    session: Session, conversation_id: int, user_id: int
) -> Conversation | None:
    """소유자가 아니면 없는 것처럼 None을 돌려준다 (존재 여부도 알려 주지 않는다)."""
    conv = session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        return None
    return conv


def list_conversations(session: Session, user_id: int, limit: int = 50) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def delete_conversation(session: Session, conversation_id: int, user_id: int) -> bool:
    conv = get_conversation(session, conversation_id, user_id)
    if conv is None:
        return False
    rows = session.execute(
        select(MessageAttachment.file_path, MessageAttachment.thumb_path)
        .join(Message, Message.id == MessageAttachment.message_id)
        .where(Message.conversation_id == conv.id)
    ).all()
    session.delete(conv)
    session.flush()
    storage.remove_files(*(path for row in rows for path in row))  # DB에서 지운 뒤에 이미지 파일도 지운다
    return True


# ---------------------------------------------------------------- 메시지
def add_message(
    session: Session,
    conversation_id: int,
    user_id: int,
    role: str,
    content: str,
    *,
    input_type: str = "text",
    env_snapshot: dict | None = None,
    mask: bool = True,
) -> Message:
    """mask=True면 저장 전에 API 키 같은 비밀을 [MASKED:...]로 가린다 (masking.py 참고)."""
    if role not in _VALID_ROLES:
        raise ValueError(f"role은 {sorted(_VALID_ROLES)} 중 하나여야 합니다.")
    if input_type not in _VALID_INPUT_TYPES:
        raise ValueError(f"input_type은 {sorted(_VALID_INPUT_TYPES)} 중 하나여야 합니다.")
    conv = get_conversation(session, conversation_id, user_id)
    if conv is None:
        raise PermissionError("대화가 없거나 이 사용자의 대화가 아닙니다.")

    if mask:
        content = mask_secrets(content)

    # TiDB는 한 행이 6MiB를 넘으면 불투명한 오류를 내므로(limits.py), 그 전에 처리한다.
    # 사용자 입력은 이유를 알려 주며 거부하고, 모델이 만든 답변은 잘라서 저장한다 (답변을 잃지 않게).
    limit = message_max_chars()
    if len(content) > limit:
        if role == "user":
            raise ValueError(f"메시지는 {limit}자 이하여야 합니다 (현재 {len(content)}자).")
        content = clip_text(content, limit)

    msg = Message(
        conversation_id=conv.id,
        role=role,
        input_type=input_type,
        content=content,
        env_snapshot=env_snapshot,
        token_count=estimate_tokens(content),
    )
    session.add(msg)
    # 첫 질문이면 제목으로 쓴다 (앞 40자)
    if role == "user" and conv.title == "새 대화":
        conv.title = " ".join(content.split())[:40] or "새 대화"
    conv.updated_at = utcnow()
    session.flush()
    return msg


def get_history_context(
    session: Session,
    conversation_id: int,
    user_id: int,
    config: HistoryConfig | None = None,
) -> list[dict]:
    """다음 질문에 붙일 이력을 상한 안에서 만들어 돌려준다."""
    config = config or HistoryConfig.from_env()
    conv = get_conversation(session, conversation_id, user_id)
    if conv is None:
        raise PermissionError("대화가 없거나 이 사용자의 대화가 아닙니다.")

    # attachments는 메타데이터만 읽는다 (원본 이미지 data는 deferred라 읽지 않는다).
    stmt = (
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.conversation_id == conv.id)
    )
    if conv.summary and conv.summary_upto_message_id:
        # 이미 요약에 반영된 메시지는 다시 넣지 않는다.
        stmt = stmt.where(Message.id > conv.summary_upto_message_id)
    # 필요한 만큼만 최신순으로 읽고 다시 시간순으로 뒤집는다 (대화가 길어도 읽는 양이 일정).
    rows = list(
        session.scalars(stmt.order_by(Message.id.desc()).limit(max(config.max_turns, 0) * 2))
    )[::-1]
    return select_history([_history_item(m) for m in rows], conv.summary, config)


def _history_item(m: Message) -> dict:
    """이력에 넣을 메시지 한 건. 이미지가 있으면 원본이 아니라 '읽어 낸 텍스트'를 본문 뒤에 붙인다."""
    analysis = m.image_analysis or "\n".join(a.analysis_text for a in m.attachments if a.analysis_text)
    if not analysis:
        return {"role": m.role, "content": m.content, "token_count": m.token_count}
    text = f"{m.content}\n\n[첨부 이미지에서 읽은 내용] {analysis}" if m.content else f"[첨부 이미지에서 읽은 내용] {analysis}"
    return {"role": m.role, "content": text, "token_count": estimate_tokens(text)}


def get_message(session: Session, message_id: int, user_id: int) -> Message | None:
    """메시지의 소유자는 대화의 소유자다. 남의 메시지는 None."""
    msg = session.get(Message, message_id)
    if msg is None or get_conversation(session, msg.conversation_id, user_id) is None:
        return None
    return msg


def list_messages(
    session: Session, conversation_id: int, user_id: int, limit: int | None = None
) -> list[Message]:
    """대화의 메시지를 시간순(오래된 것 먼저)으로 돌려준다. 화면에 대화 내역을 그릴 때 쓴다.

    limit을 주면 가장 최근 limit개만 (그래도 시간순). 각 메시지의 attachments(이미지 메타데이터)와
    sources(출처)는 접근할 때 읽힌다. 이미지 원본(data)은 attachment.data에 접근하기 전에는 읽지 않는다.
    """
    conv = get_conversation(session, conversation_id, user_id)
    if conv is None:
        raise PermissionError("대화가 없거나 이 사용자의 대화가 아닙니다.")
    stmt = select(Message).where(Message.conversation_id == conv.id)
    if limit is not None:
        rows = list(session.scalars(stmt.order_by(Message.id.desc()).limit(max(limit, 0))))[::-1]
    else:
        rows = list(session.scalars(stmt.order_by(Message.id)))
    return rows


# ---------------------------------------------------------------- 이미지 첨부
def add_image(
    session: Session,
    message_id: int,
    user_id: int,
    data: bytes,
    *,
    analysis_text: str | None = None,
) -> MessageAttachment:
    """사용자 메시지에 이미지 한 장을 붙인다.

    - 형식은 파일의 실제 바이트로 판별한다 (png/jpeg/webp만).
    - 한 장의 크기와 한 메시지의 장수에는 상한이 있다 (images.py의 IMAGE_MAX_BYTES, IMAGE_MAX_PER_MESSAGE).
    - 이미지에서 읽은 텍스트는 보통 메시지 본문에 넣고, analysis_text는 이미지별 기록용이다.
    """
    msg = get_message(session, message_id, user_id)
    if msg is None:
        raise PermissionError("메시지가 없거나 이 사용자의 메시지가 아닙니다.")
    if msg.role != "user":
        raise ValueError("이미지는 사용자(user) 메시지에만 붙일 수 있습니다.")
    mime, width, height = validate_image(data)  # 비어 있음, 크기 상한, 형식, 깨짐을 한꺼번에 검사

    count = session.scalar(
        select(func.count()).select_from(MessageAttachment).where(MessageAttachment.message_id == msg.id)
    )
    if count >= max_images_per_message():
        raise ValueError(f"한 메시지에는 이미지를 {max_images_per_message()}장까지 붙일 수 있습니다.")
    last_pos = session.scalar(
        select(func.max(MessageAttachment.position)).where(MessageAttachment.message_id == msg.id)
    )

    position = 0 if last_pos is None else last_pos + 1
    digest = sha256_hex(data)
    original_path, thumb_path = storage.relative_paths(msg.id, position, digest, mime)
    thumb = make_thumbnail(data)
    written: list[str] = []
    try:
        # 원본과 썸네일은 서버 디스크에 파일로 두고, DB에는 경로만 저장한다 (storage.py).
        storage.write_file(original_path, data)
        written.append(original_path)
        if thumb:
            storage.write_file(thumb_path, thumb)
            written.append(thumb_path)
        att = MessageAttachment(
            message_id=msg.id,
            position=position,
            mime_type=mime,
            size_bytes=len(data),
            width=width,
            height=height,
            sha256=digest,
            file_path=original_path,
            thumb_path=thumb_path if thumb else None,
            analysis_text=clip_analysis(mask_secrets(analysis_text)) if analysis_text else analysis_text,
        )
        session.add(att)
        session.flush()
    except BaseException:
        storage.remove_files(*written)  # DB에 못 넣었으면 방금 쓴 파일도 지운다
        raise
    return att


def image_bytes(att: MessageAttachment) -> bytes | None:
    """이미지 원본 바이트. 파일로 저장된 이미지는 파일에서, 이전 방식으로 DB에 저장된 이미지는 DB에서 읽는다.

    파일 경로가 있는데 파일이 없으면 FileNotFoundError (저장 폴더가 지워졌거나 다른 서버일 때).
    """
    if att.file_path:
        return storage.read_file(att.file_path)
    return att.data


def thumbnail_bytes(att: MessageAttachment) -> bytes | None:
    """화면에 보여 줄 썸네일 바이트. 파일이 없거나 읽을 수 없으면 None (화면이 멈추지 않게 예외를 내지 않는다)."""
    if att.thumb_path:
        try:
            return storage.read_file(att.thumb_path)
        except (OSError, ValueError):
            return None
    return att.thumb_data


def set_message_image_analysis(session: Session, message_id: int, user_id: int, text: str) -> None:
    """사용자 메시지에 '이미지에서 읽어 낸 텍스트'(메시지 단위)를 저장한다. 그래프의 image_analysis를 넣는 곳.

    이후 질문에 대화 이력을 붙일 때 이 텍스트가 질문 본문 뒤에 함께 들어간다 (원본 이미지는 LLM에 다시 보내지 않는다).
    """
    msg = get_message(session, message_id, user_id)
    if msg is None:
        raise PermissionError("메시지가 없거나 이 사용자의 메시지가 아닙니다.")
    if msg.role != "user":
        raise ValueError("이미지 분석 텍스트는 사용자(user) 메시지에만 붙일 수 있습니다.")
    msg.image_analysis = clip_analysis(mask_secrets(text))


def list_images(session: Session, message_id: int, user_id: int) -> list[MessageAttachment]:
    """메시지의 이미지 목록 (메타데이터와 파일 경로). 이미지 바이트는 image_bytes, thumbnail_bytes로 읽는다."""
    msg = get_message(session, message_id, user_id)
    if msg is None:
        raise PermissionError("메시지가 없거나 이 사용자의 메시지가 아닙니다.")
    return list(msg.attachments)


def get_image(session: Session, attachment_id: int, user_id: int) -> MessageAttachment | None:
    """이미지 한 장의 정보. 없거나 남의 것이면 None. 원본 바이트는 image_bytes(att)로 읽는다."""
    att = session.get(MessageAttachment, attachment_id)
    if att is None or get_message(session, att.message_id, user_id) is None:
        return None
    if not att.file_path:
        _ = att.data  # 이전 방식(DB 저장)의 이미지는 원본 바이트를 지금 읽어 둔다
    return att


def set_image_analysis(session: Session, attachment_id: int, user_id: int, text: str) -> None:
    """이미지를 저장한 뒤 비전 모델이 읽은 텍스트를 나중에 채울 때 쓴다."""
    att = session.get(MessageAttachment, attachment_id)
    if att is None or get_message(session, att.message_id, user_id) is None:
        raise PermissionError("이미지가 없거나 이 사용자의 이미지가 아닙니다.")
    att.analysis_text = clip_analysis(mask_secrets(text))


def delete_image(session: Session, attachment_id: int, user_id: int) -> bool:
    att = session.get(MessageAttachment, attachment_id)
    if att is None or get_message(session, att.message_id, user_id) is None:
        return False
    paths = (att.file_path, att.thumb_path)
    session.delete(att)
    session.flush()
    storage.remove_files(*paths)  # DB에서 지운 뒤에 파일을 지운다
    return True


# ---------------------------------------------------------------- 답변 출처
_SOURCE_FIELDS = {"url", "title", "tech", "version", "doc_type", "snippet", "score"}


def add_sources(
    session: Session, message_id: int, user_id: int, sources: list[dict], *, mask: bool = True
) -> list[MessageSource]:
    """답변(assistant 메시지)에 출처 목록을 붙인다. 순서가 곧 rank다.

    sources 각 항목: {"url"(필수), "title", "tech", "version", "doc_type", "snippet", "score"}
    """
    msg = get_message(session, message_id, user_id)
    if msg is None:
        raise PermissionError("메시지가 없거나 이 사용자의 메시지가 아닙니다.")
    if msg.role != "assistant":
        raise ValueError("출처는 assistant 메시지에만 붙일 수 있습니다.")

    rows: list[MessageSource] = []
    for rank, src in enumerate(sources):
        unknown = set(src) - _SOURCE_FIELDS
        if unknown:
            raise ValueError(f"알 수 없는 출처 필드: {sorted(unknown)}")
        if not src.get("url"):
            raise ValueError("출처에는 url이 필요합니다.")
        data = dict(src)
        if mask and data.get("snippet"):
            data["snippet"] = mask_secrets(data["snippet"])
        if data.get("snippet"):
            data["snippet"] = clip_text(data["snippet"], snippet_max_chars())  # 한 행이 6MiB를 넘지 않게
        rows.append(MessageSource(message_id=msg.id, rank=rank, **data))
    session.add_all(rows)
    session.flush()
    return rows


def get_sources(session: Session, message_id: int, user_id: int) -> list[MessageSource]:
    msg = get_message(session, message_id, user_id)
    if msg is None:
        raise PermissionError("메시지가 없거나 이 사용자의 메시지가 아닙니다.")
    return list(msg.sources)


def set_source_grounded(session: Session, source_id: int, grounded: bool) -> None:
    """환각 점검 결과를 기록한다 (점검 코드가 호출. 사용자 권한과 무관한 내부용)."""
    src = session.get(MessageSource, source_id)
    if src is None:
        raise ValueError("출처가 없습니다.")
    src.is_grounded = grounded


def set_summary(
    session: Session,
    conversation_id: int,
    user_id: int,
    summary: str,
    upto_message_id: int,
) -> None:
    """요약 텍스트를 만드는 일(LLM 호출)은 다른 곳에서 하고, 여기서는 저장만 한다."""
    conv = get_conversation(session, conversation_id, user_id)
    if conv is None:
        raise PermissionError("대화가 없거나 이 사용자의 대화가 아닙니다.")
    conv.summary = clip_text(summary, summary_max_chars())
    conv.summary_upto_message_id = upto_message_id
