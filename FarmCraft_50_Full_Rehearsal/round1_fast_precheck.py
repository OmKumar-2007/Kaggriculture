#!/usr/bin/env python3
"""Read-only authorization and job-drain guard before an explicitly waived wave-2 Round 1.

No job submissions, registrations, team recovery, phase transitions, or database writes.
The admin login POST only creates the organizer's temporary authenticated session.
"""
from __future__ import annotations
import argparse,sys,time
from urllib.parse import urlencode

from rehearsal import admin,admin_get,load_json,rows,STATE_FILE,PROTECTED_TEAM

ACTIVE={"queued","running","retrying","starting","pending"}


def require(condition,message):
    if not condition:raise RuntimeError(message)


def inspect(base,wait_minutes=60,poll_seconds=30):
    data=load_json(STATE_FILE)
    require(data.get('target')==base,'This saved state is for a different API origin.')
    snap=data.get('preflight') or {}
    require(snap.get('protectedTeamExists') and snap.get('selectedReferenceCount')==5,'Missing protected baseline. Run main launcher Check first.')
    assert_teams=rows()
    for row in assert_teams:
        t=row['team'];state=(data.get('teams') or {}).get(t) or {}
        require(state.get('upload')=='valid' and state.get('submissionId'),f'{t}: upload not confirmed.')
        wave1=(state.get('sandbox') or {}).get('1') or {}
        a1=(state.get('analytics') or {}).get('1') or {}
        require(wave1.get('id') and wave1.get('status')=='completed' and wave1.get('contestantStatus')!='contestant_error',f'{t}: wave-1 evaluation not verified.')
        require(a1.get('ok') is True,f'{t}: wave-1 replay not verified.')
        official=state.get('official') or {}
        require(official.get('status')!='ambiguous',f'{t}: ambiguous previous official attempt. Reconcile before trying again.')
    require(data.get('qualityGatePassed') is True,'Quality benchmark flag not verified. Stop.')
    op,csrf=admin(base)
    comp=admin_get(op,base,'/competition')
    require(comp.get('phase')=='QUALIFICATION_OPEN',f"Competition phase is {comp.get('phase')}. First manually START Round 1 in Admin; do not reset anything.")
    current_refs=admin_get(op,base,'/reference-bots').get('bots',[])
    old_refs=snap.get('references') or []
    def ref_shape(item):
        return (str(item.get('id')),item.get('sourceSha256') or item.get('source_sha256'),int(item.get('version') or 0),bool(item.get('selected')),bool(item.get('enabled')),bool(item.get('archived')))
    require({ref_shape(x) for x in old_refs}=={ref_shape(x) for x in current_refs},'Reference bot identities, versions, status or SHA hashes have changed from original preflight.')
    require(len([r for r in current_refs if r.get('selected') and r.get('enabled') and not r.get('archived')])==5,'Not exactly five active selected reference bots.')
    contestants=admin_get(op,base,'/contestants').get('contestants',[])
    expected=snap.get('protectedTeam') or []
    protected=[x for x in contestants if str(x.get('team','')).casefold()==PROTECTED_TEAM]
    require(len(protected)==1 and len(expected)==1 and all(protected[0].get(x)==expected[0].get(x) for x in ('teamId','submissionCount','latestVersion')),'Protected temp identity or submissions changed. Stop and inspect.')
    contestant_names={str(x.get('team','')).lower() for x in contestants}
    require(all(r['team'].lower() in contestant_names for r in assert_teams),'Some QA teams are not registered.')
    remote_official=admin_get(op,base,'/jobs?job_type=official&limit=500').get('jobs',[])
    owned={r['team'].lower():r['team'] for r in assert_teams}
    for job in remote_official:
        team=str(job.get('team') or '').lower()
        if team in owned:
            local=(data['teams'][owned[team]].get('official') or {}).get('id')
            require(local and str(local)==str(job.get('id')),f"{owned[team]} already has an official job not confirmed locally. Stop and reconcile; NEVER submit a second official attempt.")
    print('Read-only precheck: protected temp and 5 references unchanged; all 50 wave-1 games and replays passed.',flush=True)
    print('Round 1 is open. Wave-2 analytics requirement is being EXPLICITLY WAIVED; no wave-2 results will be fabricated.',flush=True)
    end=time.monotonic()+wait_minutes*60
    known={str((data['teams'][r['team']].get('sandbox') or {}).get('2',{}).get('id')):r['team'] for r in assert_teams if (data['teams'][r['team']].get('sandbox') or {}).get('2',{}).get('id')}
    require(len(known)==49,'Expected exactly 49 confirmed wave-2 job IDs at this checkpoint. Stop if state changed; check it manually.')
    missing=[r['team'] for r in assert_teams if not (data['teams'][r['team']].get('sandbox') or {}).get('2',{}).get('id')]
    require(missing==['FC26_R50_045'],f'Unexpected wave-2 missing jobs: {missing}. Stop.')
    while True:
        sandbox=admin_get(op,base,'/jobs?job_type=sandbox&limit=500').get('jobs',[])
        by_id={str(j.get('id')):j for j in sandbox}
        not_found=[t for jid,t in known.items() if jid not in by_id]
        require(not not_found,'Admin jobs response omits confirmed job(s) for: '+', '.join(not_found)+'. Wait or inspect; do not assume completed.')
        qa_jobs=[j for j in sandbox if str(j.get('team') or '').lower() in owned]
        active=[j for j in qa_jobs if str(j.get('status') or '') in ACTIVE]
        wave2=[by_id[jid] for jid in known]
        tally={st:sum(j.get('status')==st for j in wave2) for st in ['completed','queued','running','failed','timeout','cancelled']}
        candidates=[j for j in qa_jobs if str(j.get('team','')).lower()==missing[0].lower() and j.get('opponent')=='animal' and str(j.get('seed'))=='20262146']
        require(len(candidates)<=1,'Team 045 has multiple possible wave-2 jobs; manual reconciliation required.')
        if candidates and candidates[0].get('status') in ACTIVE:
            active.append(candidates[0])
        print(f"Wave 2 on server: {tally}; missing-local team 045: {'found '+str(candidates[0]['status']) if candidates else 'no matching job'}; active QA sandbox jobs: {len({str(j.get('id')) for j in active})}",flush=True)
        require(not any(j.get('status') in {'failed','timeout','cancelled'} for j in wave2),'One of the 49 wave-2 jobs failed. Investigate before Round 1.')
        if not active and tally['completed']==49:
            break
        if time.monotonic()>=end:
            raise RuntimeError('Timed out waiting for 49 wave-2 jobs to finish. None were retried; rerun this read-only precheck later.')
        time.sleep(poll_seconds)
    print('READY: 49 wave-2 jobs completed; no active QA sandbox work; wave-1 50/50 fully verified. Team 045 wave 2 is explicitly waived.',flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--base-url',default='https://neural-coliseum-api.onrender.com')
    p.add_argument('--wait-minutes',type=int,default=90)
    p.add_argument('--poll-seconds',type=int,default=30)
    a=p.parse_args()
    require(1<=a.wait_minutes<=360 and 10<=a.poll_seconds<=120,'Invalid polling options')
    require(a.base_url.rstrip('/')=='https://neural-coliseum-api.onrender.com','Live target must match tested API.')
    inspect(a.base_url.rstrip('/'),a.wait_minutes,a.poll_seconds)

if __name__=='__main__':
    try:main()
    except (RuntimeError,ValueError,KeyError,TypeError) as exc:
        print('STOP:',exc,file=sys.stderr);sys.exit(2)
