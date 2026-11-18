import asyncio

from services.catalog.app import listeners, schema


def test_subscription_cleanup_and_unknown_id() -> None:
    async def run() -> None:
        events = await schema.subscribe(
            'subscription { packageUpdated(id: "pypi:fastapi") { id demoRevision } }'
        )
        initial = await anext(events)
        assert initial.errors is None
        assert initial.data is not None
        assert initial.data["packageUpdated"]["id"] == "pypi:fastapi"
        assert len(listeners["pypi:fastapi"]) == 1
        await events.aclose()
        assert len(listeners["pypi:fastapi"]) == 0
        result = await schema.execute('mutation { advanceDemo(id: "missing") { id } }')
        assert result.errors
        assert "Unknown demo package" in result.errors[0].message

    asyncio.run(run())
