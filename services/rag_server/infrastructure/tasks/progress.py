import redis
import json
from typing import Dict, List
from core.config import get_required_env
import logging

logger = logging.getLogger(__name__)

PROGRESS_TTL = 3600

def get_redis_client():
    redis_url = get_required_env("REDIS_URL")
    return redis.from_url(redis_url, decode_responses=True)

def create_batch(batch_id: str, task_ids: List[str], filenames: List[str]):
    client = get_redis_client()
    batch_key = f"batch:{batch_id}"

    batch_data = {
        "batch_id": batch_id,
        "total": len(task_ids),
        "completed": 0,
        "total_chunks": 0,
        "completed_chunks": 0,
        "tasks": {}
    }

    for task_id, filename in zip(task_ids, filenames):
        batch_data["tasks"][task_id] = {
            "task_id": task_id,
            "filename": filename,
            "status": "pending",
            "data": {},
            "total_chunks": 0,
            "completed_chunks": 0
        }

    client.set(batch_key, json.dumps(batch_data), ex=PROGRESS_TTL)
    logger.info(f"[PROGRESS] Created batch {batch_id} with {len(task_ids)} tasks")

def update_task_progress(batch_id: str, task_id: str, status: str, data: Dict):
    client = get_redis_client()
    batch_key = f"batch:{batch_id}"

    batch_json = client.get(batch_key)
    if not batch_json:
        logger.warning(f"[PROGRESS] Batch {batch_id} not found in Redis")
        return

    batch_data = json.loads(batch_json)

    if task_id not in batch_data["tasks"]:
        logger.warning(f"[PROGRESS] Task {task_id} not found in batch {batch_id}")
        return

    batch_data["tasks"][task_id]["status"] = status
    batch_data["tasks"][task_id]["data"] = data

    if status in ["completed", "error"]:
        batch_data["completed"] += 1

    client.set(batch_key, json.dumps(batch_data), ex=PROGRESS_TTL)
    logger.info(f"[PROGRESS] Updated task {task_id} in batch {batch_id}: {status}")

def set_task_total_chunks(batch_id: str, task_id: str, total_chunks: int):
    client = get_redis_client()
    batch_key = f"batch:{batch_id}"

    batch_json = client.get(batch_key)
    if not batch_json:
        logger.warning(f"[PROGRESS] Batch {batch_id} not found in Redis")
        return

    batch_data = json.loads(batch_json)

    if task_id not in batch_data["tasks"]:
        logger.warning(f"[PROGRESS] Task {task_id} not found in batch {batch_id}")
        return

    batch_data["tasks"][task_id]["total_chunks"] = total_chunks
    batch_data["total_chunks"] += total_chunks

    client.set(batch_key, json.dumps(batch_data), ex=PROGRESS_TTL)
    logger.info(f"[PROGRESS] Set total chunks for task {task_id}: {total_chunks}")

def increment_task_chunk_progress(batch_id: str, task_id: str):
    client = get_redis_client()
    batch_key = f"batch:{batch_id}"

    batch_json = client.get(batch_key)
    if not batch_json:
        logger.warning(f"[PROGRESS] Batch {batch_id} not found in Redis")
        return

    batch_data = json.loads(batch_json)

    if task_id not in batch_data["tasks"]:
        logger.warning(f"[PROGRESS] Task {task_id} not found in batch {batch_id}")
        return

    batch_data["tasks"][task_id]["completed_chunks"] += 1
    batch_data["completed_chunks"] += 1

    client.set(batch_key, json.dumps(batch_data), ex=PROGRESS_TTL)

def get_batch_progress(batch_id: str) -> Dict:
    client = get_redis_client()
    batch_key = f"batch:{batch_id}"

    batch_json = client.get(batch_key)
    if not batch_json:
        return None

    return json.loads(batch_json)
