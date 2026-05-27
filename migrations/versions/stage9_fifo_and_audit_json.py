"""Add Transaction.nkd + portfolio_id for FIFO; AuditLog.details Text -> JSON."""

from alembic import op
import sqlalchemy as sa

revision = "stage9_fifo_and_audit_json"
down_revision = "stage8_tx_type"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("nkd", sa.Numeric(10, 4), nullable=True))
        batch_op.add_column(
            sa.Column(
                "portfolio_id",
                sa.Integer,
                sa.ForeignKey("bond_portfolio.id"),
                nullable=True,
            )
        )

    # Clean up non-JSON data in audit_log.details before altering column type to JSON
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Create temporary helper function to check if string is valid JSON
        op.execute("""
            CREATE OR REPLACE FUNCTION pg_temp.is_valid_json(p_json text) RETURNS boolean AS $$
            BEGIN
                PERFORM p_json::json;
                RETURN TRUE;
            EXCEPTION WHEN OTHERS THEN
                RETURN FALSE;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
        """)

        # Update invalid JSON strings to valid JSON strings using to_json
        op.execute("""
            UPDATE audit_log 
            SET details = to_json(details)::text 
            WHERE details IS NOT NULL AND NOT pg_temp.is_valid_json(details);
        """)

        op.execute("DROP FUNCTION IF EXISTS pg_temp.is_valid_json(text);")

    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.alter_column(
            "details",
            existing_type=sa.Text(),
            type_=sa.JSON(),
            existing_nullable=True,
            postgresql_using="details::json",
        )


def downgrade():
    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.alter_column(
            "details",
            existing_type=sa.JSON(),
            type_=sa.Text(),
            existing_nullable=True,
        )

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("portfolio_id")
        batch_op.drop_column("nkd")
