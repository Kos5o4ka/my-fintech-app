"""Add deal_no column to transactions and buy_deal_no/sell_deal_no to bond_portfolio.

Revision ID: stage10_add_deal_no
Revises: stage9_fifo_and_audit_json
Create Date: 2026-05-27 22:50:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision = "stage10_add_deal_no"
down_revision = "stage9_fifo_and_audit_json"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspect_obj = reflection.Inspector.from_engine(conn)
    
    # 1. Handle transactions table
    existing_tx_cols = [c["name"] for c in inspect_obj.get_columns("transactions")]
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        if "deal_no" not in existing_tx_cols:
            batch_op.add_column(sa.Column("deal_no", sa.String(length=100), nullable=True))
            
            # Check if index already exists
            existing_indexes = [idx["name"] for idx in inspect_obj.get_indexes("transactions")]
            if "ix_transactions_deal_no" not in existing_indexes:
                batch_op.create_index("ix_transactions_deal_no", ["deal_no"], unique=False)

    # 2. Handle bond_portfolio table
    existing_bp_cols = [c["name"] for c in inspect_obj.get_columns("bond_portfolio")]
    with op.batch_alter_table("bond_portfolio", schema=None) as batch_op:
        if "buy_deal_no" not in existing_bp_cols:
            batch_op.add_column(sa.Column("buy_deal_no", sa.String(length=100), nullable=True))
        if "sell_deal_no" not in existing_bp_cols:
            batch_op.add_column(sa.Column("sell_deal_no", sa.String(length=100), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspect_obj = reflection.Inspector.from_engine(conn)
    
    # 1. Handle bond_portfolio table
    existing_bp_cols = [c["name"] for c in inspect_obj.get_columns("bond_portfolio")]
    with op.batch_alter_table("bond_portfolio", schema=None) as batch_op:
        if "sell_deal_no" in existing_bp_cols:
            batch_op.drop_column("sell_deal_no")
        if "buy_deal_no" in existing_bp_cols:
            batch_op.drop_column("buy_deal_no")

    # 2. Handle transactions table
    existing_tx_cols = [c["name"] for c in inspect_obj.get_columns("transactions")]
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        if "deal_no" in existing_tx_cols:
            # Check if index exists
            existing_indexes = [idx["name"] for idx in inspect_obj.get_indexes("transactions")]
            if "ix_transactions_deal_no" in existing_indexes:
                batch_op.drop_index("ix_transactions_deal_no")
            batch_op.drop_column("deal_no")
