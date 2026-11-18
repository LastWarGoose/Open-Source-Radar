from alembic import op
from sqlalchemy import text

from services.catalog.normalization import license_key

revision = "catalog_0006"
down_revision = "catalog_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE packages ADD COLUMN license_key VARCHAR(200)")
    db = op.get_bind()
    # Classify each distinct declaration once, including packages imported before this revision.
    declared = db.scalars(text("SELECT DISTINCT license FROM packages WHERE license IS NOT NULL"))
    values = [{"raw": raw, "key": key} for raw in declared if (key := license_key(raw))]
    if values:
        db.execute(text("UPDATE packages SET license_key = :key WHERE license = :raw"), values)
    op.create_index("packages_source_license_key", "packages", ["source", "license_key"])


def downgrade() -> None:
    op.drop_index("packages_source_license_key", table_name="packages")
    op.drop_column("packages", "license_key")
