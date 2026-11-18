"""Stage 0 fixtures only: one process, volatile state, no external requests."""

import asyncio
from collections.abc import AsyncGenerator

import strawberry
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from radar_common.database import ready
from radar_common.graphql import FederatedSchema
from radar_common.metrics import install_metrics
from radar_common.telemetry import CorrelationMiddleware, configure_logging
from sqlalchemy.exc import SQLAlchemyError
from strawberry.fastapi import GraphQLRouter

from services.catalog.campaign import import_campaign, request_campaign
from services.catalog.domain_graphql import DomainQuery, context_getter
from services.catalog.import_jobs import import_job, request_import, resume_import
from services.catalog.job_graphql import probe_job, request_probe_job
from services.catalog.progress import import_progress
from services.catalog.projection import update_repository_projection

FIXTURES = {
    "pypi:fastapi": ("fastapi", "Фреймворк для создания API на Python"),
    "pypi:strawberry-graphql": ("strawberry-graphql", "GraphQL для Python с аннотациями типов"),
}
revisions: dict[str, int] = dict.fromkeys(FIXTURES, 0)
listeners: dict[str, set[asyncio.Queue[int]]] = {key: set() for key in FIXTURES}


@strawberry.federation.type(keys=["id"])
class DemoPackage:
    id: strawberry.ID
    name: str
    summary: str
    demo_revision: int

    @classmethod
    def resolve_reference(cls, id: strawberry.ID) -> "DemoPackage | None":
        return get_package(str(id))


def get_package(package_id: str) -> DemoPackage | None:
    fixture = FIXTURES.get(package_id)
    if fixture is None:
        return None
    return DemoPackage(
        id=strawberry.ID(package_id),
        name=fixture[0],
        summary=fixture[1],
        demo_revision=revisions[package_id],
    )


@strawberry.type
class Query(DomainQuery):
    import_campaign = strawberry.field(resolver=import_campaign)
    probe_job = strawberry.field(resolver=probe_job)
    import_job = strawberry.field(resolver=import_job)

    @strawberry.field
    async def demo_packages(self) -> list[DemoPackage]:
        # Fixed two-item fixture. Catalog pagination belongs to stage 2.
        return [package for key in FIXTURES if (package := get_package(key)) is not None]

    @strawberry.field
    async def demo_package(self, id: strawberry.ID) -> DemoPackage | None:
        return get_package(str(id))


@strawberry.type
class Mutation:
    request_campaign = strawberry.mutation(resolver=request_campaign)
    update_repository_projection = strawberry.mutation(resolver=update_repository_projection)
    request_probe_job = strawberry.mutation(resolver=request_probe_job)
    request_import = strawberry.mutation(resolver=request_import)
    resume_import = strawberry.mutation(resolver=resume_import)

    @strawberry.mutation
    async def advance_demo(self, id: strawberry.ID) -> DemoPackage:
        key = str(id)
        package = get_package(key)
        if package is None:
            raise ValueError("Unknown demo package")
        revisions[key] += 1
        for queue in listeners[key]:
            # Coalesce updates: a signal asks subscribers to read the latest state.
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(revisions[key])
        package.demo_revision = revisions[key]
        return package


@strawberry.type
class Subscription:
    import_progress = strawberry.subscription(resolver=import_progress)

    @strawberry.subscription
    async def package_updated(self, id: strawberry.ID) -> AsyncGenerator[DemoPackage, None]:
        key = str(id)
        if key not in FIXTURES:
            raise ValueError("Unknown demo package")
        if sum(map(len, listeners.values())) >= 128:
            raise ValueError("Demo subscription limit reached")
        queue: asyncio.Queue[int] = asyncio.Queue(maxsize=1)
        listeners[key].add(queue)
        try:
            package = get_package(key)
            if package is not None:
                yield package
            while True:
                await queue.get()
                package = get_package(key)
                if package is not None:
                    yield package
        finally:
            listeners[key].discard(queue)


schema = FederatedSchema(
    query=Query, mutation=Mutation, subscription=Subscription, federation_version="2.7"
)
configure_logging()
app = FastAPI(title="Radar Catalog")
install_metrics(
    app,
    {
        "real_packages": "SELECT count(*) FROM packages WHERE source='PYPI'",
        "packages_with_github": "SELECT count(*) FROM packages WHERE source='PYPI' "
        "AND github_stars IS NOT NULL",
    },
)
app.add_middleware(CorrelationMiddleware, service="catalog")
app.include_router(
    GraphQLRouter(
        schema, context_getter=context_getter, subscription_protocols=["graphql-transport-ws"]
    ),
    prefix="/graphql",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "catalog"}


@app.get("/ready")
async def readiness() -> JSONResponse:
    try:
        await asyncio.to_thread(ready)
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})
