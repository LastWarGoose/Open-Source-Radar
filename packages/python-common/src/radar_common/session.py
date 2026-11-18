"""Session transport; account storage belongs exclusively to Workspace."""

import hmac
import os

import httpx
from graphql import GraphQLError
from starlette.requests import HTTPConnection
from strawberry.types import Info

from radar_common.tracing import trace_headers

COOKIE = "radar_session"


def require_origin(request: HTTPConnection) -> None:
    allowed = {"http://localhost:3000", "http://127.0.0.1:3000"}
    if site := os.getenv("SITE_URL"):
        allowed.add(site.rstrip("/"))
    if request.headers.get("origin") not in allowed:
        raise GraphQLError("Origin rejected", extensions={"code": "FORBIDDEN"})


def internal(request: HTTPConnection) -> bool:
    expected = os.getenv("DEV_ADMIN_TOKEN", "")
    return bool(expected) and hmac.compare_digest(
        request.headers.get("x-dev-admin-token", ""), expected
    )


async def require_admin(info: Info) -> None:
    request = info.context["request"]
    if request.scope["type"] == "websocket":
        params = info.context.get("connection_params") or {}
        headers = [
            (key.encode(), str(params.get(key, "")).encode()) for key in ("cookie", "origin")
        ]
        request = HTTPConnection({"type": "websocket", "headers": headers})
    if internal(request):
        return
    require_origin(request)
    cookie = request.headers.get("cookie", "")
    if not request.cookies.get(COOKIE):
        raise GraphQLError("Sign in required", extensions={"code": "UNAUTHENTICATED"})
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                "http://workspace:8000/graphql",
                headers={"cookie": cookie, **trace_headers()},
                json={"query": "query SessionRole { me { id role } }"},
            )
            result = response.json()
            if response.status_code != 200 or result.get("errors"):
                raise ValueError
            actor = result["data"]["me"]
    except (httpx.HTTPError, ValueError, KeyError):
        raise GraphQLError(
            "Session service unavailable", extensions={"code": "UNAVAILABLE"}
        ) from None
    if not actor:
        raise GraphQLError("Session expired", extensions={"code": "UNAUTHENTICATED"})
    if actor["role"] != "admin":
        raise GraphQLError("Administrator required", extensions={"code": "FORBIDDEN"})
