"""stage12: user settings, audit category, site notifications

Revision ID: stage12_settings_notif
Revises: stage9_fifo_and_audit_json
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "stage12_settings_notif"
down_revision = "stage9_fifo_and_audit_json"
branch_labels = None
depends_on = None


def _col_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def _table_exists(table):
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)
    return table in insp.get_table_names()


def upgrade():
    # ── User settings columns ─────────────────────────────────────────
    if not _col_exists("users", "theme"):
        op.add_column("users", sa.Column("theme", sa.String(10), server_default="system", nullable=False))
    if not _col_exists("users", "notif_time"):
        op.add_column("users", sa.Column("notif_time", sa.String(5), server_default="09:00", nullable=False))
    if not _col_exists("users", "notif_timezone"):
        op.add_column("users", sa.Column("notif_timezone", sa.String(64), server_default="Europe/Moscow", nullable=False))
    if not _col_exists("users", "oferta_advance_days"):
        op.add_column("users", sa.Column("oferta_advance_days", sa.Integer(), server_default="14", nullable=False))

    # ── AuditLog category column ──────────────────────────────────────
    if not _col_exists("audit_log", "category"):
        op.add_column("audit_log", sa.Column("category", sa.String(20), server_default="account", nullable=False))
        op.create_index("ix_audit_user_category", "audit_log", ["user_id", "category"])

    # ── SiteNotification table ────────────────────────────────────────
    if not _table_exists("site_notifications"):
        op.create_table(
            "site_notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("is_read", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_site_notif_user_unread", "site_notifications", ["user_id", "is_read"])


def downgrade():
    op.drop_table("site_notifications")
    op.drop_index("ix_audit_user_category", "audit_log")
    op.drop_column("audit_log", "category")
    op.drop_column("users", "oferta_advance_days")
    op.drop_column("users", "notif_timezone")
    op.drop_column("users", "notif_time")
    op.drop_column("users", "theme")
