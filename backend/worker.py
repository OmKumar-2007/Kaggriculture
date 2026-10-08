"""Start a bounded number of RQ worker processes."""
from __future__ import annotations
import multiprocessing,os,time,threading,logging,socket,re
from uuid import uuid4

log=logging.getLogger("neural_coliseum.worker")

def count_limit() -> int:
    return max(1,min(int(os.getenv("MAX_EVALUATION_WORKERS",os.getenv("SIMULATION_WORKERS","2"))),8))

def serve(index: int):
    from rq import Worker, SimpleWorker
    from rq import Queue
    from backend.services.queueing import QUEUE_PRIORITY,redis_connection
    from backend.services.storage import store
    worker_class = SimpleWorker if os.name == "nt" else Worker
    from backend.services.host_telemetry import publish_host_sample, publish_worker_sample
    node = re.sub(r"[^a-zA-Z0-9_-]", "-", os.getenv("WORKER_NODE_NAME", socket.gethostname()))[:40]
    connection=redis_connection(); name=f"{node}-simulation-{index}"; ref={"worker":None}
    rq_name=f"{name}~{os.getpid()}-{uuid4().hex[:8]}"
    def heartbeat():
        while True:
            worker=ref["worker"]
            try:
                current=worker.get_current_job() if worker else None
                mode=connection.hget("arena:worker:modes",name)
                mode=mode.decode() if isinstance(mode,bytes) else mode
                store.record_worker(name,status="busy" if current else (mode or "idle"),current_job_id=current.id if current else None)
                if current:
                    store.touch_job_heartbeat(current.id)
                publish_worker_sample(name,busy=bool(current))
                if index == 1:
                    publish_host_sample()
            except Exception: log.exception("Worker heartbeat failed")
            time.sleep(max(2,int(os.getenv("WORKER_HEARTBEAT_INTERVAL","5"))))
    threading.Thread(target=heartbeat,daemon=True,name=f"{name}-heartbeat").start()
    last_reconcile = 0.0
    while True:
        try:
            if index == 1 and time.monotonic() - last_reconcile > 30:
                from backend.services.queueing import reconcile_queued_jobs
                store.recover_stale_jobs(int(os.getenv("STALE_JOB_SECONDS", "300")))
                reconcile_queued_jobs()
                last_reconcile = time.monotonic()
            paused=connection.smembers("arena:paused_queues")
            mode=connection.hget("arena:worker:modes",name)
            capacity=int(connection.get("arena:worker:active_capacity") or count_limit())
            if mode or index > capacity:
                label=mode.decode() if isinstance(mode,bytes) else mode
                store.record_worker(name,status=label or "paused")
                time.sleep(1);continue
            active=[queue for queue in QUEUE_PRIORITY if queue.encode() not in paused and queue not in paused]
            if not active:
                store.record_worker(name,status="idle")
                time.sleep(1);continue
            worker=worker_class([Queue(queue,connection=connection) for queue in active],connection=connection,name=rq_name)
            ref["worker"]=worker
            did_work=worker.work(burst=True,max_jobs=1,with_scheduler=False)
            if not did_work:time.sleep(.5)
        except Exception:
            log.exception("Worker loop failed")
            time.sleep(2)

if __name__=="__main__":
    count=count_limit()
    processes=[multiprocessing.Process(target=serve,args=(i+1,),name=f"simulation-{i+1}") for i in range(count)]
    for process in processes:process.start()
    for process in processes:process.join()
