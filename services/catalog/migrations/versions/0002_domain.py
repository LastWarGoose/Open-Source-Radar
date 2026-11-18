"""catalog domain schema, frozen at stage 2."""

from alembic import op

revision = "catalog_0002"
down_revision = "catalog_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE EXTENSION IF NOT EXISTS pg_trgm
""")
    op.execute("""
CREATE TABLE import_jobs (
	id UUID NOT NULL, 
	request_key UUID NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	processed INTEGER NOT NULL, 
	checkpoint JSONB NOT NULL, 
	error_code VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT import_status CHECK (status IN ('queued','running','succeeded','failed')), 
	CONSTRAINT import_source_progress CHECK (source = 'PYPI' AND processed >= 0), 
	UNIQUE (request_key)
)
""")
    op.execute("""
CREATE TABLE packages (
	id VARCHAR(220) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	display_name VARCHAR(200) NOT NULL, 
	summary TEXT NOT NULL, 
	license VARCHAR(200), 
	requires_python VARCHAR(200), 
	source VARCHAR(32) NOT NULL, 
	source_id VARCHAR(200) NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
    CONSTRAINT normalized_package_name
        CHECK (name = lower(name) AND name ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
	UNIQUE (name)
)
""")
    op.execute("""
CREATE TABLE releases (
	id UUID NOT NULL, 
	package_id VARCHAR(220) NOT NULL, 
	version VARCHAR(200) NOT NULL, 
	normalized_version VARCHAR(200) NOT NULL, 
	version_rank INTEGER NOT NULL, 
	is_prerelease BOOLEAN NOT NULL, 
	yanked BOOLEAN NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (package_id, normalized_version), 
	FOREIGN KEY(package_id) REFERENCES packages (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE INDEX ix_releases_package_id ON releases (package_id)
""")
    op.execute("""
CREATE TABLE dependency_requirements (
	id UUID NOT NULL, 
	release_id UUID NOT NULL, 
	raw VARCHAR(4096) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	specifier TEXT NOT NULL, 
	extras VARCHAR(200)[] NOT NULL, 
	marker TEXT, 
	url TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (release_id, raw), 
	FOREIGN KEY(release_id) REFERENCES releases (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE INDEX ix_dependency_requirements_release_id ON dependency_requirements (release_id)
""")
    op.execute("""
CREATE INDEX packages_search ON packages USING gin(to_tsvector('simple', name || ' ' || summary))
""")
    op.execute("""
CREATE INDEX packages_name_trgm ON packages USING gin(name gin_trgm_ops)
""")
    op.execute("""
CREATE INDEX packages_updated ON packages(updated_at DESC, id)
""")
    op.execute("""
CREATE INDEX releases_rank ON releases(package_id, version_rank DESC, id)
""")


def downgrade() -> None:
    op.drop_table("dependency_requirements")
    op.drop_table("releases")
    op.drop_table("packages")
    op.drop_table("import_jobs")
