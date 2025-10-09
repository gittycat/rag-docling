from celery import Celery
from celery.signals import worker_process_init
from core_logic.env_config import get_required_env
from core_logic.logging_config import configure_logging
import logging

configure_logging()
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
    worker_without_mingle=True,
    worker_without_gossip=True,
    worker_log_format='[%(levelname)s/%(processName)s] %(message)s',
    worker_task_log_format='[%(levelname)s/%(processName)s] [%(task_name)s] %(message)s',
)

@worker_process_init.connect
def init_worker(**kwargs):
    from core_logic.settings import initialize_settings
    logger.info("[CELERY] Initializing settings for worker process")
    initialize_settings()
    logger.info("[CELERY] Worker process initialization complete")

logger.info(f"[CELERY] Celery app configured with Redis: {redis_url}")
