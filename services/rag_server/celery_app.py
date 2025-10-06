from celery import Celery
from core_logic.env_config import get_required_env
import logging

logger = logging.getLogger(__name__)

redis_url = get_required_env("REDIS_URL")

celery_app = Celery(
    "rag_tasks",
    broker=redis_url,
    backend=redis_url,
    include=["tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

logger.info(f"[CELERY] Celery app configured with Redis: {redis_url}")
