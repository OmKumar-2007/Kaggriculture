import tempfile,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from backend.services.blob_storage import LocalObjectStorage, AzureBlobStorage
from backend.services.storage import ActiveJobError,PlatformStore
from tests.official_helpers import open_round_one, official_payload

class JobPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=PlatformStore(Path(self.temp.name)/"jobs.db")
        self.submission=self.store.create_submission("TeamOne","submissions/TeamOne/1/agent.py",valid=True)
    def tearDown(self):self.temp.cleanup()
    def test_duplicate_active_job_is_rejected(self):
        self.store.create_job("TeamOne","sandbox",submission_id=self.submission["id"],opponent="balanced",seed=1)
        with self.assertRaises(ActiveJobError):self.store.create_job("TeamOne","sandbox",submission_id=self.submission["id"],opponent="balanced",seed=2)
    def test_job_has_exactly_one_terminal_outcome(self):
        open_round_one(self.store)
        job=self.store.create_job("TeamOne","official",submission_id=self.submission["id"],progress_total=8,payload=official_payload())
        self.store.mark_job_running(job["id"],"worker-1");self.store.update_job_progress(job["id"],3,8);self.store.finish_job(job["id"],{"rating":10});self.store.fail_job(job["id"],"late failure")
        saved=self.store.get_job(job["id"]);self.assertEqual(saved["status"],"completed");self.assertEqual(saved["progressCurrent"],8);self.assertIsNone(saved["error"])
    def test_one_official_submission_even_after_failure_and_reopen(self):
        open_round_one(self.store)
        first=self.store.create_job("TeamOne","official",submission_id=self.submission["id"],payload=official_payload())
        self.store.fail_job(first["id"],"bad bot","CONTESTANT_FAILURE")
        reopened=PlatformStore(Path(self.temp.name)/"jobs.db")
        self.assertEqual(reopened.official_attempts("TeamOne")["remaining"],0)
        with self.assertRaises(ActiveJobError):
            reopened.create_job("TeamOne","official",submission_id=self.submission["id"],payload=official_payload())
    def test_concurrent_official_clicks_create_one_job(self):
        open_round_one(self.store)
        path=Path(self.temp.name)/"jobs.db"
        stores=[PlatformStore(path),PlatformStore(path)]
        def submit(index):
            try:
                return stores[index].create_job("TeamOne","official",submission_id=self.submission["id"],payload=official_payload())
            except ActiveJobError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(submit,range(2)))
        self.assertEqual(sum(item is not None for item in results),1)
    def test_infrastructure_retry_reuses_frozen_job(self):
        open_round_one(self.store)
        first=self.store.create_job("TeamOne","official",submission_id=self.submission["id"],payload=official_payload())
        self.store.fail_job(first["id"],"worker crashed","WORKER_FAILURE")
        retried=self.store.retry_failed_infrastructure_job(first["id"],2)
        self.assertEqual(retried["id"],first["id"])
        self.assertEqual(retried["retryCount"],1)
        self.assertEqual(retried["status"],"queued")
        self.assertEqual(self.store.official_attempts("TeamOne")["remaining"],0)
    def test_submission_versions_are_unique_under_concurrency(self):
        versions=[];lock=threading.Lock()
        def create(index):
            item=self.store.create_submission("Concurrent",f"submissions/Concurrent/{index}/agent.py",valid=True)
            with lock:versions.append(item["version"])
        threads=[threading.Thread(target=create,args=(i,)) for i in range(8)]
        [x.start() for x in threads];[x.join() for x in threads]
        self.assertEqual(sorted(versions),list(range(1,9)))

    def test_job_survives_store_reinitialization(self):
        job=self.store.create_job("TeamOne","sandbox",submission_id=self.submission["id"],opponent="balanced",seed=1)
        reopened=PlatformStore(Path(self.temp.name)/"jobs.db")
        self.assertEqual(reopened.get_job(job["id"])["status"],"queued")

    def test_rehearsal_data_never_enters_public_leaderboard(self):
        rehearsal=self.store.create_submission("rehearsal_001","rehearsal/agent.py",valid=True,rehearsal=True)
        self.store.record_evaluation(rehearsal["id"],{"status":"complete","rating":9999,"winRate":100,"games":8})
        self.store.activate_submission("rehearsal_001",rehearsal["id"])
        self.assertEqual(self.store.leaderboard(),[])
        self.assertTrue(next(row for row in self.store.contestant_metrics() if row["team"]=="rehearsal_001")["isRehearsal"])
        self.assertEqual(self.store.reset_rehearsal_data(),1)

class ObjectStorageTests(unittest.TestCase):
    def test_local_round_trip_and_path_guard(self):
        with tempfile.TemporaryDirectory() as root:
            storage=LocalObjectStorage(Path(root));storage.put_bytes("submissions/team/agent.py",b"pass")
            self.assertEqual(storage.get_bytes("submissions/team/agent.py"),b"pass")
            with self.assertRaises(ValueError):storage.put_bytes("../escape",b"bad")
    def test_azure_blob_keys_reject_traversal_and_controls(self):
        for bad in ("../secret", "/root", "a//b", "a\\b", "a\x00b", "a?b"):
            with self.assertRaises(ValueError):AzureBlobStorage._key(bad)
        self.assertEqual(AzureBlobStorage._key("private/submissions/agent.py"),"private/submissions/agent.py")

if __name__=="__main__":unittest.main()
