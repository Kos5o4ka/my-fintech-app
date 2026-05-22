"""stage4: add notes column to bond_portfolio

Revision ID: f6g7h8i9j0k1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-23 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6g7h8i9j0k1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bond_portfolio', sa.Column('notes', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('bond_portfolio', 'notes')
