from uuid import UUID

import pytest
from graphql import GraphQLError
from packaging.version import Version
from radar_common.graphql import decode_cursor, encode_cursor, page_size, scope_key

from services.catalog.normalization import (
    license_key,
    normalized_name,
    normalized_version,
    parse_requirement,
    release_id,
)
from services.repositories.normalization import github_name
from services.workspace.access import DEV_ACTORS, actor_for_token, dev_token


@pytest.mark.parametrize("name", ["Foo_Bar", "foo.bar", "FOO---BAR"])
def test_pypi_names(name: str) -> None:
    assert normalized_name(name) == "foo-bar"


@pytest.mark.parametrize("name", ["-invalid", "bad/name", "bad name", "", "a" * 201])
def test_invalid_names(name: str) -> None:
    with pytest.raises(ValueError):
        normalized_name(name)


def test_versions_and_requirements() -> None:
    assert normalized_version("v1.0.0") == normalized_version("1.0")
    assert release_id("Foo_Bar", "1.0.0") == release_id("foo.bar", "1")
    assert sorted(["1.10", "1.9", "2.0rc1", "2.0"], key=Version) == ["1.9", "1.10", "2.0rc1", "2.0"]
    parsed = parse_requirement('Foo_Bar[Fast,ssl]>=1.0,<2; python_version < "3.13"')
    assert parsed.name == "foo-bar" and parsed.extras == ["fast", "ssl"]
    assert parsed.specifier == "<2,>=1.0" and parsed.marker == 'python_version < "3.13"'
    direct = parse_requirement("foo @ https://example.com/foo.whl")
    assert direct.url == "https://example.com/foo.whl"
    with pytest.raises(ValueError):
        parse_requirement("foo >>> 1")
    with pytest.raises(ValueError):
        normalized_version("not-a-version")


def test_license_filter_keys_preserve_declared_choices() -> None:
    assert license_key("MIT License") == license_key("mit") == "MIT"
    assert license_key("mit OR Apache-2.0") == "MIT OR Apache-2.0"
    assert license_key("BSD License") == "BSD"
    assert license_key("See the repository for licensing details") is None


def test_cursor_scope_limits_and_malformed_input() -> None:
    scope = scope_key("catalog", "filter", "NAME_ASC")
    cursor = encode_cursor(scope, "same", "unique-id")
    assert decode_cursor(cursor, scope, 2) == ["same", "unique-id"]
    for bad in ("!", "e30=", "x" * 2049):
        with pytest.raises(GraphQLError):
            decode_cursor(bad, scope)
    with pytest.raises(GraphQLError):
        decode_cursor(cursor, scope_key("other"), 2)
    for size in (0, -1, 101):
        with pytest.raises(GraphQLError):
            page_size(size)
    assert page_size(100) == 100


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/foo/bar",
        "https://github.com.evil/foo/bar",
        "https://user@github.com/foo/bar",
        "https://github.com:443/foo/bar",
        "https://127.0.0.1/foo/bar",
        "https://github.com/foo/bar/issues",
        "https://github.com/foo/bar?token=secret",
        "https://github.com/foo/..",
    ],
)
def test_repository_allowlist(url: str) -> None:
    with pytest.raises(ValueError):
        github_name(url)


def test_repository_normalization() -> None:
    assert github_name("https://github.com/Owner/Repo.git/") == "owner/repo"


def test_workspace_identity_is_credential_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_ADMIN_TOKEN", "unit-test-only")
    for actor in DEV_ACTORS:
        assert actor_for_token(dev_token("unit-test-only", actor)) == actor
    for forged in (
        "",
        str(DEV_ACTORS[0]),
        dev_token("wrong-secret", DEV_ACTORS[0]),
        str(UUID(int=0)),
    ):
        with pytest.raises(GraphQLError):
            actor_for_token(forged)
