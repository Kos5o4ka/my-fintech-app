"""stage7: add currency column to transactions table

Revision ID: stage7_transaction_currency
Revises: stage6_telegram_username
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "stage7_transaction_currency"
down_revision = "stage6_telegram_username"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("transactions")]
    if "currency" not in columns:
        with op.batch_alter_table("transactions") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "currency", sa.String(3), nullable=False, server_default="RUB"
                )
            )


def downgrade():
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("currency")
