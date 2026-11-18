from urllib.parse import quote

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field
from radar_common.source_http import SourceError, SourceHTTP

from services.catalog.normalization import normalized_name, normalized_version, parse_requirement


class ProjectInfo(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=100000)
    license: str | None = None
    license_expression: str | None = None
    requires_python: str | None = Field(default=None, max_length=200)
    requires_dist: list[str] | None = Field(default=None, max_length=2000)
    project_urls: dict[str, str] | None = None
    home_page: str | None = None
    yanked: bool = False


class Project(BaseModel):
    info: ProjectInfo
    releases: dict[str, list[dict]] | None = None


def stable_version(releases: dict[str, list[dict]]) -> str:
    choices = []
    for name, files in releases.items():
        try:
            version = Version(name)
        except InvalidVersion:
            continue
        if not version.is_prerelease and any(not file.get("yanked", False) for file in files):
            choices.append((version, name))
    if not choices:
        raise SourceError("NO_STABLE_RELEASE")
    return max(choices)[1]


def fetch(
    http: SourceHTTP, name: str, version: str | None, *, stable_only: bool = False
) -> tuple[ProjectInfo, ProjectInfo]:
    name = normalized_name(name)
    document = Project.model_validate(http.request("/pypi/" + name + "/json"))
    project = document.info
    if normalized_name(project.name) != name:
        raise SourceError("IDENTITY_MISMATCH")
    release = project
    if stable_only and not version:
        if document.releases is None:
            raise SourceError("MISSING_RELEASE_INDEX")
        version = stable_version(document.releases)
    if version and normalized_version(version) != normalized_version(project.version):
        release = Project.model_validate(
            http.request("/pypi/" + name + "/" + quote(version, safe="") + "/json")
        ).info
    if normalized_name(release.name) != name or (
        version and normalized_version(version) != normalized_version(release.version)
    ):
        raise SourceError("IDENTITY_MISMATCH")
    normalized_version(release.version)
    for requirement in release.requires_dist or []:
        parse_requirement(requirement)
    return project, release
