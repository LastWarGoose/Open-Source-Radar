import json
import logging

import pytest
from fastapi.testclient import TestClient
from radar_common.telemetry import JsonFormatter, safe_id

from services.catalog.app import app


def test_admin_mutation_is_denied_before_database_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_ADMIN_TOKEN", "test-only-token")
    with TestClient(app) as client:
        response = client.post(
            "/graphql",
            json={
                "query": "mutation { requestProbeJob(requestKey: "
                '"00000000-0000-4000-8000-000000000001") { id } }',
            },
        )
        assert response.status_code == 200
        assert response.json()["errors"][0]["extensions"]["code"] == "FORBIDDEN"


def test_correlation_and_redaction() -> None:
    assert safe_id("known-request_123") == "known-request_123"
    assert "\n" not in safe_id("invalid\nheader")
    record = logging.LogRecord("third-party", logging.ERROR, "", 0, "secret-password", (), None)
    record.authorization = "secret-token"
    payload = JsonFormatter().format(record)
    assert "secret" not in payload
    assert json.loads(payload)["event"] == "runtime_log"
    with TestClient(app) as client:
        response = client.get("/health", headers={"x-request-id": "known-request_123"})
        assert response.headers["x-request-id"] == "known-request_123"
