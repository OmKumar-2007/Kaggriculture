"""Mixed contestant and spectator traffic. Never targets remote hosts by default."""
from __future__ import annotations
import itertools, os, time
from pathlib import Path
from urllib.parse import urlparse

from locust import HttpUser, between, events, task

COUNTER=itertools.count(1); RUN_ID=int(time.time())
SOURCE=(Path(__file__).resolve().parent/"agent.py").read_bytes()
PROFILE=os.getenv("LOAD_PROFILE","mixed").lower()

@events.init.add_listener
def protect_public_target(environment,**_):
    host=environment.host or "http://127.0.0.1:8000";name=urlparse(host).hostname
    if name in ("neural-coliseum.onrender.com","neural-coliseum-api.onrender.com"):
        raise RuntimeError("Load testing the public production Neural Coliseum service is disabled.")
    if name not in ("localhost","127.0.0.1","::1") and os.getenv("ALLOW_REMOTE_LOAD_TEST")!="1":
        raise RuntimeError("Remote load testing is disabled. Set ALLOW_REMOTE_LOAD_TEST=1 only for an approved staging host.")
    approved={item.strip().lower() for item in os.getenv("LOAD_TEST_STAGING_HOSTS","").split(",") if item.strip()}
    if name not in ("localhost","127.0.0.1","::1") and "staging" not in (name or "").lower() and name not in approved:
        raise RuntimeError("Remote target is not an approved staging host. Set LOAD_TEST_STAGING_HOSTS to the exact hostnames.")

class ContestantUser(HttpUser):
    wait_time=between(1,3)
    weight=7 if PROFILE=="mixed" else (1 if PROFILE in ("contestants","uploads","sandbox","official") else 0)
    def on_start(self):
        self.team=f"load_{RUN_ID}_{next(COUNTER):05d}";self.submission=None;self.job=None;self.completed_type=None;self.official_sent=False
        if PROFILE=="official":
            self.upload()
            self.submit_official()

    @task(5)
    def bot_lab(self):
        self.client.get(f"/botlab/{self.team}",name="GET /botlab/:team")
        if not self.submission:self.upload()

    def upload(self):
        response=self.client.post("/botlab/upload",data={"username":self.team},files={"agent":("agent.py",SOURCE,"text/x-python")},name="POST /botlab/upload")
        if response.ok:self.submission=response.json().get("submission")

    @task(4)
    def sandbox(self):
        if PROFILE not in ("mixed","contestants","sandbox"):return
        if not self.submission:self.upload();return
        if self.job:self.poll();return
        if self.completed_type=="sandbox":self.completed_type=None
        response=self.client.post(f"/botlab/{self.team}/sandbox",data={"opponent":"starter_crop","seed":20260929},name="POST /botlab/:team/sandbox")
        if response.status_code==202:self.job=response.json()["id"]

    @task(1)
    def official(self):
        if PROFILE not in ("mixed","contestants","official") or self.official_sent:return
        if not self.submission:self.upload();return
        if self.job:self.poll();return
        self.submit_official()

    def submit_official(self):
        if self.official_sent or not self.submission:return
        response=self.client.post(f"/botlab/{self.team}/submit",name="POST /botlab/:team/submit")
        if response.status_code==202:self.job=response.json()["id"];self.official_sent=True

    @task(3)
    def analytics_and_leaderboard(self):
        self.client.get(f"/botlab/{self.team}",name="GET /botlab/:team")
        self.client.get("/leaderboard")
        if self.job:self.poll()

    def poll(self):
        response=self.client.get(f"/jobs/{self.job}",name="GET /jobs/:id")
        if response.ok and response.json().get("status") in ("completed","failed","cancelled"):
            self.completed_type=response.json().get("type");self.job=None

class SpectatorUser(HttpUser):
    wait_time=between(1,4)
    weight=3 if PROFILE=="mixed" else (1 if PROFILE in ("spectators","status") else 0)
    @task(4)
    def leaderboard(self):self.client.get("/leaderboard")
    @task(3)
    def tournament(self):self.client.get("/tournament/status")
    @task(2)
    def status(self):self.client.get("/health");self.client.get("/event/status")
