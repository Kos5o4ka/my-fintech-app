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
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_users_cols = []
    try:
        existing_users_cols = [c["name"] for c in inspector.get_columns("users")]
    except Exception:
        pass

    with op.batch_alter_table("users", schema=None) as batch_op:
        if "email" not in existing_users_cols:
            batch_op.add_column(sa.Column("email", sa.String(length=254), nullable=True))
        if "email_notifications" not in existing_users_cols:
            batch_op.add_column(
                sa.Column(
                    "email_notifications",
                    sa.Boolean(),
                    nullable=True,
                    server_default="false",
                )
            )

    existing_bp_cols = []
    try:
        existing_bp_cols = [c["name"] for c in inspector.get_columns("bond_portfolio")]
    except Exception:
        pass

    with op.batch_alter_table("bond_portfolio", schema=None) as batch_op:
        if "secid" not in existing_bp_cols:
            batch_op.add_column(sa.Column("secid", sa.String(length=50), nullable=True))
        if "name" not in existing_bp_cols:
            batch_op.add_column(sa.Column("name", sa.String(length=100), nullable=True))
        if "broker_commission" not in existing_bp_cols:
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
