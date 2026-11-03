"""
관계형 DB 테이블 정의 (사용자 / 프로필 / 대화 / 메시지).

설계 원칙
- 시간은 항상 UTC로 저장한다. TiDB Cloud 서버 시간대가 UTC라 NOW()를 쓰면
  한국 시간과 어긋났던 2차 프로젝트 경험이 있어서, DB가 아니라 파이썬에서 시각을 채운다.
- username은 소문자로만 저장한다. MySQL/TiDB는 기본적으로 대소문자를 구분하지 않고
  SQLite는 구분해서, 같은 이름이 DB마다 다르게 중복 판정되는 일을 막기 위해서다.
- 긴 본문(코드, 오류 로그)은 MySQL의 TEXT(64KB)가 부족할 수 있어 MEDIUMTEXT로 올린다.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    true,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# 일반 DB에서는 Text, MySQL/TiDB에서는 MEDIUMTEXT(약 16MB)로 만든다.
LongText = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
# 이미지 바이트용. MySQL의 기본 BLOB은 64KB까지라서 MEDIUMBLOB(약 16MB)로 올린다.
LargeBlob = LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql")


def utcnow() -> datetime:
    """시간대 정보 없는(naive) UTC 현재 시각. MySQL DATETIME은 시간대를 저장하지 않는다."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # 비활성 계정은 로그인할 수 없다 (삭제하지 않고 막기만 할 때 쓴다).
    # server_default는 이미 행이 있는 테이블에 컬럼을 추가할 때(마이그레이션) 필요하다.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(Base):
    """사용자가 자주 쓰는 개발 환경. 질문할 때 환경 정보를 매번 다시 묻지 않기 위한 기본값."""

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    python_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    os: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 예: {"langchain": "1.4.3", "langgraph": "1.2.14", "mcp": "2.3.0"}
    lib_versions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="profile")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="새 대화")
    # 오래된 대화를 압축한 요약. summary_upto_message_id까지의 메시지가 요약에 반영돼 있다.
    # (messages와 서로 참조하는 순환을 피하려고 이 컬럼에는 외래키를 걸지 않는다.)
    summary: Mapped[str | None] = mapped_column(LongText, nullable=True)
    summary_upto_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    input_type: Mapped[str] = mapped_column(String(16), default="text")  # "text" | "image"
    content: Mapped[str] = mapped_column(LongText)
    # 사용자 메시지에 이미지가 있을 때 비전 모델이 읽어 낸 텍스트 (메시지 단위, 그래프 State의 image_analysis와 같은 단위).
    # 이후 질문에 이력을 붙일 때 content와 함께 쓴다 (이미지 원본은 LLM에 다시 보내지 않는다).
    image_analysis: Mapped[str | None] = mapped_column(LongText, nullable=True)
    # 질문 시점의 환경 스냅샷. 나중에 "그때 어떤 버전이었는지" 알기 위해 같이 저장한다.
    env_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    sources: Mapped[list["MessageSource"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="MessageSource.rank"
    )
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="MessageAttachment.position"
    )


class MessageAttachment(Base):
    """사용자 메시지에 딸린 이미지 (화면에 다시 보여 주기 위한 원본 보관용).

    - 이미지 원본과 썸네일은 DB가 아니라 서버 디스크의 파일이다. 여기에는 그 파일의 상대 경로만 둔다
      (file_path = 원본, thumb_path = 썸네일, 저장 폴더는 src/db/storage.py).
    - data, thumb_data(DB에 직접 둔 바이트)는 이전 방식으로 저장된 행을 읽기 위해 남겨 둔 것이다. 새 행은 NULL이다.
      읽을 때는 파일 경로가 있으면 파일, 없으면 이 칸을 쓴다 (repository.image_bytes, thumbnail_bytes).
    - 이미지에서 읽어 낸 텍스트는 메시지 본문(content)에 들어간다.
    - LLM에 넘기는 대화 이력에는 이미지가 아니라 텍스트(analysis_text/content)만 쓴다.
    - data는 deferred라서, 첨부 목록을 읽을 때는 가져오지 않는다.
    """

    __tablename__ = "message_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)  # 한 메시지 안에서의 순서 (0부터)
    mime_type: Mapped[str] = mapped_column(String(50))  # 호출자가 준 값이 아니라 바이트로 판별한 값
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 원본 파일의 상대 경로 (storage.py)
    thumb_path: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 썸네일 파일의 상대 경로
    data: Mapped[bytes | None] = mapped_column(LargeBlob, nullable=True, deferred=True)  # 이전 방식(DB 저장)의 원본
    thumb_data: Mapped[bytes | None] = mapped_column(LargeBlob, nullable=True)  # 이전 방식(DB 저장)의 썸네일
    analysis_text: Mapped[str | None] = mapped_column(LongText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    message: Mapped["Message"] = relationship(back_populates="attachments")


class MessageSource(Base):
    """답변에 붙은 출처 한 건.

    문서 조각(청크)과 벡터는 FAISS 쪽에 있어서 외래키로 묶을 대상이 이 DB에는 없다.
    그래서 출처 정보를 그대로 복사해 저장한다. 대화를 다시 열어도 출처가 보이고,
    나중에 문서가 바뀌거나 사라져도 "그때 답변이 근거로 삼은 내용"이 남는다.
    """

    __tablename__ = "message_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer, default=0)  # 검색 결과 순위(0이 가장 위)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tech: Mapped[str | None] = mapped_column(String(30), nullable=True)  # langchain/langgraph/mcp
    version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # docs/issue/readme/release
    snippet: Mapped[str | None] = mapped_column(LongText, nullable=True)  # 근거로 쓴 발췌문
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 환각 점검에서 "이 출처가 실제로 답변의 근거였는가"를 나중에 채운다 (None = 아직 점검 전).
    is_grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    message: Mapped[Message] = relationship(back_populates="sources")
