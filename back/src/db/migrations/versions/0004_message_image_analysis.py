"""messages.image_analysis 컬럼 추가 (이미지에서 읽어 낸 텍스트, 메시지 단위)

그래프 State의 image_analysis는 이미지 여러 장에 대해 문자열 하나라서, 첨부별(message_attachments.analysis_text)이
아니라 메시지 단위로도 둔다. 이후 질문에 대화 이력을 붙일 때 이 텍스트를 함께 쓴다.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

LongText = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    op.add_column("messages", sa.Column("image_analysis", LongText, nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "image_analysis")
