"""Administrative read-only report: separate owner connections, no cross-database SQL."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from radar_common.database import database_url
from sqlalchemy import create_engine, text

from scripts.cohort_evidence import save_cohort


def read(owner: str, query: str, parameters: dict | None = None) -> list[dict]:
    database = create_engine(database_url(owner), hide_parameters=True)
    try:
        with database.connect() as connection:
            return [
                dict(row) for row in connection.execute(text(query), parameters or {}).mappings()
            ]
    finally:
        database.dispose()


def grouped(owner: str, query: str, parameters: dict | None = None) -> dict:
    return {row["key"]: row["count"] for row in read(owner, query, parameters)}


def report(campaign: str) -> tuple[dict, list[dict]]:
    params = {"campaign": UUID(campaign)}
    jobs = read(
        "catalog",
        "SELECT id,status,processed,error_code,created_at,completed_at "
        "FROM import_jobs WHERE id=:campaign",
        params,
    )
    if len(jobs) != 1:
        raise ValueError("Campaign does not exist")
    work = read(
        "catalog",
        "SELECT id,status,error_code,checkpoint,payload "
        "FROM source_work WHERE parent_id=:campaign ORDER BY created_at,id",
        params,
    )
    cohort = [
        {
            "work_id": str(row["id"]),
            "package_id": row["checkpoint"]["package"],
            "release_id": row["checkpoint"]["release"],
            "name": row["checkpoint"]["name"],
            "version": row["checkpoint"]["version"],
            "observed_at": row["checkpoint"]["observed"],
            "github_selected": row["payload"].get("repositories", False),
        }
        for row in work
        if row["status"] == "succeeded"
    ]
    packages = [row["package_id"] for row in cohort]
    releases = [row["release_id"] for row in cohort]
    assert len(packages) == len(set(packages)), "Duplicate normalized package in campaign"
    result: dict = {"captured_at": datetime.now(UTC).isoformat(), "campaign": jobs[0]}
    result["failed_candidates"] = [
        {"name": row["payload"]["name"], "error_code": row["error_code"]}
        for row in work
        if row["status"] == "failed"
    ]
    result["cohort_unique_packages"] = len(packages)
    result["cohort_unique_releases"] = len(set(releases))
    result["catalog"] = read(
        "catalog",
        """
        SELECT count(*) FILTER (WHERE source='PYPI') AS real_packages,
               count(DISTINCT name) FILTER (WHERE source='PYPI') AS real_unique_names,
               count(*) FILTER (WHERE source='SYNTHETIC') AS synthetic_packages
        FROM packages""",
    )[0]
    result["catalog"].update(
        read(
            "catalog",
            """
        SELECT count(*) AS real_releases,
               count(*) FILTER (WHERE is_prerelease) AS prereleases,
               count(*) FILTER (WHERE yanked) AS yanked
        FROM releases WHERE source='PYPI'""",
        )[0]
    )
    result["catalog"].update(
        read(
            "catalog",
            """
        SELECT count(*) AS real_requirements, count(DISTINCT d.name) AS dependency_names
        FROM dependency_requirements d JOIN releases r ON r.id=d.release_id
        WHERE r.source='PYPI'""",
        )[0]
    )
    result["cohort_projection"] = grouped(
        "catalog",
        """
        SELECT github_status AS key,count(*) FROM packages
        WHERE id=ANY(:ids) GROUP BY github_status""",
        {"ids": packages},
    )
    result["github"] = read(
        "repositories",
        """
        SELECT count(*) AS real_repositories FROM repositories WHERE source='GITHUB'""",
    )[0]
    result["github"].update(
        read(
            "repositories",
            """
        SELECT count(DISTINCT p.package_id) AS cohort_matched_packages,
               count(DISTINCT r.id) AS cohort_repositories
        FROM package_repositories p JOIN repositories r ON p.repository_id=r.id
        WHERE p.package_id=ANY(:ids) AND p.status='VERIFIED' AND r.source='GITHUB'
        """,
            {"ids": packages},
        )[0]
    )
    result["github"]["selected_packages"] = sum(row["github_selected"] for row in cohort)
    result["github"]["matching_fraction"] = (
        result["github"]["cohort_matched_packages"] / len(packages) if packages else 0
    )
    result["osv"] = read(
        "security",
        """
        SELECT count(*) AS canonical_advisories FROM vulnerabilities WHERE source='OSV'""",
    )[0]
    result["osv"].update(
        read(
            "security",
            """
        SELECT count(*) AS identifiers_including_aliases FROM vulnerability_aliases a
        JOIN vulnerabilities v ON v.id=a.vulnerability_id WHERE v.source='OSV'""",
        )[0]
    )
    result["osv"]["cohort_statuses"] = grouped(
        "security",
        """
        SELECT status AS key,count(*) FROM version_scans
        WHERE release_id=ANY(:ids) AND source='OSV' GROUP BY status""",
        {"ids": releases},
    )
    result["osv"]["cohort_unchecked"] = len(releases) - sum(
        result["osv"]["cohort_statuses"].values()
    )
    result["osv"].update(
        read(
            "security",
            """
        SELECT count(DISTINCT s.release_id) AS cohort_releases_with_findings,
               count(DISTINCT f.vulnerability_id) AS cohort_advisories,
               count(*) AS cohort_findings
        FROM version_scans s JOIN scan_findings f ON f.scan_id=s.id
        WHERE s.release_id=ANY(:ids) AND s.source='OSV'""",
            {"ids": releases},
        )[0]
    )
    for owner, suffix in (("repositories", "github"), ("security", "osv")):
        identities = [
            uuid5(UUID(row["work_id"]), suffix)
            for row in cohort
            if suffix == "osv" or row["github_selected"]
        ]
        result[suffix]["cohort_jobs"] = grouped(
            owner,
            """
            SELECT status AS key,count(*) FROM source_work WHERE id=ANY(:ids)
            GROUP BY status""",
            {"ids": identities},
        )
        result[suffix]["cohort_expected_jobs"] = len(identities)
        result[suffix]["cohort_missing_jobs"] = len(identities) - sum(
            result[suffix]["cohort_jobs"].values()
        )
        result[suffix]["cohort_errors"] = grouped(
            owner,
            """
            SELECT error_code AS key,count(*) FROM source_work WHERE id=ANY(:ids)
            AND error_code IS NOT NULL GROUP BY error_code""",
            {"ids": identities},
        )
    result["database"] = {}
    for owner in ("catalog", "repositories", "security", "workspace"):
        result["database"][owner] = read(
            owner,
            """
            SELECT current_database() AS name,pg_database_size(current_database()) AS bytes,
                   version() AS version""",
        )[0]
    return result, cohort


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign")
    parser.add_argument("--output", default="/evidence")
    parser.add_argument("--cohort-store", type=Path, default=Path("/evidence/cohorts"))
    args = parser.parse_args()
    result, cohort = report(args.campaign)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    payload = save_cohort(
        (json.dumps(cohort, indent=2, default=str) + "\n").encode(), output, args.cohort_store
    )
    result["cohort_sha256"] = payload.stem
    temporary = output / "source-report.tmp"
    temporary.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(output / "source-report.json")
    print(
        json.dumps(
            {key: result[key] for key in ("cohort_unique_packages", "github", "osv")},
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
