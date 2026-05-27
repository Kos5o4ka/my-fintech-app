"""Add deal_no column to transactions and buy_deal_no/sell_deal_no to bond_portfolio.

Revision ID: stage10_add_deal_no
Revises: stage9_fifo_and_audit_json
Create Date: 2026-05-27 22:50:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "stage10_add_deal_no"
down_revision = "stage9_fifo_and_audit_json"
branch_labels = None
depends_on = None


def upgrade():
    # Add deal_no to transactions
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deal_no", sa.String(length=100), nullable=True))
        batch_op.create_index("ix_transactions_deal_no", ["deal_no"], unique=False)

    # Add buy_deal_no and sell_deal_no to bond_portfolio
    with op.batch_alter_table("bond_portfolio", schema=None) as batch_op:
        batch_op.add_column(sa.Column("buy_deal_no", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("sell_deal_no", sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table("bond_portfolio", schema=None) as batch_op:
        batch_op.drop_column("sell_deal_no")
        batch_op.drop_column("buy_deal_no")

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index("ix_transactions_deal_no")
        batch_op.drop_column("deal_no")
