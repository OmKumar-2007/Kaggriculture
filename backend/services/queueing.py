"""Redis/RQ transport. PostgreSQL remains the job source of truth."""
from __future__ import annotations

import os
from redis import Redis
from rq import Queue, Retry

QUEUE_PRIORITY=("tournament","official","sandbox")

def postgres_queue() -> bool:
    return os.getenv("QUEUE_BACKEND", "redis").lower() == "postgres"

def redis_connection() -> Redis:
    url=os.getenv("REDIS_URL")
    if not url: raise RuntimeError("REDIS_URL is required for simulation jobs.")
    return Redis.from_url(url,decode_responses=False,socket_connect_timeout=2,socket_timeout=5)

def ping_redis() -> bool: return bool(redis_connection().ping())

def enqueue(job: dict):
    if postgres_queue():
        return job["id"]  # create_job committed the durable queue entry already.
    connection=redis_connection(); queue=Queue(job["queue"],connection=connection,default_timeout=int(os.getenv("MATCH_TIMEOUT_SECONDS","120"))*12)
    retry=Retry(max=max(0, int(os.getenv("MAX_INFRASTRUCTURE_RETRIES", "2")))) if job["type"] in ("sandbox", "official") and int(os.getenv("MAX_INFRASTRUCTURE_RETRIES", "2")) > 0 else None
    return queue.enqueue("backend.jobs.execute_job",job["id"],job_id=job["id"],retry=retry,result_ttl=86400,failure_ttl=86400)

def queue_position(job: dict) -> int | None:
    if job["status"]!="queued":return None
    if postgres_queue():
        from backend.services.storage import store
        waiting = store.list_admin_jobs(status="queued", limit=1000)
        ids = [row["id"] for row in reversed(waiting) if row["queue"] == job["queue"]]
        return ids.index(job["id"])+1 if job["id"] in ids else None
    try:
        ids=Queue(job["queue"],connection=redis_connection()).get_job_ids()
        return ids.index(job["id"])+1 if job["id"] in ids else None
    except Exception:return None

def worker_count() -> int:
    if postgres_queue():
        from backend.services.storage import store
        return sum(row["status"] == "active" for row in store.remote_workers())
    try:
        from rq import Worker
        return len(Worker.all(connection=redis_connection()))
    except Exception:return 0

def reconcile_queued_jobs(limit: int = 1000) -> int:
    """Restore durable database jobs when Redis lost its volatile job records."""
    if postgres_queue(): return 0
    from rq.job import Job
    from backend.services.storage import store
    connection = redis_connection()
    lock = connection.lock("arena:queue:reconcile", timeout=60, blocking=False)
    if not lock.acquire(blocking=False):
        return 0
    restored = 0
    try:
        for job in store.list_admin_jobs(status="queued", limit=limit):
            try:
                existing = Job.fetch(job["id"], connection=connection)
                if existing.get_status(refresh=True) in ("queued", "deferred", "scheduled"):
                    continue
                existing.delete()
            except Exception:
                pass
            enqueue(job)
            restored += 1
    finally:
        try:
            lock.release()
        except Exception:
            pass
    return restored
