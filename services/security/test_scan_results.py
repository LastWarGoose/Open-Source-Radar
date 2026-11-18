from datetime import UTC, datetime

from packaging.version import Version
from radar_common.versions import nearest_version

from services.security.source import Advisory


def test_fix_belongs_to_the_package_and_affected_interval() -> None:
    def entry(name: str, events: list[dict[str, str]]) -> dict:
        return {
            "package": {"name": name, "ecosystem": "PyPI"},
            "ranges": [{"type": "ECOSYSTEM", "events": events}],
        }

    ranges = [{"introduced": "2.0"}, {"fixed": "2.1rc1"}, {"introduced": "0"}, {"fixed": "1.10"}]
    advisory = Advisory.model_validate(
        {
            "id": "TEST",
            "modified": datetime.now(UTC),
            "affected": [
                entry("Some_Pkg", ranges),
                entry("other", [{"introduced": "0"}, {"fixed": "1.1"}]),
                entry("some-pkg", [{"introduced": "3"}, {"last_affected": "3.8"}]),
                entry("some-pkg", [{"introduced": "4"}]),
            ],
        }
    )
    assert advisory.fix_for("some-pkg", "1.9") == "1.10"
    assert advisory.fix_for("some-pkg", "2.0.1") == "2.1rc1"
    for version in ("1.10", "2.1rc1", "3.5", "4.2"):
        assert advisory.fix_for("some-pkg", version) is None
    advisory.affected[0].versions.append("1.10")
    assert advisory.fix_for("some-pkg", "1.9") is None


def test_nearest_release_uses_pep440_and_prefers_the_same_series() -> None:
    versions = {Version(value): value for value in ("1.9", "1.10", "2.5rc1")}
    assert nearest_version(versions, Version("1.10.0")) == "1.10"
    assert nearest_version(versions, Version("2.4")) == "2.5rc1"
    assert nearest_version(versions, Version("3")) == "2.5rc1"
    assert nearest_version(versions, Version("0.1")) == "1.9"
    assert nearest_version({}, Version("1")) is None
