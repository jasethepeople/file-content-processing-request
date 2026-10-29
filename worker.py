"""Celery worker configuration for bounded Hermes background jobs."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from celery import Celery

broker_url = os.getenv("HERMES_REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("hermes", broker=broker_url, backend=broker_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=150,
    task_time_limit=180,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(bind=True, autoretry_for=(OSError,), retry_backoff=True, retry_jitter=True, retry_kwargs={"max_retries": 3})
def queue_heartbeat(self) -> dict[str, str]:
    """Verify that the worker can accept a non-sensitive job.

    Production tools should enqueue only encrypted argument references and a
    policy-validated approval ID, never raw passwords or private keys.
    """
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}
