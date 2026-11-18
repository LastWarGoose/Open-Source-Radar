from datetime import datetime
from urllib.parse import quote

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


class Advisory(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=99)
    summary: str = Field(default="", max_length=100000)
    details: str = Field(default="", max_length=2000000)
    modified: datetime
    withdrawn: datetime | None = None
    affected: list[dict] = Field(default_factory=list)


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
