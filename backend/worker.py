"""Start a bounded number of RQ worker processes."""
from __future__ import annotations
import multiprocessing,os,time,threading,logging

log=logging.getLogger("neural_coliseum.worker")

def serve(index: int):
    from rq import Worker, SimpleWorker
    from rq import Queue
    from backend.services.queueing import QUEUE_PRIORITY,redis_connection
    from backend.services.storage import store
    worker_class = SimpleWorker if os.name == "nt" else Worker
    connection=redis_connection(); name=f"simulation-{index}"; ref={"worker":None}
    def heartbeat():
        while True:
            worker=ref["worker"]
            try:
                current=worker.get_current_job() if worker else None
                store.record_worker(name,status="busy" if current else "idle",current_job_id=current.id if current else None)
            except Exception: log.exception("Worker heartbeat failed")
            time.sleep(max(2,int(os.getenv("WORKER_HEARTBEAT_INTERVAL","5"))))
    threading.Thread(target=heartbeat,daemon=True,name=f"{name}-heartbeat").start()
    while True:
        try:
            paused=connection.smembers("arena:paused_queues")
            active=[queue for queue in QUEUE_PRIORITY if queue.encode() not in paused and queue not in paused]
            if not active:
                store.record_worker(name,status="idle")
                time.sleep(1);continue
            worker=worker_class([Queue(queue,connection=connection) for queue in active],connection=connection,name=name)
            ref["worker"]=worker
            did_work=worker.work(burst=True,max_jobs=1,with_scheduler=False)
            if not did_work:time.sleep(.5)
        except Exception:
            log.exception("Worker loop failed")
            time.sleep(2)

if __name__=="__main__":
    count=max(1,min(int(os.getenv("SIMULATION_WORKERS","2")),8))
    processes=[multiprocessing.Process(target=serve,args=(i+1,),name=f"simulation-{i+1}") for i in range(count)]
    for process in processes:process.start()
    for process in processes:process.join()
