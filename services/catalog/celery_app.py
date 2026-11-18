import os
from urllib.parse import quote

from celery import Celery, Task
from celery.signals import setup_logging, task_postrun, task_prerun
from kombu import Exchange, Queue
from radar_common.telemetry import configure_logging
from radar_common.tracing import span

exchange = Exchange("catalog", type="direct", durable=True)
broker = "amqp://radar:" + quote(os.environ["RABBITMQ_PASSWORD"], safe="") + "@rabbitmq:5672/radar"
celery_app = Celery(
    "catalog", broker=broker, include=["services.catalog.tasks", "services.import_tasks"]
)
celery_app.conf.update(
    task_queues=(
        Queue("catalog.probes", exchange=exchange, routing_key="catalog.probes", durable=True),
        Queue("catalog.imports", exchange=exchange, routing_key="catalog.imports", durable=True),
        Queue(
            "repositories.imports",
            exchange=exchange,
            routing_key="repositories.imports",
            durable=True,
        ),
        Queue("security.imports", exchange=exchange, routing_key="security.imports", durable=True),
    ),
    beat_schedule={
        owner + "-dispatch": {
            "task": owner + ".dispatch",
            "schedule": 10.0,
            "options": {"queue": owner + ".imports", "routing_key": owner + ".imports"},
        }
        for owner in ("catalog", "repositories", "security")
    }
    | {
        "refresh-follows": {
            "task": "catalog.refresh-follows",
            "schedule": 900.0,
            "options": {"queue": "catalog.imports", "routing_key": "catalog.imports"},
        },
        "reconcile-projection": {
            "task": "catalog.reconcile-projection",
            "schedule": 60.0,
            "options": {"queue": "catalog.imports", "routing_key": "catalog.imports"},
        },
    },
    task_default_queue="catalog.probes",
    task_default_exchange="catalog",
    task_default_routing_key="catalog.probes",
    task_create_missing_queues=False,
    task_default_delivery_mode="persistent",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    result_backend=None,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"confirm_publish": True},
    task_publish_retry=False,
    worker_hijack_root_logger=False,
    timezone="UTC",
    enable_utc=True,
)


@setup_logging.connect
def setup_task_logging(**kwargs: object) -> None:
    configure_logging()


@task_prerun.connect
def start_task_span(task: Task, **kwargs: object) -> None:
    parent = (task.request.headers or {}).get("traceparent")
    ctx = span(os.environ.get("SERVICE_NAME", "catalog") + "-worker", task.name, parent)
    ctx.__enter__()
    task.request.radar_span = ctx


@task_postrun.connect
def finish_task_span(task: Task, **kwargs: object) -> None:
    if ctx := getattr(task.request, "radar_span", None):
        ctx.__exit__(None, None, None)
