"""Celery application — the entry point both the worker and the API import.

Two roles, both backed by Redis here:
  broker  : the queue the API pushes tasks onto and the worker pulls from.
  backend : where task state/results are stored so the API can poll them.

The worker is started with:
  celery -A worker.celery_app worker --loglevel=info
"""

from celery import Celery

from core.config import REDIS_URL

celery_app = Celery(
    "rag",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["worker.tasks"],   # modules Celery imports to discover @task funcs
)

celery_app.conf.update(
    task_track_started=True,    # expose a "started" state, not just pending->done
    result_expires=3600,        # forget results after 1h so Redis stays small
)
