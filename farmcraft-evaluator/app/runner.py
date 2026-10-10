"""Reuse the trusted Docker-backed FarmCraft evaluators on the remote laptop."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

from configuration import ROOT

sys.path.insert(0, str(ROOT))

from backend.services.evaluation import evaluate_source, evaluation_plan
from backend.services.sandbox import REPLAY_DIR, REMOTE_CANCEL_CHECK, run_sandbox_source
from backend.services.scoring import load_scoring_config
from tournament import run_seeded_tournament


def execute(job: dict, client, cancel_check) -> dict:
    local_hash = hashlib.sha256((ROOT / "config" / "evaluation.json").read_bytes()).hexdigest()
    if job.get("evaluationConfigSha256") != local_hash:
        raise RuntimeError("Evaluation configuration differs from the cloud. Update this evaluator checkout.")
    token = REMOTE_CANCEL_CHECK.set(cancel_check)
    try:
        os.environ["EVALUATOR_IMAGE"] = client.config["EVALUATOR_IMAGE"]
        # sandbox.py reads this constant at import time.
        import backend.services.sandbox as sandbox
        sandbox.DOCKER_IMAGE = client.config["EVALUATOR_IMAGE"]
        if job["type"] == "sandbox":
            source = client.source(job, job["submissionId"])
            client.progress(job, "submission", "completed", "Verified submission source downloaded")
            result = run_sandbox_source(source, job["opponent"], int(job["seed"]))
            replay_id = result.get("replayId")
            if replay_id:
                replay = REPLAY_DIR / f"{replay_id}.json"
                client.replay(job, replay_id, replay.read_bytes())
            return result
        if job["type"] == "official":
            source = client.source(job, job["submissionId"])
            if hashlib.sha256(source.encode("utf-8")).hexdigest()!=job.get("submissionSha256"):
                raise RuntimeError("Frozen contestant source hash mismatch.")
            client.progress(job, "submission", "completed", "Verified submission source downloaded")
            config=job.get("qualificationConfig")
            references=job.get("referenceSources")
            if not config or not references:raise RuntimeError("Frozen qualification configuration missing.")
            return evaluate_source(source, config=config,reference_sources=references,
                progress=lambda done, total: client.progress(job, "match", "running", f"{done}/{total}", done, total),
                on_stage=lambda stage, status, detail: client.progress(job, stage, status, detail))
        if job["type"] == "reference_test":
            source=job.get("referenceSource")
            if not source:raise RuntimeError("Reference bot source missing.")
            result=run_sandbox_source(source,"starter_crop",20260929)
            if result.get("contestantFailure") or result.get("status")!="success":
                raise RuntimeError("Reference bot failed its real sandbox match.")
            return {"status":"passed","botFinalMoney":result.get("botFinalMoney")}
        if job["type"] == "tournament":
            with tempfile.TemporaryDirectory(prefix="farmcraft-remote-tournament-") as directory:
                players = []
                for index, participant in enumerate(job.get("participants", [])):
                    source = client.source(job, participant["submissionId"])
                    path = Path(directory) / f"{index}.py"
                    path.write_text(source, encoding="utf-8")
                    if hashlib.sha256(source.encode("utf-8")).hexdigest()!=participant["sha256"]:
                        raise RuntimeError("Qualified submission source hash mismatch.")
                    players.append({"username": participant["team"], "filePath": str(path),
                                    "seed":participant["seed"]})
                if len(players) < 2: raise RuntimeError("At least two active submissions are required.")
                def tournament_progress(event, data):
                    if event == "GAME_END" and data.get("replayId"):
                        replay_id=data["replayId"]
                        client.replay(job,replay_id,(REPLAY_DIR/f"{replay_id}.json").read_bytes())
                    client.progress(job, "tournament", "running", event, event=event, data=data)
                result = run_seeded_tournament(players,seed=20260929,
                    max_tie_replays=job.get("tieReplayLimit",3),
                    completed_matches=job.get("completedMatches",[]),
                    completed_games=job.get("completedGames",[]),on_progress=tournament_progress)
                if result.get("error"): raise RuntimeError(result["error"])
                return result
        raise ValueError(f"Unsupported job type: {job['type']}")
    finally:
        REMOTE_CANCEL_CHECK.reset(token)
