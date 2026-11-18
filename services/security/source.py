from datetime import datetime
from urllib.parse import quote

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field
from radar_common.source_http import SourceError, SourceHTTP


class Hit(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    modified: datetime


class BatchResult(BaseModel):
    vulns: list[Hit] = Field(default_factory=list, max_length=1000)
    next_page_token: str | None = None


class Batch(BaseModel):
    results: list[BatchResult] = Field(min_length=1, max_length=1)


class AffectedPackage(BaseModel):
    ecosystem: str
    name: str


class AffectedRange(BaseModel):
    type: str
    events: list[dict[str, str]]


class Affected(BaseModel):
    package: AffectedPackage | None = None
    ranges: list[AffectedRange] = Field(default_factory=list)
    versions: list[str] = Field(default_factory=list)


class Advisory(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=99)
    summary: str = Field(default="", max_length=100000)
    details: str = Field(default="", max_length=2000000)
    modified: datetime
    withdrawn: datetime | None = None
    affected: list[Affected] = Field(default_factory=list)

    def fix_for(self, name: str, version: str) -> str | None:
        """First explicit fixed boundary that closes an interval affecting this PyPI release."""
        checked = Version(version)
        intervals: list[tuple[Version | None, Version | None, str]] = []
        listed: set[Version] = set()
        try:
            for entry in self.affected:
                pkg = entry.package
                if not pkg or pkg.ecosystem != "PyPI" or canonicalize_name(pkg.name) != name:
                    continue
                listed.update(Version(v) for v in entry.versions)
                for span in entry.ranges:
                    if span.type != "ECOSYSTEM":
                        continue
                    events = []
                    for event in span.events:
                        if len(event) != 1:
                            return None
                        kind, value = next(iter(event.items()))
                        if kind not in ("introduced", "fixed", "last_affected"):
                            return None
                        boundary = None if kind == "introduced" and value == "0" else Version(value)
                        events.append((boundary, kind))
                    events.sort(key=lambda e: (e[0] is not None, e[0]))
                    start = None
                    opened = False
                    for boundary, kind in events:
                        if kind == "introduced" and not opened:
                            start, opened = boundary, True
                        elif kind != "introduced" and opened:
                            intervals.append((start, boundary, kind))
                            opened = False
                        else:
                            return None
                    if opened:
                        intervals.append((start, None, "open"))
        except InvalidVersion:
            return None

        def contains(start: Version | None, end: Version | None, kind: str, v: Version) -> bool:
            return (start is None or start <= v) and (
                end is None or v < end or (kind == "last_affected" and v == end)
            )

        candidates = sorted(
            {
                end
                for start, end, kind in intervals
                if end is not None and kind == "fixed" and contains(start, end, kind, checked)
            }
        )
        for candidate in candidates:
            if candidate not in listed and not any(
                contains(*span, candidate) for span in intervals
            ):
                value = str(candidate)
                return value if len(value) <= 200 else None
        return None


def fetch(http: SourceHTTP, name: str, version: str) -> list[Advisory]:
    ids: set[str] = set()
    tokens: set[str] = set()
    query: dict = {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
    for _ in range(10):
        result = Batch.model_validate(http.request("/v1/querybatch", {"queries": [query]})).results[
            0
        ]
        ids.update(hit.id for hit in result.vulns)
        if len(ids) > 50:
            raise SourceError("ADVISORY_BUDGET")
        token = result.next_page_token
        if not token:
            break
        if token in tokens:
            raise SourceError("PAGINATION_LOOP")
        tokens.add(token)
        query["page_token"] = token
    else:
        raise SourceError("PAGE_BUDGET")
    records = []
    for identity in sorted(ids):
        advisory = Advisory.model_validate(http.request("/v1/vulns/" + quote(identity, safe="")))
        if advisory.id != identity:
            raise SourceError("IDENTITY_MISMATCH")
        if not advisory.withdrawn:
            records.append(advisory)
    return records
