"""Expand Transaction.tx_type VARCHAR(4) → VARCHAR(10) to support 'coupon'."""

from alembic import op
import sqlalchemy as sa

revision = "stage8_tx_type"
down_revision = "stage7_transaction_currency"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.alter_column(
            "tx_type",
            existing_type=sa.String(4),
            type_=sa.String(10),
            nullable=False,
        )


def downgrade():
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.alter_column(
            "tx_type",
            existing_type=sa.String(10),
            type_=sa.String(4),
            nullable=False,
        )
