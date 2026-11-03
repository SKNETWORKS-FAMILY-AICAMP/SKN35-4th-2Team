"""users.is_active 컬럼 추가, message_sources 테이블 추가

- is_active: 이미 행이 있어도 추가할 수 있게 server_default(true)를 둔다. 기존 계정은 모두 활성.
- message_sources: 답변에 붙은 출처 (url, 제목, 버전, 발췌문, 점수, 근거 여부).

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

LongText = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "message_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("tech", sa.String(30), nullable=True),
        sa.Column("version", sa.String(30), nullable=True),
        sa.Column("doc_type", sa.String(30), nullable=True),
        sa.Column("snippet", LongText, nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("is_grounded", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_message_sources_message_id", "message_sources", ["message_id"])


def downgrade() -> None:
    op.drop_table("message_sources")
    op.drop_column("users", "is_active")
