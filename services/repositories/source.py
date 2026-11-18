from pydantic import BaseModel, Field
from radar_common.source_http import SourceError, SourceHTTP

from services.repositories.normalization import github_name


class RepositoryData(BaseModel):
    id: int = Field(gt=0)
    full_name: str = Field(max_length=220)
    description: str | None = None
    html_url: str = Field(max_length=300)
    stargazers_count: int = Field(ge=0)
    private: bool


def candidates(urls: list[str]) -> list[str]:
    found: set[str] = set()
    for url in urls:
        try:
            found.add(github_name(url))
        except ValueError:
            continue
    if len(found) > 5:
        raise SourceError("TOO_MANY_REPOSITORIES")
    return sorted(found)


def fetch(http: SourceHTTP, name: str) -> RepositoryData:
    result = RepositoryData.model_validate(http.request("/repos/" + name))
    if result.private or github_name(result.html_url) != result.full_name.lower():
        raise SourceError("IDENTITY_MISMATCH")
    # API may canonicalize a renamed repository via a same-host redirect.
    return result
