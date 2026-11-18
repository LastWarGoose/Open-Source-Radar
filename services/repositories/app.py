"""DemoRepository fields are resolved here, in a separate subgraph process."""

import asyncio

import strawberry
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from radar_common.database import ready
from radar_common.graphql import FederatedSchema
from radar_common.import_api import read_work
from radar_common.metrics import install_metrics
from radar_common.telemetry import CorrelationMiddleware, configure_logging
from sqlalchemy.exc import SQLAlchemyError
from strawberry.fastapi import GraphQLRouter

from services.repositories.domain_graphql import DomainQuery, Package, context_getter
from services.repositories.import_api import Mutation
from services.repositories.projection import repository_snapshots


@strawberry.type
class DemoRepository:
    id: strawberry.ID
    full_name: str
    url: str
    stars: int


FIXTURES = {
    "pypi:fastapi": DemoRepository(
        id=strawberry.ID("demo:fastapi"),
        full_name="fastapi/fastapi",
        url="https://github.com/fastapi/fastapi",
        stars=12345,
    ),
    "pypi:strawberry-graphql": DemoRepository(
        id=strawberry.ID("demo:strawberry"),
        full_name="strawberry-graphql/strawberry",
        url="https://github.com/strawberry-graphql/strawberry",
        stars=6789,
    ),
}


@strawberry.federation.type(keys=["id"], extend=True)
class DemoPackage:
    id: strawberry.ID = strawberry.federation.field(external=True)

    @classmethod
    def resolve_reference(cls, id: strawberry.ID) -> "DemoPackage":
        return cls(id=id)

    @strawberry.field
    async def repository(self) -> DemoRepository | None:
        return FIXTURES.get(str(self.id))


@strawberry.type
class Query(DomainQuery):
    repository_snapshots = strawberry.field(resolver=repository_snapshots)
    repository_import_job = strawberry.field(resolver=read_work)

    @strawberry.field
    async def repository_service(self) -> str:
        return "repositories-stage0"


schema = FederatedSchema(
    query=Query, mutation=Mutation, types=[DemoPackage, Package], federation_version="2.7"
)
configure_logging()
app = FastAPI(title="Radar Repositories")
install_metrics(app)
app.add_middleware(CorrelationMiddleware, service="repositories")
app.include_router(GraphQLRouter(schema, context_getter=context_getter), prefix="/graphql")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "repositories"}


@app.get("/ready")
async def readiness() -> JSONResponse:
    try:
        await asyncio.to_thread(ready)
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})
