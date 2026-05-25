"""fix missing columns in users and bond_portfolio

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-22 00:01:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=254), nullable=True))
        batch_op.add_column(
            sa.Column(
                "email_notifications",
                sa.Boolean(),
                nullable=True,
                server_default="false",
            )
        )

    with op.batch_alter_table("bond_portfolio", schema=None) as batch_op:
        batch_op.add_column(sa.Column("secid", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("name", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column(
                "broker_commission", sa.Numeric(precision=10, scale=4), nullable=True
            )
        )


def downgrade():
    with op.batch_alter_table("bond_portfolio", schema=None) as batch_op:
        batch_op.drop_column("broker_commission")
        batch_op.drop_column("name")
        batch_op.drop_column("secid")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email_notifications")
        batch_op.drop_column("email")
