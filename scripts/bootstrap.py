"""Generate local secrets without printing values or replacing an existing .env."""

import os
import secrets
from pathlib import Path

KEYS = (
    "POSTGRES_PASSWORD",
    "CATALOG_DB_PASSWORD",
    "REPOSITORIES_DB_PASSWORD",
    "SECURITY_DB_PASSWORD",
    "WORKSPACE_DB_PASSWORD",
    "RABBITMQ_PASSWORD",
    "DEV_ADMIN_TOKEN",
)


def main() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.exists():
        print("Existing .env preserved; no credentials changed.")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
        for key in KEYS:
            output.write(f"{key}={secrets.token_hex(24)}\n")
    print("Created ignored .env with local credentials.")


if __name__ == "__main__":
    main()
