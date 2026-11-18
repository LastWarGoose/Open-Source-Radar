from pathlib import Path

from services.catalog.app import schema as catalog
from services.repositories.app import schema as repositories
from services.security.app import schema as security
from services.workspace.app import schema as workspace

destination = Path(__file__).resolve().parents[1] / "packages" / "graphql"
destination.mkdir(parents=True, exist_ok=True)
for name, schema in (
    ("catalog", catalog),
    ("repositories", repositories),
    ("security", security),
    ("workspace", workspace),
):
    (destination / f"{name}.graphql").write_text(schema.as_str() + "\n", encoding="utf-8")
    print(f"Exported {name}")
