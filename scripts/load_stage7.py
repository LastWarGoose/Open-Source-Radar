"""Run the authenticated 20-VU profile only against the isolated, restored Compose project."""

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from statistics import quantiles
from uuid import uuid4

import httpx
from websockets.sync.client import connect
from websockets.typing import Origin, Subprotocol

from scripts.cohort_evidence import read_cohort, save_cohort
from scripts.windows_awake import prevent_idle_sleep

PROJECT = "radar-stage7-check"
URL = "http://localhost:4400/graphql"
ORIGIN = "http://localhost:3300"
ROOT = Path(__file__).resolve().parents[1]


def sql(owner: str, statement: str) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            PROJECT,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            owner,
        ],
        input=statement,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def gql(client: httpx.Client, query: str, variables: dict) -> dict:
    response = client.post(URL, json={"query": query, "variables": variables})
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError("Load fixture GraphQL operation failed")
    return dict(data["data"])


def main() -> None:
    modes = sys.argv[1:] or ["warm", "baseline"]
    if any(mode not in {"warm", "baseline", "pilot", "smoke"} for mode in modes):
        raise ValueError("Unknown load profile")
    prefix = "radar7-" + uuid4().hex[:12] + "-"
    password = secrets.token_hex(20)
    identity = uuid4()
    destination = ROOT / ".runtime" / prefix.rstrip("-")
    destination.mkdir()
    evidence = ROOT / "docs/evidence/stage5"
    cohort = save_cohort(
        read_cohort(evidence).read_bytes(), destination, evidence / "cohorts", pin=True
    )
    with httpx.Client(headers={"Origin": ORIGIN}, timeout=15) as client:
        for i in range(1, 21):
            username = prefix + str(i)
            gql(
                client,
                "mutation Register($u:String!,$p:String!){register(username:$u,"
                "password:$p){account{username}}}",
                {"u": username, "p": password},
            )
            gql(
                client,
                "mutation CreateCollection($n:String!){createCollection(name:$n){id}}",
                {"n": "load-" + str(i)},
            )
        # The isolated fixture keeps one real authenticated import subscription open during k6.
        sql("workspace", f"UPDATE accounts SET role='admin' WHERE username='{username}'")
        sql(
            "catalog",
            "INSERT INTO import_jobs"
            "(id,request_key,status,source,processed,checkpoint) "
            f"VALUES ('{identity}','{identity}','running','PYPI',0,'{{}}')",
        )
        cookie = client.cookies.get("radar_session")
        if not cookie:
            raise RuntimeError("No session cookie")

    with connect(
        URL.replace("http:", "ws:"),
        origin=Origin(ORIGIN),
        additional_headers={"Cookie": "radar_session=" + cookie},
        subprotocols=[Subprotocol("graphql-transport-ws")],
        open_timeout=10,
    ) as ws:
        ws.send(json.dumps({"type": "connection_init"}))
        assert json.loads(ws.recv(10))["type"] == "connection_ack"
        ws.send(
            json.dumps(
                {
                    "type": "subscribe",
                    "id": "load",
                    "payload": {
                        "query": "subscription ImportProgress($id:UUID!){"
                        "importProgress(jobId:$id){status processed}}",
                        "variables": {"id": str(identity)},
                    },
                }
            )
        )

        def event() -> dict:
            while True:
                message = json.loads(ws.recv(10))
                if message["type"] == "ping":
                    ws.send(json.dumps({"type": "pong"}))
                elif message["type"] == "next" and not message["payload"].get("errors"):
                    return dict(message["payload"]["data"]["importProgress"])
                else:
                    raise AssertionError("Subscription ended before the expected event")

        assert event()["status"] == "running"
        delays = []
        progress = 0
        outcomes = {}
        for mode in modes:
            script = ROOT / "tests/load/stage5.js"
            print(f"{mode}: 20 accounts, active subscription. Results in {destination}", flush=True)
            container = prefix + mode
            run = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    container,
                    "--cpus=2",
                    "--memory=512m",
                    "--network",
                    PROJECT + "_backend",
                    "-e",
                    "MODE",
                    "-e",
                    "RADAR_LOAD_PREFIX",
                    "-e",
                    "RADAR_LOAD_PASSWORD",
                    "-v",
                    f"{script}:/test.js:ro",
                    "-v",
                    f"{cohort}:/data/cohort.json:ro",
                    "-v",
                    f"{destination}:/results",
                    "grafana/k6:1.0.0",
                    "run",
                    "--quiet",
                    "/test.js",
                ],
                env={
                    **os.environ,
                    "MODE": mode,
                    "RADAR_LOAD_PREFIX": prefix,
                    "RADAR_LOAD_PASSWORD": password,
                },
            )
            try:
                while run.poll() is None:
                    try:
                        run.wait(timeout=25)
                    except subprocess.TimeoutExpired:
                        progress += 1
                        tick = time.monotonic()
                        sql(
                            "catalog",
                            f"UPDATE import_jobs SET processed={progress} WHERE id='{identity}'",
                        )
                        assert event() == {"status": "running", "processed": progress}
                        delays.append(time.monotonic() - tick)
                outcomes[mode] = run.returncode
            finally:
                if run.poll() is None:
                    subprocess.run(["docker", "stop", container], check=False)
                    run.wait(timeout=20)
        started = time.monotonic()
        sql(
            "catalog",
            f"UPDATE import_jobs SET status='succeeded', completed_at=now() WHERE id='{identity}'",
        )
        assert event()["status"] == "succeeded"
        delivery = round(time.monotonic() - started, 3)
        (destination / "subscription.json").write_text(
            json.dumps(
                {
                    "elapsed_seconds_including_update": delivery,
                    "k6_exit_codes": outcomes,
                    "progress_events": len(delays),
                    "p95_progress_seconds": quantiles(delays, n=100, method="inclusive")[94]
                    if len(delays) > 1
                    else None,
                }
            ),
            encoding="utf-8",
        )
        print(f"PASS: private subscription delivered the final state in {delivery}s", flush=True)
        if any(outcomes.values()):
            raise SystemExit(f"k6 thresholds or test failed: {outcomes}")


if __name__ == "__main__":
    with prevent_idle_sleep():
        main()
