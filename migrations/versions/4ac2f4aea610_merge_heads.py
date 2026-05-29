"""merge heads

Revision ID: 4ac2f4aea610
Revises: 5f2e8c2a8f0b, stage12_settings_notif
Create Date: 2026-05-29 17:58:41.728808

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4ac2f4aea610'
down_revision = ('5f2e8c2a8f0b', 'stage12_settings_notif')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
