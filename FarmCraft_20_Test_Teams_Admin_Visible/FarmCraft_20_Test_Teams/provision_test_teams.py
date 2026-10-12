#!/usr/bin/env python3
"""Register 20 QA teams and upload 20 distinct agent.py files via real FarmCraft APIs.

Safe by default (dry run); writes local HTTP-only session cookies under runtime/.
No official submissions or tournament registrations are performed.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
from http.cookiejar import MozillaCookieJar
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
PRODUCTION = {"neural-coliseum-api.onrender.com", "neural-coliseum.onrender.com"}
LOCK = threading.Lock()


def request(opener, base, method, path, data=None, headers=None, timeout=20):
    req = Request(base + path, data=data, method=method, headers={
        "Accept": "application/json", "User-Agent": "FarmCraft-QA20/1.0", **(headers or {})
    })
    started = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as response:
            status, raw = response.status, response.read(512_000)
    except HTTPError as error:
        status, raw = error.code, error.read(512_000)
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        obj = {"detail": raw.decode("utf-8", errors="replace")[:400]}
    return status, obj, round((time.perf_counter()-started)*1000, 1)


def multipart_upload(team, source):
    boundary = "farmcraftqa_" + uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"username\"\r\n\r\n{team}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"agent\"; filename=\"agent.py\"\r\n"
        f"Content-Type: text/x-python\r\n\r\n"
    ).encode("utf-8") + source + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, {"Content-Type": "multipart/form-data; boundary=" + boundary}


def check_target(base, args):
    p = urlparse(base)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
        raise SystemExit("Invalid --base-url; use e.g. http://127.0.0.1:8000 or https://staging.example.com")
    host = p.hostname.lower()
    if host in PRODUCTION:
        if not (args.allow_production and args.acknowledge_competition_slots):
            raise SystemExit("Production blocked: 20 test teams occupy real registration slots. "
                "Explicitly add --allow-production --acknowledge-competition-slots only if authorized.")
        if p.scheme != "https":
            raise SystemExit("Production requires https://")
    elif host not in {"localhost", "127.0.0.1", "::1"}:
        if not args.allow_staging or host != (args.staging_host or "").lower() or p.scheme != "https":
            raise SystemExit("Remote targets require --allow-staging --staging-host EXACT_HOST and HTTPS")


def get_session(opener, cookies, base, team):
    status, obj, latency = request(opener, base, "GET", "/api/participants/session")
    if status == 200:
        if obj.get("team", "").casefold() != team.casefold():
            raise RuntimeError("Stored cookie belongs to another team; refusing to reuse session")
        return obj, "restored", latency
    status, obj, latency = request(
        opener, base, "POST", "/api/participants/session",
        data=json.dumps({"team": team}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    if status != 200:
        raise RuntimeError(f"Session creation returned HTTP {status}: {obj.get('detail',obj)}")
    if obj.get("team", "").casefold() != team.casefold() or not obj.get("csrfToken"):
        raise RuntimeError("Unexpected session response")
    cookies.save(ignore_discard=True, ignore_expires=True)
    try:
        os.chmod(cookies.filename, 0o600)
    except OSError:
        pass
    return obj, "created", latency


def team_task(row, index, args, base):
    if args.arrival_delay:
        time.sleep(index * args.arrival_delay)
    team = row["team"]
    result = {"team": team, "bot": row["bot_name"], "session": "not_started", "upload": "not_started", "sandbox": "not_requested", "job_id": "", "error": ""}
    cookies_path = args.runtime_dir / "sessions" / f"{team}.cookies.txt"
    cookies_path.parent.mkdir(parents=True, exist_ok=True)
    jar = MozillaCookieJar(str(cookies_path))
    if cookies_path.exists():
        jar.load(ignore_discard=True, ignore_expires=True)
    opener = build_opener(HTTPCookieProcessor(jar))
    try:
        session, session_state, session_latency = get_session(opener, jar, base, team)
        result.update(session=session_state, session_ms=session_latency)
        csrf = session["csrfToken"]
        auth_headers = {"X-Participant-CSRF": csrf}
        status, summary, _ = request(opener, base, "GET", "/botlab/" + quote(team, safe=""))
        if status != 200:
            raise RuntimeError(f"GET /botlab/{team}: HTTP {status} {summary.get('detail',summary)}")
        previous = summary.get("currentSubmission") if isinstance(summary, dict) else None
        if previous and not args.force_upload:
            result["upload"] = "already_present"
        else:
            source = (ROOT / row["bot_file"]).read_bytes()
            body, hdr = multipart_upload(team, source)
            status, upload, elapsed = request(opener, base, "POST", "/botlab/upload",
                                              data=body, headers={**auth_headers, **hdr}, timeout=45)
            result["upload_ms"] = elapsed
            if status != 200:
                raise RuntimeError(f"Bot upload returned HTTP {status}: {upload.get('detail',upload)}")
            validation = upload.get("validation") or {}
            if validation.get("valid") is not True:
                raise RuntimeError("Bot uploaded but failed server validation: " + str(validation.get("errors", [])))
            result["upload"] = "validated"
            result["submission_id"] = (upload.get("submission") or {}).get("id")
        if args.mode == "sandbox" and index < args.max_sandbox_jobs:
            status, job, elapsed = request(opener, base, "POST", "/botlab/" + quote(team, safe="") + "/sandbox",
                                           data=urlencode({"opponent": args.opponent, "seed": args.seed + index}).encode("ascii"),
                                           headers={**auth_headers, "Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
            if status != 202 or not isinstance(job, dict) or not job.get("id"):
                raise RuntimeError(f"Sandbox submit returned HTTP {status}: {job.get('detail',job)}")
            result["sandbox"] = "queued"
            result["job_id"] = job["id"]
            result["sandbox_submit_ms"] = elapsed
        elif args.mode == "sandbox":
            result["sandbox"] = "skipped_by_limit"
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, KeyError) as error:
        result["error"] = str(error)[:500]
    with LOCK:
        print(f"[{index+1:02d}/20] {team}: session={result['session']}, upload={result['upload']}, sandbox={result['sandbox']}" +
              (" ERROR=" + result['error'] if result['error'] else ""), flush=True)
    return result


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend API URL (not frontend URL)")
    p.add_argument("--execute", action="store_true", help="Actually create sessions/accounts and upload bots; otherwise dry run")
    p.add_argument("--mode", choices=("upload", "sandbox"), default="upload")
    p.add_argument("--max-sandbox-jobs", type=int, default=4, help="By default only first 4 bots submit sandbox jobs")
    p.add_argument("--opponent", choices=("starter_crop", "random", "balanced", "trader", "animal"), default="starter_crop")
    p.add_argument("--seed", type=int, default=20260929)
    p.add_argument("--workers", type=int, default=2, help="Concurrent HTTP clients: 1-4")
    p.add_argument("--arrival-delay", type=float, default=0.6, help="Start delay in seconds between successive team requests")
    p.add_argument("--runtime-dir", type=Path, default=ROOT / "runtime")
    p.add_argument("--allow-staging", action="store_true")
    p.add_argument("--staging-host", help="Exact authorized staging hostname")
    p.add_argument("--allow-production", action="store_true")
    p.add_argument("--acknowledge-competition-slots", action="store_true")
    p.add_argument("--force-upload", action="store_true", help="Upload again even when a team already has a submission")
    args = p.parse_args()
    if not 1 <= args.workers <= 4 or not 0 <= args.max_sandbox_jobs <= 20 or args.arrival_delay < 0:
        p.error("workers must be 1-4, max-sandbox-jobs 0-20, arrival-delay >= 0")
    args.base_url = args.base_url.rstrip("/")
    return args


def main():
    args = parse_args()
    with (ROOT / "teams.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 20 or len({row['team'].casefold() for row in rows}) != 20:
        raise SystemExit("Expected 20 unique team names")
    for row in rows:
        source = ROOT / row["bot_file"]
        if not source.is_file() or len(source.read_bytes()) > 100_000:
            raise SystemExit("Bot missing or too large: " + str(source))
    print(f"Prepared {len(rows)} teams, {len(rows)} unique bots, mode={args.mode}, target={args.base_url}")
    if not args.execute:
        print("DRY RUN ONLY — no external accounts or uploads created. Add --execute after choosing an isolated staging target.")
        for row in rows:
            print(row["team"], "->", row["bot_name"], row["bot_file"])
        return 0
    check_target(args.base_url, args)
    opener=build_opener()
    status, payload, _ = request(opener, args.base_url, "GET", "/health")
    if status != 200:
        raise SystemExit(f"Target not healthy: HTTP {status}: {payload}")
    status, payload, _ = request(opener, args.base_url, "GET", "/ready")
    if status != 200:
        raise SystemExit(f"Target not ready: HTTP {status}: {payload}")
    args.runtime_dir.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(team_task,row,i,args,args.base_url) for i,row in enumerate(rows)]
        results=[f.result() for f in futures]
    report={"target":args.base_url,"mode":args.mode,"created":sum(r['session']=='created' for r in results),
            "restored":sum(r['session']=='restored' for r in results),
            "uploaded":sum(r['upload']=='validated' for r in results),
            "existing_uploads":sum(r['upload']=='already_present' for r in results),
            "sandbox_queued":sum(r['sandbox']=='queued' for r in results),
            "errors":sum(bool(r['error']) for r in results),"teams":results}
    out=args.runtime_dir/"provision_results.json"
    out.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("\nSummary:", {key:val for key,val in report.items() if key not in ('teams',)})
    print("Report:",out)
    print("Session cookies are under:", args.runtime_dir/'sessions', "— keep them private and out of Git.")
    return 1 if report['errors'] else 0


if __name__ == "__main__":
    sys.exit(main())
