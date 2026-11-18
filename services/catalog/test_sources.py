"""Source contracts: synthetic payloads, no live API calls."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError
from radar_common.source_http import SourceError, SourceHTTP

from services.catalog.source import fetch as pypi_fetch
from services.repositories.source import candidates
from services.repositories.source import fetch as github_fetch
from services.security.source import fetch as osv_fetch


@pytest.mark.parametrize(
    "status,code",
    [(401, "AUTH_REJECTED"), (403, "AUTH_REJECTED"), (404, "NOT_FOUND"), (422, "HTTP_422")],
)
def test_permanent_errors_are_not_retried(status: int, code: str) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status)

    client = SourceHTTP("github", transport=httpx.MockTransport(respond), sleep=lambda _: None)
    with pytest.raises(SourceError, match=code):
        client.request("/repos/a/b")
    client.close()
    assert len(calls) == 1


def test_transient_retry_budget_and_recovery() -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503 if len(calls) < 3 else 200, json={"ok": True})

    client = SourceHTTP("pypi", transport=httpx.MockTransport(respond), sleep=lambda _: None)
    assert client.request("/pypi/test/json") == {"ok": True}
    assert len(calls) == 3
    client.close()


def test_timeout_attempts_are_bounded_and_do_not_leak_url() -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("sensitive detail", request=request)

    client = SourceHTTP("github", transport=httpx.MockTransport(respond), sleep=lambda _: None)
    with pytest.raises(SourceError, match="^NETWORK$"):
        client.request("/repos/a/b")
    client.close()
    assert len(calls) == 3


@pytest.mark.parametrize("status", [403, 429])
def test_rate_limit_defers_and_respects_reset(status: int) -> None:
    calls: list[httpx.Request] = []
    delays: list[float] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            status,
            headers={
                "Retry-After": "120",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(datetime.now(UTC).timestamp() + 180),
            },
        )

    client = SourceHTTP("github", transport=httpx.MockTransport(respond), block=delays.append)
    with pytest.raises(SourceError) as error:
        client.request("/repos/a/b")
    assert error.value.retry_after and error.value.retry_after >= 180
    assert len(calls) == len(delays) == 1
    client.close()


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/private", "https://evil.example/x", "https://api.github.com@evil.example/x"],
)
def test_redirect_does_not_forward_token_to_other_host(url: str) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(302, headers={"Location": url})

    client = SourceHTTP("github", token="synthetic-token", transport=httpx.MockTransport(respond))
    with pytest.raises(SourceError, match="UNSAFE_REDIRECT"):
        client.request("/repos/a/b")
    assert len(calls) == 1
    client.close()


def test_invalid_json() -> None:
    client = SourceHTTP(
        "pypi",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content="not-json")),
    )
    with pytest.raises(SourceError, match="INVALID_JSON"):
        client.request("/pypi/test/json")
    client.close()


def test_secondary_rate_limit_without_headers() -> None:
    client = SourceHTTP(
        "github",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"message": "secondary rate limit exceeded"})
        ),
    )
    with pytest.raises(SourceError, match="RATE_LIMIT") as error:
        client.request("/repos/a/b")
    assert error.value.retry_after == 60
    client.close()


def test_pypi_historical_requirements_use_release_endpoint() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        historic = "/1.0/" in request.url.path
        return httpx.Response(
            200,
            json={
                "info": {
                    "name": "Foo_Bar",
                    "version": "1.0" if historic else "2.0",
                    "requires_dist": ['Dep[ssl]>=1; python_version < "3.13"']
                    if historic
                    else ["dep>=2"],
                }
            },
        )

    client = SourceHTTP("pypi", transport=httpx.MockTransport(respond))
    project, release = pypi_fetch(client, "foo-bar", "1.0")
    assert project.version == "2.0" and release.version == "1.0"
    assert release.requires_dist == ['Dep[ssl]>=1; python_version < "3.13"']
    client.close()


def test_pypi_identity_and_schema_validation() -> None:
    client = SourceHTTP(
        "pypi",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"info": {"name": "wrong", "version": "1"}})
        ),
    )
    with pytest.raises(SourceError, match="IDENTITY_MISMATCH"):
        pypi_fetch(client, "expected", None)
    client.close()
    client = SourceHTTP(
        "pypi",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"info": {}})),
    )
    with pytest.raises(ValidationError):
        pypi_fetch(client, "expected", None)
    client.close()


def test_github_links_are_not_guessed() -> None:
    assert candidates(
        [
            "https://github.com/A/B.git",
            "https://github.com/a/b",
            "https://github.com/a/b/issues",
            "http://localhost/x",
            "https://github.com.evil/a/b",
        ]
    ) == ["a/b"]
    client = SourceHTTP(
        "github",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "id": 1,
                    "full_name": "a/b",
                    "html_url": "https://evil.example/a/b",
                    "private": False,
                    "stargazers_count": 1,
                },
            )
        ),
    )
    with pytest.raises(ValueError):
        github_fetch(client, "a/b")
    client.close()


def test_osv_pagination_details_and_withdrawal() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            query = json.loads(request.content)["queries"][0]
            assert query["package"] == {"name": "example", "ecosystem": "PyPI"}
            assert query["version"] == "1.0"
            if "page_token" not in query:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "vulns": [{"id": "TEST-A", "modified": "2026-01-01T00:00:00Z"}],
                                "next_page_token": "page2",
                            }
                        ]
                    },
                )
            assert query["page_token"] == "page2"
            return httpx.Response(
                200,
                json={
                    "results": [{"vulns": [{"id": "TEST-B", "modified": "2026-01-01T00:00:00Z"}]}]
                },
            )
        identity = request.url.path.split("/")[-1]
        return httpx.Response(
            200,
            json={
                "id": identity,
                "modified": "2026-01-01T00:00:00Z",
                "withdrawn": "2026-01-02T00:00:00Z" if identity == "TEST-B" else None,
            },
        )

    client = SourceHTTP("osv", transport=httpx.MockTransport(respond))
    assert [row.id for row in osv_fetch(client, "example", "1.0")] == ["TEST-A"]
    assert len(requests) == 4
    client.close()


def test_osv_empty_and_pagination_loop_are_distinct() -> None:
    client = SourceHTTP(
        "osv",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": [{}]})),
    )
    assert osv_fetch(client, "example", "1") == []
    client.close()
    client = SourceHTTP(
        "osv",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"results": [{"next_page_token": "same"}]})
        ),
    )
    with pytest.raises(SourceError, match="PAGINATION_LOOP"):
        osv_fetch(client, "example", "1")
    client.close()
