"""repositories domain schema, frozen at stage 2."""

from alembic import op

revision = "repositories_0002"
down_revision = "repositories_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE repositories (
	id VARCHAR(250) NOT NULL, 
	full_name VARCHAR(220) NOT NULL, 
	url VARCHAR(300) NOT NULL, 
	stars INTEGER NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	source_id VARCHAR(250) NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT nonnegative_stars CHECK (stars >= 0), 
	UNIQUE (full_name), 
	UNIQUE (url), 
	UNIQUE (source_id)
)
""")
    op.execute("""
CREATE TABLE package_repositories (
	package_id VARCHAR(220) NOT NULL, 
	repository_id VARCHAR(250) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (package_id, repository_id), 
	CONSTRAINT link_status CHECK (status IN ('UNVERIFIED','VERIFIED','INVALID')), 
	FOREIGN KEY(repository_id) REFERENCES repositories (id) ON DELETE CASCADE
)
""")


def downgrade() -> None:
    op.drop_table("package_repositories")
    op.drop_table("repositories")
