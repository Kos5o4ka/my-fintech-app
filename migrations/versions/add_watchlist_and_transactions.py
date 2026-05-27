"""add watchlist and transactions tables

Revision ID: a1b2c3d4e5f6
Revises: ca104efdddb2
Create Date: 2026-05-22 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "23805777d53a"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = []
    try:
        existing_tables = inspector.get_table_names()
    except Exception:
        pass

    if "transactions" not in existing_tables:
        op.create_table(
            "transactions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("isin", sa.String(length=12), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=True),
            sa.Column("tx_type", sa.String(length=4), nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("commission", sa.Numeric(precision=10, scale=4), nullable=True),
            sa.Column("tx_date", sa.Date(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("transactions", schema=None) as batch_op:
            try:
                batch_op.create_index("ix_tx_user_id", ["user_id"], unique=False)
            except Exception:
                pass

    if "watchlist" not in existing_tables:
        op.create_table(
            "watchlist",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("isin", sa.String(length=12), nullable=False),
            sa.Column("secid", sa.String(length=50), nullable=True),
            sa.Column("name", sa.String(length=100), nullable=True),
            sa.Column("added_at", sa.Date(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "isin", name="uq_watchlist_user_isin"),
        )
        with op.batch_alter_table("watchlist", schema=None) as batch_op:
            try:
                batch_op.create_index("ix_wl_user_id", ["user_id"], unique=False)
            except Exception:
                pass


def downgrade():
    with op.batch_alter_table("watchlist", schema=None) as batch_op:
        batch_op.drop_index("ix_wl_user_id")
    op.drop_table("watchlist")

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index("ix_tx_user_id")
    op.drop_table("transactions")
