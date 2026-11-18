"""Suspend only source consumers while running deterministic DB checks, then restore them."""

from scripts.verify_infrastructure import compose

CONSUMERS = ("beat", "catalog-importer", "repositories-importer", "security-importer")


def main() -> None:
    try:
        compose("stop", *CONSUMERS)
        compose("run", "--rm", "checks", ".venv/bin/python", "-m", "scripts.check_stage3")
    finally:
        compose("up", "-d", "--wait", *CONSUMERS)
    print("PASS: stage 3 deterministic checks; source consumers restored", flush=True)


if __name__ == "__main__":
    main()
