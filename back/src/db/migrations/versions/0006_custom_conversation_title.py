"""Preserve user-selected conversation titles."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("conversations", sa.Column("title_is_custom", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("title_is_custom")
