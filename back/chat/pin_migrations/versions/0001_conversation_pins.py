"""Web conversation pin storage; independent of AI engine migrations."""
from alembic import op
import sqlalchemy as sa

revision = "pin_0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("conversation_pins",
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    op.create_index("ix_conversation_pins_user_id", "conversation_pins", ["user_id"])

def downgrade():
    op.drop_index("ix_conversation_pins_user_id", table_name="conversation_pins")
    op.drop_table("conversation_pins")
