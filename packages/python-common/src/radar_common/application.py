import asyncio
from collections.abc import Awaitable, Callable

import strawberry
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from strawberry.fastapi import GraphQLRouter

from radar_common.database import ready
from radar_common.metrics import install_metrics
from radar_common.telemetry import CorrelationMiddleware, configure_logging


def create_app(
    schema: strawberry.Schema, service: str, context: Callable[..., Awaitable[dict]]
) -> FastAPI:
    configure_logging()
    app = FastAPI(title="Radar " + service)
    if service == "security":
        install_metrics(app)
    app.add_middleware(CorrelationMiddleware, service=service)
    app.include_router(GraphQLRouter(schema, context_getter=context), prefix="/graphql")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": service}

    @app.get("/ready")
    async def readiness() -> JSONResponse:
        try:
            await asyncio.to_thread(ready)
        except SQLAlchemyError:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app
