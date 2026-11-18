"""workspace domain schema, frozen at stage 2."""

from alembic import op

revision = "workspace_0002"
down_revision = "workspace_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE actors (
	id UUID NOT NULL, 
	PRIMARY KEY (id)
)
""")
    op.execute("""
CREATE TABLE collections (
	id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner_id, name), 
	FOREIGN KEY(owner_id) REFERENCES actors (id)
)
""")
    op.execute("""
CREATE INDEX ix_collections_owner_id ON collections (owner_id)
""")
    op.execute("""
CREATE TABLE notifications (
	id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	message TEXT NOT NULL, 
	package_id VARCHAR(220), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	read_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES actors (id)
)
""")
    op.execute("""
CREATE INDEX ix_notifications_owner_id ON notifications (owner_id)
""")
    op.execute("""
CREATE TABLE collection_items (
	collection_id UUID NOT NULL, 
	package_id VARCHAR(220) NOT NULL, 
	PRIMARY KEY (collection_id, package_id), 
	FOREIGN KEY(collection_id) REFERENCES collections (id) ON DELETE CASCADE
)
""")


def downgrade() -> None:
    op.drop_table("collection_items")
    op.drop_table("notifications")
    op.drop_table("collections")
    op.drop_table("actors")
