"""Offline campaign checks, preserving the existing consumer configuration and budgets."""

from scripts.verify_infrastructure import compose
from scripts.verify_stage3 import CONSUMERS


def main() -> None:
    running = set(compose("ps", "--status", "running", "--services").splitlines())
    restore = [name for name in CONSUMERS if name in running]
    try:
        if restore:
            compose("stop", *restore)
        compose("run", "--rm", "checks", ".venv/bin/python", "-m", "scripts.check_stage5")
    finally:
        if restore:
            compose("start", "--wait", *restore)
    print("PASS: offline campaign checks; previous consumer configuration restored", flush=True)


if __name__ == "__main__":
    main()
