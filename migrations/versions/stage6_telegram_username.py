"""Add telegram_username column to users table.

Revision ID: stage6_telegram_username
Revises: stage5_2fa_toggle
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "stage6_telegram_username"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("telegram_username", sa.String(64), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("telegram_username")
