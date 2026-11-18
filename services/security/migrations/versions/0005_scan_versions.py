from alembic import op

revision = "security_0005"
down_revision = "security_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE version_scans ADD package_name VARCHAR(200), ADD version VARCHAR(200)")
    op.execute("ALTER TABLE scan_findings ADD fixed_version VARCHAR(200)")
    op.execute("""
        UPDATE version_scans s SET package_name = w.name, version = w.version
        FROM (
            SELECT DISTINCT ON (payload->>'release') payload->>'release' AS release,
                   payload->>'name' AS name, payload->>'version' AS version
            FROM source_work
            WHERE payload ?& ARRAY['release','name','version']
            ORDER BY payload->>'release', created_at DESC, id
        ) w WHERE s.release_id = w.release AND s.source = 'OSV'
    """)
    op.create_index("ix_version_scans_package_name", "version_scans", ["package_name"])


def downgrade() -> None:
    op.drop_index("ix_version_scans_package_name", table_name="version_scans")
    op.drop_column("scan_findings", "fixed_version")
    op.drop_column("version_scans", "version")
    op.drop_column("version_scans", "package_name")
