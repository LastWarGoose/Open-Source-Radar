"""Verify real stored traces, correlated logs, targets and the HTTP-200 error counter."""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def main() -> None:
    api, grafana = sys.argv[1:3]
    if urlsplit(api).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Probe credential is only sent to a local gateway")
    proxy = grafana.rstrip("/") + "/api/datasources/proxy/uid/"
    token = next(
        line.split("=", 1)[1]
        for line in Path(".env").read_text().splitlines()
        if line.startswith("DEV_ADMIN_TOKEN=")
    )
    with httpx.Client(timeout=10) as client:
        client.get(grafana + "/api/dashboards/uid/open-source-radar").raise_for_status()

        def prom(query: str) -> list:
            response = client.get(proxy + "prometheus/api/v1/query", params={"query": query})
            response.raise_for_status()
            return list(response.json()["data"]["result"])

        def failures() -> float:
            values = prom('sum(radar_graphql_errors_total{operation="AdminJobs"})')
            return float(values[0]["value"][1]) if values else 0

        before = failures()
        denied_trace = uuid4().hex
        denied = client.post(
            api,
            json={"query": "query AdminJobs {importJobs(first:1){nodes{id}}}"},
            headers={"traceparent": f"00-{denied_trace}-0123456789abcdef-01"},
        )
        assert denied.status_code == 200 and denied.json()["errors"]
        traces = {"denied": (denied_trace, {"gateway", "catalog"})}
        marker = "no-telemetry-value-" + uuid4().hex
        for name, query, variables, owners in [
            (
                "card",
                "query PublicPackage($id:ID!,$marker:String!){"
                "packages(first:1,search:$marker){nodes{id}} "
                "package(id:$id){name repositories(first:1)"
                "{nodes{repository{stars}}} releases(first:1){nodes{scan{status}}}}}",
                {"id": "pypi:fastapi"},
                {"catalog", "repositories", "security", "gateway"},
            ),
            (
                "probe",
                "mutation Probe($id:UUID!){requestProbeJob(requestKey:$id){id}}",
                {"id": str(uuid4())},
                {"gateway", "catalog", "catalog-dispatcher", "catalog-worker"},
            ),
        ]:
            ident = uuid4().hex
            result = client.post(
                api,
                json={"query": query, "variables": {**variables, "marker": marker}},
                headers={
                    "traceparent": f"00-{ident}-0123456789abcdef-01",
                    "x-dev-admin-token": token,
                },
            )
            assert result.headers.get("x-trace-id") == ident and not result.json().get("errors")
            traces[name] = (ident, owners)
        deadline = time.monotonic() + 75
        pending = set(traces)
        while pending or failures() <= before:
            if time.monotonic() > deadline:
                raise AssertionError(f"Missing telemetry: {pending}, error counter {failures()}")
            for name in list(pending):
                ident, owners = traces[name]
                trace = client.get(
                    proxy + "tempo/api/traces/" + ident, headers={"Accept": "application/json"}
                )
                if trace.status_code == 404:
                    continue
                trace.raise_for_status()
                assert marker not in trace.text and token not in trace.text
                if name == "denied":
                    failed = {
                        a["value"]["stringValue"]
                        for batch in trace.json()["batches"]
                        if any(
                            s.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR")
                            for group in batch["scopeSpans"]
                            for s in group["spans"]
                        )
                        for a in batch["resource"]["attributes"]
                        if a["key"] == "service.name"
                    }
                    if not owners <= failed:
                        continue
                services = {
                    a["value"]["stringValue"]
                    for batch in trace.json()["batches"]
                    for a in batch["resource"]["attributes"]
                    if a["key"] == "service.name"
                }
                logs = client.get(
                    proxy + "loki/loki/api/v1/query_range",
                    params={
                        "query": '{service_name=~".+"} | trace_id="' + ident + '"',
                        "limit": 20,
                    },
                )
                logs.raise_for_status()
                assert marker not in logs.text and token not in logs.text
                if owners <= services and logs.json()["data"]["result"]:
                    print(name, ident, sorted(services), flush=True)
                    pending.remove(name)
            time.sleep(1)
        up = prom('up{job=~"sources|gateway"}')
        assert len(up) == 4 and all(row["value"][1] == "1" for row in up)
        print(json.dumps({"scrape_targets": len(up), "http_200_error_counted": True}))


if __name__ == "__main__":
    main()
