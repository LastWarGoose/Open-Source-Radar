"""Campaign journal acceptance, no source requests; run with consumers stopped."""

import os
from uuid import uuid4

from graphql import GraphQLError
from radar_common.database import engine
from radar_common.import_queue import Work
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from scripts.check_stage2 import gql
from scripts.check_stage3 import owner
from services.catalog.campaign import create
from services.catalog.domain_models import ImportJobRow
from services.catalog.import_jobs import refresh_parent


def main() -> None:
    denied = gql(
        'mutation { requestCampaign(requestKey: "00000000-0000-0000-0000-000000000005", '
        'names: ["example"], target: 1) { id } }',
        errors=True,
    )
    assert denied.get("errors")
    owner("catalog")
    identities = []
    try:
        key = uuid4()
        names = [f"radar-campaign-check-{n}" for n in range(105)]
        campaign = create(key, names, 100)
        identities.append(campaign.id)
        resumed = gql(
            "mutation Resume($id:UUID!){ resumeImport(id:$id){ id } }",
            {"id": str(campaign.id)},
            errors=True,
            headers={"x-dev-admin-token": os.environ["DEV_ADMIN_TOKEN"]},
        )
        assert resumed.get("errors"), "Legacy resume must not requeue rejected campaign candidates"
        assert campaign.pending == 40 and campaign.candidates_consumed == 40
        assert create(key, names, 100).id == campaign.id
        try:
            create(key, list(reversed(names)), 100)
        except GraphQLError:
            pass
        else:
            raise AssertionError("Changed manifest accepted under same key")
        with Session(engine()) as session, session.begin():
            rows = list(session.scalars(select(Work).where(Work.parent_id == campaign.id)))
            manifest = session.get(ImportJobRow, campaign.id)
            assert manifest
            original_manifest = manifest.checkpoint
            for i, row in enumerate(rows):
                row.status = "failed" if i < 5 else "succeeded"
        engine.cache_clear()
        refresh_parent(campaign.id)
        next_state = create(key, names, 100)
        assert (next_state.succeeded, next_state.failed, next_state.pending) == (35, 5, 40)
        while next_state.pending:
            with Session(engine()) as session, session.begin():
                for row in session.scalars(
                    select(Work).where(Work.parent_id == campaign.id, Work.status == "queued")
                ):
                    row.status = "succeeded"
            refresh_parent(campaign.id)
            next_state = create(key, names, 100)
        assert next_state.status == "succeeded" and next_state.succeeded == 100
        assert next_state.candidates_consumed == 105
        assert create(key, names, 100).completed_at == next_state.completed_at
        with Session(engine()) as session:
            parent = session.get(ImportJobRow, campaign.id)
            assert parent and parent.checkpoint == original_manifest
        exhausted = create(uuid4(), ["radar-campaign-exhausted"], 1)
        identities.append(exhausted.id)
        with Session(engine()) as session, session.begin():
            work = session.scalar(select(Work).where(Work.parent_id == exhausted.id))
            assert work
            work.status = "failed"
        refresh_parent(exhausted.id)
        with Session(engine()) as session:
            exhausted_job = session.get(ImportJobRow, exhausted.id)
            assert exhausted_job and exhausted_job.error_code == "CANDIDATES_EXHAUSTED"
        print(
            "PASS: campaign cap, deterministic replacement, durable recovery, idempotency, "
            "target without overshoot, exhausted candidates, immutable manifest and authorization"
        )
    finally:
        with Session(engine()) as session, session.begin():
            session.execute(delete(Work).where(Work.parent_id.in_(identities)))
            session.execute(delete(ImportJobRow).where(ImportJobRow.id.in_(identities)))


if __name__ == "__main__":
    main()
