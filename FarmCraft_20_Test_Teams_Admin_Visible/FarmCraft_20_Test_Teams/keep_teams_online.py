#!/usr/bin/env python3
"""Send bounded QA heartbeats to make provisioned test teams appear online in Control Center.

Only uses sessions created by provision_test_teams.py, never creates any account.
This is a time-limited, low-volume visibility check, not a stress test.
"""
from __future__ import annotations

import argparse
import csv
from http.cookiejar import MozillaCookieJar
import json
from pathlib import Path
import sys
import time
from urllib.request import HTTPCookieProcessor, build_opener

from provision_test_teams import ROOT, check_target, request


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://127.0.0.1:8000')
    p.add_argument('--runtime-dir', type=Path, default=ROOT/'runtime')
    p.add_argument('--duration-seconds', type=int, default=120,
                   help='How long to send heartbeats (30..600 seconds)')
    p.add_argument('--interval-seconds', type=int, default=15,
                   help='Seconds between batches (10..30)')
    p.add_argument('--allow-staging', action='store_true')
    p.add_argument('--staging-host')
    p.add_argument('--allow-production', action='store_true')
    p.add_argument('--acknowledge-competition-slots', action='store_true')
    p.add_argument('--execute', action='store_true', help='Actually send heartbeats')
    args = p.parse_args()
    if not 30 <= args.duration_seconds <= 600 or not 10 <= args.interval_seconds <= 30:
        p.error('duration must be 30..600 and interval must be 10..30 seconds')
    args.base_url = args.base_url.rstrip('/')
    return args


def heartbeat_batch(sessions, base):
    """Send one real heartbeat per authenticated test session."""
    successes = 0
    failures = []
    for team, opener in sessions:
        try:
            status, data, _ = request(opener, base, 'GET', '/api/participants/session')
            if status != 200 or data.get('team', '').casefold() != team.casefold():
                failures.append((team, f'session HTTP {status}'))
                continue
            csrf = data.get('csrfToken')
            if not csrf:
                failures.append((team, 'missing csrfToken'))
                continue
            status, response, _ = request(
                opener, base, 'POST', '/api/participants/heartbeat',
                data=json.dumps({'idle': False, 'latencyMs': None}).encode('utf-8'),
                headers={'Content-Type':'application/json','X-Participant-CSRF':csrf}
            )
            if status == 200 and response.get('status') == 'ok':
                successes += 1
            else:
                failures.append((team, f'heartbeat HTTP {status}: {str(response.get("detail", response))[:100]}'))
        except Exception as error:
            failures.append((team, str(error)[:100]))
    return successes, failures


def main():
    args = parse_args()
    with (ROOT/'teams.csv').open(encoding='utf-8', newline='') as file:
        teams = [row['team'] for row in csv.DictReader(file)]
    check_target(args.base_url, args)
    sessions = []
    for team in teams:
        path = args.runtime_dir/'sessions'/f'{team}.cookies.txt'
        if not path.is_file():
            continue
        jar = MozillaCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=True)
        opener = build_opener(HTTPCookieProcessor(jar))
        sessions.append((team, opener))
    if not args.execute:
        print(f'DRY RUN: {len(sessions)}/{len(teams)} saved sessions found; no heartbeats sent.')
        print('Add --execute to mark these test sessions online for a limited time.')
        return 0
    if len(sessions) != len(teams):
        raise SystemExit(f'Expected {len(teams)} saved sessions but found {len(sessions)}. Provision teams first.')
    deadline = time.monotonic() + args.duration_seconds
    batch = 0
    while True:
        batch += 1
        successes, failures = heartbeat_batch(sessions, args.base_url)
        print(f'Heartbeat batch {batch}: {successes}/{len(sessions)} online signals accepted', flush=True)
        for team, message in failures[:5]:
            print(f'  {team}: {message}', flush=True)
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(args.interval_seconds, remaining))
    print('Finished. Presence becomes idle/offline naturally after heartbeats stop.')
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
