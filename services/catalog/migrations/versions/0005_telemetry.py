from alembic import op

revision = "catalog_0005"
down_revision = "catalog_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE source_work ADD COLUMN traceparent VARCHAR(55)")
    op.execute("ALTER TABLE jobs ADD COLUMN traceparent VARCHAR(55)")
    op.execute("""CREATE TABLE follow_refresh (
        id integer PRIMARY KEY CHECK (id=1), after_id varchar(220) NOT NULL DEFAULT '',
        cycle_at timestamptz NOT NULL DEFAULT now(), next_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("INSERT INTO follow_refresh(id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("follow_refresh")
    op.drop_column("jobs", "traceparent")
    op.drop_column("source_work", "traceparent")
