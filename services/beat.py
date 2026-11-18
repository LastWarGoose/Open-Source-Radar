"""Only the PostgreSQL session-lock holder may run Beat in this local deployment."""

import os
import threading
import time
from pathlib import Path

from radar_common.database import engine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from services.catalog.celery_app import celery_app


def main() -> None:
    with engine().connect() as connection:
        if not connection.scalar(text("SELECT pg_try_advisory_lock(72163003)")):
            raise SystemExit("An import scheduler is already active")
        connection.commit()

        def heartbeat() -> None:
            while True:
                try:
                    connection.execute(text("SELECT 1"))
                    connection.commit()
                    Path("/tmp/radar-beat-heartbeat").write_text(str(time.time()), encoding="ascii")
                except SQLAlchemyError:
                    os._exit(1)  # Stop scheduling immediately if ownership of the lock is lost.
                time.sleep(5)

        threading.Thread(target=heartbeat, daemon=True).start()
        celery_app.Beat(loglevel="INFO", schedule="/tmp/radar-beat-schedule").run()


if __name__ == "__main__":
    main()
