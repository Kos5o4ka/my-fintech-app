"""stage2: add telegram_chat_id and telegram_notifications to users

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-23 00:01:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("telegram_chat_id", sa.String(length=20), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "telegram_notifications",
                sa.Boolean(),
                nullable=True,
                server_default="false",
            )
        )
        batch_op.create_unique_constraint(
            "uq_users_telegram_chat_id", ["telegram_chat_id"]
        )


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("uq_users_telegram_chat_id", type_="unique")
        batch_op.drop_column("telegram_notifications")
        batch_op.drop_column("telegram_chat_id")
