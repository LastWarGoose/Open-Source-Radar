"""Local accounts, revocable sessions, rate limits and follows."""

from alembic import op

revision = "workspace_0003"
down_revision = "workspace_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE accounts (
 actor_id UUID PRIMARY KEY REFERENCES actors(id),
 username VARCHAR(40) NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, recovery_hash VARCHAR(64) NOT NULL,
 role VARCHAR(10) NOT NULL CHECK (role IN ('user','admin'))
);
CREATE TABLE sessions (
 token_hash VARCHAR(64) PRIMARY KEY,
 actor_id UUID NOT NULL REFERENCES accounts(actor_id),
 expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_sessions_actor_id ON sessions(actor_id);
CREATE INDEX ix_sessions_expires_at ON sessions(expires_at);
CREATE TABLE auth_attempts (
 key VARCHAR(64) PRIMARY KEY, attempts INTEGER NOT NULL, reset_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE follows (
 owner_id UUID NOT NULL REFERENCES actors(id), package_id VARCHAR(220) NOT NULL,
 version VARCHAR(200), observed_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(owner_id,package_id)
);
""")


def downgrade() -> None:
    for table in ("follows", "auth_attempts", "sessions", "accounts"):
        op.drop_table(table)
