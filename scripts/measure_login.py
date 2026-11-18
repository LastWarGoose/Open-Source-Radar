"""Measure three bursts of twenty valid logins through the isolated GraphQL gateway."""

import asyncio
import os
import secrets
from contextlib import AsyncExitStack
from math import ceil
from time import perf_counter
from uuid import uuid4

import httpx

from scripts.check_stage6 import LOGIN, ORIGIN, cleanup


def p95(samples: list[float]) -> float:
    return sorted(samples)[ceil(len(samples) * 0.95) - 1]


async def measure() -> None:
    url = os.environ["GRAPHQL_URL"]
    prefix = "burst-" + uuid4().hex[:12]
    names = [f"{prefix}-{i}" for i in range(20)]
    password = secrets.token_urlsafe(24)
    signup = """mutation Prepare($u:String!,$p:String!){
      register(username:$u,password:$p){account{id username}}
    }"""
    try:
        async with AsyncExitStack() as stack:
            clients = []
            identities = {}
            for name in names:
                client = await stack.enter_async_context(
                    httpx.AsyncClient(headers={"origin": ORIGIN}, timeout=20)
                )
                response = await client.post(
                    url, json={"query": signup, "variables": {"u": name, "p": password}}
                )
                response.raise_for_status()
                result = response.json()
                if (
                    result.get("errors")
                    or result["data"]["register"]["account"]["username"] != name
                ):
                    raise RuntimeError("Could not prepare a benchmark account")
                identities[name] = result["data"]["register"]["account"]["id"]
                clients.append(client)
            reader = await stack.enter_async_context(
                httpx.AsyncClient(
                    cookies=clients[0].cookies, headers={"origin": ORIGIN}, timeout=20
                )
            )

            async def login(client: httpx.AsyncClient, name: str) -> float:
                client.cookies.clear()
                start = perf_counter()
                response = await client.post(
                    url, json={"query": LOGIN, "variables": {"u": name, "p": password}}
                )
                duration = (perf_counter() - start) * 1000
                response.raise_for_status()
                result = response.json()
                if (
                    result.get("errors")
                    or result["data"]["login"]["id"] != identities[name]
                    or not response.cookies.get("radar_session")
                ):
                    raise RuntimeError("Benchmark login failed")
                return duration

            async def read_session(done: asyncio.Event) -> list[float]:
                durations = []
                while not done.is_set():
                    start = perf_counter()
                    response = await reader.post(url, json={"query": "query Session { me { id } }"})
                    durations.append((perf_counter() - start) * 1000)
                    response.raise_for_status()
                    if response.json().get("data", {}).get("me") != {"id": identities[names[0]]}:
                        raise RuntimeError("Benchmark session read failed")
                    await asyncio.sleep(0.1)
                return durations

            samples = []
            read_samples = []
            for burst in range(4):
                done = asyncio.Event()
                reads = asyncio.create_task(read_session(done))
                try:
                    durations = await asyncio.gather(
                        *(login(client, name) for client, name in zip(clients, names, strict=True))
                    )
                finally:
                    done.set()
                    observed = await reads
                if burst:  # Discard one warm-up burst.
                    samples.extend(durations)
                    read_samples.extend(observed)
                    print(f"Burst {burst}: login p95={p95(durations):.0f} ms")
            samples.sort()
            median = samples[ceil(len(samples) * 0.50) - 1]
            print(
                f"{len(samples)} successful logins: p50={median:.0f} "
                f"p95={p95(samples):.0f} max={samples[-1]:.0f} ms; "
                f"{len(read_samples)} session reads: p95={p95(read_samples):.0f} ms"
            )
    finally:
        cleanup(names)


if __name__ == "__main__":
    asyncio.run(measure())
