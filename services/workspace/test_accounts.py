import pytest
from fastapi.testclient import TestClient
from graphql import GraphQLError
from radar_common.session import require_origin
from starlette.requests import Request

from services.workspace.accounts import PASSWORD, digest, password_value, principal, username_value
from services.workspace.app import app


def test_credentials_validation_and_argon2() -> None:
    assert username_value("  User_123 ") == "user_123"
    for value in ("ab", "кириллица", "has space", "x" * 41):
        with pytest.raises(GraphQLError):
            username_value(value)
    for value in ("short", "x" * 129):
        with pytest.raises(GraphQLError):
            password_value(value)
    hashed = PASSWORD.hash("long-enough-test-password")
    assert hashed.startswith("$argon2id$")
    assert PASSWORD.verify("long-enough-test-password", hashed)
    assert not PASSWORD.verify("another-long-password", hashed)
    assert len(digest("opaque-token")) == 64
    assert principal("") is None
    assert principal("x" * 129) is None


@pytest.mark.parametrize("origin", [None, "null", "https://evil.invalid"])
def test_origin_required(origin: str | None) -> None:
    headers = [(b"origin", origin.encode())] if origin else []
    with pytest.raises(GraphQLError):
        require_origin(Request({"type": "http", "headers": headers}))


def test_authentication_errors_do_not_log_query_secrets(caplog: pytest.LogCaptureFixture) -> None:
    sensitive = "literal-password-never-log-123"
    with TestClient(app) as client:
        response = client.post(
            "/graphql",
            json={
                "query": 'mutation { login(username:"secret-user", password:"'
                + sensitive
                + '") { id } }'
            },
            headers={"origin": "https://evil.invalid"},
        )
    assert response.json()["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    assert sensitive not in caplog.text
    assert "secret-user" not in caplog.text
