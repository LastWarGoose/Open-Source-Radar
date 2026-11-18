"""Durable source work and freshness, local to catalog."""

from alembic import op

revision = "catalog_0003"
down_revision = "catalog_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE source_work (
            id UUID PRIMARY KEY, parent_id UUID, payload JSONB NOT NULL,
            checkpoint JSONB NOT NULL DEFAULT '{}', status VARCHAR(16) NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0, error_code VARCHAR(64),
            correlation_id VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            next_at TIMESTAMPTZ NOT NULL DEFAULT now(), published_at TIMESTAMPTZ,
            CHECK (status IN ('queued', 'succeeded', 'failed')),
            CHECK (attempts >= 0)
        )
    """)
    op.execute("CREATE INDEX ix_source_work_parent_id ON source_work(parent_id)")
    op.execute("CREATE INDEX source_work_due ON source_work(next_at) WHERE status='queued'")
    op.execute("""
        CREATE TABLE source_state (
            key VARCHAR(250) PRIMARY KEY, status VARCHAR(16) NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL, checked_at TIMESTAMPTZ NOT NULL,
            last_success_at TIMESTAMPTZ, error_code VARCHAR(64),
            CHECK (status IN ('UNKNOWN','SUCCESS','STALE','FAILED'))
        )
    """)
    op.execute("""
        CREATE TABLE source_quota (
            source VARCHAR(16) PRIMARY KEY, window_at TIMESTAMPTZ NOT NULL,
            used INTEGER NOT NULL, next_at TIMESTAMPTZ NOT NULL
        )
    """)


def downgrade() -> None:
    op.drop_table("source_quota")
    op.drop_table("source_state")
    op.drop_table("source_work")
