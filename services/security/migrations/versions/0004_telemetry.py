from alembic import op

revision = "security_0004"
down_revision = "security_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE source_work ADD COLUMN traceparent VARCHAR(55)")


def downgrade() -> None:
    op.drop_column("source_work", "traceparent")
