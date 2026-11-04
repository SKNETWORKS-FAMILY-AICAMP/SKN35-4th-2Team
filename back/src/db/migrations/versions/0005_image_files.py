"""첨부 이미지를 DB가 아니라 서버 파일에 저장 (DB에는 경로만)

- file_path, thumb_path 추가: 새 이미지는 서버 디스크의 파일이고, 여기에 그 상대 경로를 둔다 (src/db/storage.py).
- data를 NULL 허용으로 바꾼다: 새 행은 원본 바이트를 DB에 두지 않는다.
  이전 방식으로 저장된 행은 data(와 thumb_data)가 그대로 남아 있어서 계속 읽을 수 있다.
  이전 행을 파일로 옮기려면: uv run python -m src.db.move_images_to_files

되돌리기(downgrade)는 data를 다시 NOT NULL로 만들기 때문에, 파일로 저장된 행(data가 NULL)이 하나라도 있으면 실패한다.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

LargeBlob = sa.LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql")


def upgrade() -> None:
    op.add_column("message_attachments", sa.Column("file_path", sa.String(255), nullable=True))
    op.add_column("message_attachments", sa.Column("thumb_path", sa.String(255), nullable=True))
    with op.batch_alter_table("message_attachments") as batch:
        batch.alter_column("data", existing_type=LargeBlob, nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("message_attachments") as batch:
        batch.alter_column("data", existing_type=LargeBlob, nullable=False)
        batch.drop_column("thumb_path")
        batch.drop_column("file_path")
