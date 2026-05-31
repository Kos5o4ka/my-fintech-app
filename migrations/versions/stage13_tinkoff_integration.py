"""stage13: T-Invest integration — encrypted token storage + last sync timestamp

Revision ID: stage13_tinkoff_integration
Revises: 4ac2f4aea610
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa


revision = "stage13_tinkoff_integration"
down_revision = "4ac2f4aea610"
branch_labels = None
depends_on = None


def _col_exists(table, column):
    from sqlalchemy import inspect
    insp = inspect(op.get_bind())
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # tinkoff_token: расширяем до Text — Fernet-токен длиннее 255 байт
    if _col_exists("users", "tinkoff_token"):
        if dialect == "postgresql":
            op.execute("ALTER TABLE users ALTER COLUMN tinkoff_token TYPE TEXT")
        # SQLite не умеет ALTER COLUMN TYPE — String там уже хранит произвольную длину
    else:
        op.add_column("users", sa.Column("tinkoff_token", sa.Text(), nullable=True))

    if not _col_exists("users", "tinkoff_last_sync_at"):
        op.add_column(
            "users",
            sa.Column("tinkoff_last_sync_at", sa.DateTime(), nullable=True),
        )

    if not _col_exists("users", "tinkoff_account_id"):
        op.add_column(
            "users",
            sa.Column("tinkoff_account_id", sa.String(50), nullable=True),
        )


def downgrade():
    if _col_exists("users", "tinkoff_account_id"):
        op.drop_column("users", "tinkoff_account_id")
    if _col_exists("users", "tinkoff_last_sync_at"):
        op.drop_column("users", "tinkoff_last_sync_at")
