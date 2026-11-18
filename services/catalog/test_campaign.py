import httpx
import pytest
from radar_common.import_queue import source_budget
from radar_common.source_http import SourceError, SourceHTTP

from scripts.select_stage5 import select_names
from services.catalog.source import fetch, stable_version


def test_sample_is_normalized_deduplicated_and_order_independent() -> None:
    data = [{"name": "A_B"}, {"name": "a-b"}, {"name": "other"}, {"name": "bad/thing"}]
    selected = select_names(data, 100)
    assert set(selected) == {"a-b", "other"}
    assert selected == select_names(list(reversed(data)), 100)
    assert select_names(data, 1) == selected[:1]


def test_stable_release_policy_excludes_yanked_prerelease_and_empty_files() -> None:
    assert (
        stable_version(
            {
                "9.0": [],
                "8.0": [{"yanked": True}],
                "3.0rc1": [{}],
                "2.0": [{}],
                "1.9": [{}],
                "legacy-invalid": [{}],
            }
        )
        == "2.0"
    )
    with pytest.raises(SourceError, match="NO_STABLE_RELEASE"):
        stable_version({"1.0rc1": [{}], "1.0": [{"yanked": True}]})


def test_stable_policy_fetches_the_selected_versions_requirements() -> None:
    paths = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        historical = "/1.0/" in request.url.path
        return httpx.Response(
            200,
            json={
                "info": {
                    "name": "example",
                    "version": "1.0" if historical else "2.0rc1",
                    "requires_dist": ["stable-dependency>=1"]
                    if historical
                    else ["future-dependency"],
                },
                "releases": {"1.0": [{}], "2.0rc1": [{}]},
            },
        )

    http = SourceHTTP("pypi", transport=httpx.MockTransport(respond))
    try:
        project, release = fetch(http, "example", None, stable_only=True)
        assert project.version == "2.0rc1" and release.version == "1.0"
        assert release.requires_dist == ["stable-dependency>=1"]
        assert paths == ["/pypi/example/json", "/pypi/example/1.0/json"]
    finally:
        http.close()


def test_bulk_budget_is_explicit_and_cannot_remove_upper_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RADAR_PYPI_REQUESTS_PER_HOUR", raising=False)
    assert source_budget("pypi") == (120, 0.5)
    monkeypatch.setenv("RADAR_PYPI_REQUESTS_PER_HOUR", "6000")
    assert source_budget("pypi") == (6000, 0.5)
    monkeypatch.setenv("RADAR_PYPI_REQUESTS_PER_HOUR", "6001")
    with pytest.raises(ValueError, match="budget"):
        source_budget("pypi")
