"""security domain schema, frozen at stage 2."""

from alembic import op

revision = "security_0002"
down_revision = "security_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE version_scans (
	id UUID NOT NULL, 
	release_id VARCHAR(36) NOT NULL, 
    status VARCHAR(16) NOT NULL,
    source VARCHAR(32) NOT NULL,
	checked_at TIMESTAMP WITH TIME ZONE, 
	last_success_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(64), 
	PRIMARY KEY (id), 
	CONSTRAINT scan_status CHECK (status IN ('UNKNOWN','SUCCESS','STALE','FAILED')), 
    CONSTRAINT success_checked CHECK (status <> 'SUCCESS' OR
        (checked_at IS NOT NULL AND last_success_at IS NOT NULL)),
	UNIQUE (release_id)
)
""")
    op.execute("""
CREATE TABLE vulnerabilities (
	id VARCHAR(200) NOT NULL, 
	summary TEXT NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)
""")
    op.execute("""
CREATE TABLE scan_findings (
	scan_id UUID NOT NULL, 
	vulnerability_id VARCHAR(200) NOT NULL, 
	PRIMARY KEY (scan_id, vulnerability_id), 
	FOREIGN KEY(scan_id) REFERENCES version_scans (id) ON DELETE CASCADE, 
	FOREIGN KEY(vulnerability_id) REFERENCES vulnerabilities (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE vulnerability_aliases (
	alias VARCHAR(200) NOT NULL, 
	vulnerability_id VARCHAR(200) NOT NULL, 
	PRIMARY KEY (alias), 
	FOREIGN KEY(vulnerability_id) REFERENCES vulnerabilities (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE INDEX ix_vulnerability_aliases_vulnerability_id ON vulnerability_aliases (vulnerability_id)
""")


def downgrade() -> None:
    op.drop_table("vulnerability_aliases")
    op.drop_table("scan_findings")
    op.drop_table("vulnerabilities")
    op.drop_table("version_scans")
