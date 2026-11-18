from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.security.models import AliasRow, VulnerabilityRow


def save_advisory(
    session: Session,
    identity: str,
    aliases: list[str],
    summary: str,
    fetched_at: datetime,
    *,
    source: str = "OSV",
) -> str:
    names = sorted(set([identity, *aliases]))
    if len(names) > 100 or any(not name or len(name) > 200 for name in names):
        raise ValueError("Invalid advisory identifiers")
    # Serialize overlapping alias sets, including first insertion, in deterministic order.
    for name in names:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": name}
        )
    canonical_ids = set(
        session.scalars(select(AliasRow.vulnerability_id).where(AliasRow.alias.in_(names)))
    )
    if len(canonical_ids) > 1:
        raise ValueError("Alias groups need explicit reconciliation")
    canonical = next(iter(canonical_ids), identity)
    values = dict(id=canonical, summary=summary, source=source, fetched_at=fetched_at)
    session.execute(
        insert(VulnerabilityRow)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[VulnerabilityRow.id],
            set_={key: value for key, value in values.items() if key != "id"},
            where=VulnerabilityRow.fetched_at <= fetched_at,
        )
    )
    for name in names:
        session.execute(
            insert(AliasRow).values(alias=name, vulnerability_id=canonical).on_conflict_do_nothing()
        )
    return canonical
