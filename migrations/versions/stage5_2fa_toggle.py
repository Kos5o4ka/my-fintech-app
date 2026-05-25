"""stage5: add two_fa_enabled to users

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa

revision = "g7h8i9j0k1l2"
down_revision = "f6g7h8i9j0k1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("two_fa_enabled", sa.Boolean(), nullable=True))
    op.execute("UPDATE users SET two_fa_enabled = true")
    op.alter_column(
        "users", "two_fa_enabled", nullable=False, server_default=sa.text("true")
    )


def downgrade():
    op.drop_column("users", "two_fa_enabled")
