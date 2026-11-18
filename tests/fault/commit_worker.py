"""Mounted only in the isolated probe worker. Stop one child exactly at the ack boundary."""

import os
import signal
from pathlib import Path

from celery import Task
from celery.signals import task_postrun, task_prerun


def interrupt(task: Task, phase: str) -> None:
    if (
        task.name != "catalog.probe"
        or task.request.id != os.environ["FAULT_JOB_ID"]
        or phase != os.environ["FAULT_PHASE"]
    ):
        return
    try:
        Path("/tmp/probe-interrupted").touch(exist_ok=False)
    except FileExistsError:
        return
    os.kill(os.getpid(), signal.SIGKILL)


@task_prerun.connect
def before(task: Task, **kwargs: object) -> None:
    interrupt(task, "before")


@task_postrun.connect
def after(task: Task, **kwargs: object) -> None:
    interrupt(task, "after")
