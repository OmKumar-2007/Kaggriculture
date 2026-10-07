"""Redis/RQ transport. PostgreSQL remains the job source of truth."""
from __future__ import annotations

import os
from redis import Redis
from rq import Queue, Retry

QUEUE_PRIORITY=("tournament","official","sandbox")

def redis_connection() -> Redis:
    url=os.getenv("REDIS_URL")
    if not url: raise RuntimeError("REDIS_URL is required for simulation jobs.")
    return Redis.from_url(url,decode_responses=False,socket_connect_timeout=2,socket_timeout=5)

def ping_redis() -> bool: return bool(redis_connection().ping())

def enqueue(job: dict):
    connection=redis_connection(); queue=Queue(job["queue"],connection=connection,default_timeout=int(os.getenv("MATCH_TIMEOUT_SECONDS","120"))*12)
    retry=Retry(max=1,interval=[10]) if job["type"] in ("tournament",) else None
    return queue.enqueue("backend.jobs.execute_job",job["id"],job_id=job["id"],retry=retry,result_ttl=86400,failure_ttl=86400)

def queue_position(job: dict) -> int | None:
    if job["status"]!="queued":return None
    try:
        ids=Queue(job["queue"],connection=redis_connection()).get_job_ids()
        return ids.index(job["id"])+1 if job["id"] in ids else None
    except Exception:return None

def worker_count() -> int:
    try:
        from rq import Worker
        return len(Worker.all(connection=redis_connection()))
    except Exception:return 0
