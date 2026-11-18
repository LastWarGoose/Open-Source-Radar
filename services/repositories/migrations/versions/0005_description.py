from alembic import op
from sqlalchemy import Column, Text

revision = "repositories_0005"
down_revision = "repositories_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("repositories", Column("description", Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("repositories", "description")
