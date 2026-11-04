"""message_attachments 테이블 추가 (사용자 메시지에 딸린 이미지)

- data: 원본 바이트. MySQL/TiDB에서는 MEDIUMBLOB (기본 BLOB은 64KB까지라 부족하다).
- thumb_data: 대화 목록용 작은 미리보기(JPEG).
- 메시지가 삭제되면 첨부도 함께 삭제된다 (ON DELETE CASCADE).

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

LargeBlob = sa.LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql")
LongText = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("data", LargeBlob, nullable=False),
        sa.Column("thumb_data", LargeBlob, nullable=True),
        sa.Column("analysis_text", LongText, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"])


def downgrade() -> None:
    op.drop_table("message_attachments")
