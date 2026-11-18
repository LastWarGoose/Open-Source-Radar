"""Run domain acceptance and restore Security after a controlled subgraph outage."""

from scripts.verify_infrastructure import compose


def main() -> None:
    compose("run", "--rm", "checks", ".venv/bin/python", "-m", "scripts.check_stage2")
    try:
        compose("stop", "security")
        compose(
            "run", "--rm", "checks", ".venv/bin/python", "-m", "scripts.check_stage2", "--partial"
        )
    finally:
        compose("up", "-d", "--wait", "security")
    print("PASS: stage 2 graph and partial failure checks; Security restored", flush=True)


if __name__ == "__main__":
    main()
