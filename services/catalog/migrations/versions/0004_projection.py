"""Catalog-owned GitHub projection and reconciliation cursor."""

from alembic import op

revision = "catalog_0004"
down_revision = "catalog_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE packages
        ADD COLUMN github_stars INTEGER CHECK (github_stars >= 0),
        ADD COLUMN github_checked_at TIMESTAMPTZ,
        ADD COLUMN github_projected_at TIMESTAMPTZ,
        ADD COLUMN github_status VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN'
    """)
    op.execute("CREATE INDEX packages_stars ON packages((coalesce(github_stars,-1)) DESC,id)")
    op.execute("""
        CREATE TABLE projection_sync (
            id INTEGER PRIMARY KEY CHECK (id=1),
            after_id VARCHAR(220),
            checked_at TIMESTAMPTZ
        )
    """)
    op.execute("INSERT INTO projection_sync(id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("projection_sync")
    op.execute("DROP INDEX packages_stars")
    for column in ("github_status", "github_projected_at", "github_checked_at", "github_stars"):
        op.drop_column("packages", column)
