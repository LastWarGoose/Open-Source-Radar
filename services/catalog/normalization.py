from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, canonicalize_version
from packaging.version import Version


def normalized_name(value: str) -> str:
    if len(value) > 200:
        raise ValueError("Package name too long")
    return str(canonicalize_name(value, validate=True))


def package_id(name: str) -> str:
    return "pypi:" + normalized_name(name)


def release_id(name: str, version: str) -> UUID:
    return uuid5(NAMESPACE_URL, package_id(name) + "/" + normalized_version(version))


def normalized_version(value: str) -> str:
    if len(value) > 200:
        raise ValueError("Version too long")
    return canonicalize_version(Version(value))


@dataclass(frozen=True)
class ParsedRequirement:
    raw: str
    name: str
    specifier: str
    extras: list[str]
    marker: str | None
    url: str | None


def parse_requirement(value: str) -> ParsedRequirement:
    if len(value) > 4096:
        raise ValueError("Requirement too long")
    parsed = Requirement(value)
    if len(parsed.extras) > 100:
        raise ValueError("Too many extras")
    return ParsedRequirement(
        raw=value,
        name=normalized_name(parsed.name),
        specifier=str(parsed.specifier),
        extras=sorted(str(canonicalize_name(extra)) for extra in parsed.extras),
        marker=str(parsed.marker) if parsed.marker else None,
        url=parsed.url,
    )
