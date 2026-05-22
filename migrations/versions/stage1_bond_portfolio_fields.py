"""stage1: add currency and updated_at to bond_portfolio, add ix_bp_isin index

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bond_portfolio', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('currency', sa.String(length=3), nullable=False, server_default='RUB')
        )
        batch_op.add_column(
            sa.Column('updated_at', sa.DateTime(), nullable=True)
        )
        batch_op.create_index('ix_bp_isin', ['isin'], unique=False)


def downgrade():
    with op.batch_alter_table('bond_portfolio', schema=None) as batch_op:
        batch_op.drop_index('ix_bp_isin')
        batch_op.drop_column('updated_at')
        batch_op.drop_column('currency')
