#!/usr/bin/env python3
"""Exact, operator-approved reconciliation of two missing sandbox wave-1 jobs.

Never creates accounts or uploads bots. Never retries a submission with an
unknown outcome. Reuses existing authenticated participant sessions.
"""
import argparse
import datetime
from urllib.parse import quote, urlencode
import rehearsal as kit

TARGETS=('FC26_R50_003','FC26_R50_004')
EXPECTED_SUBMISSIONS={'FC26_R50_003':42,'FC26_R50_004':43}


def exact_matches(jobs, team, seed, opponent, submission):
    return [j for j in jobs if isinstance(j,dict)
            and j.get('type')=='sandbox'
            and str(j.get('team') or '').casefold()==team.casefold()
            and str(j.get('seed'))==str(seed)
            and j.get('opponent')==opponent
            and str(j.get('submissionId'))==str(submission)
            and j.get('id')]


def server_jobs(op,base,team):
    query=urlencode({'team':team,'job_type':'sandbox','limit':100})
    rows=kit.admin_get(op,base,'/jobs?'+query).get('jobs',[])
    if not isinstance(rows,list):raise RuntimeError('Organizer API returned malformed job history.')
    return [j for j in rows if str(j.get('team') or '').casefold()==team.casefold()]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='https://neural-coliseum-api.onrender.com')
    args=parser.parse_args()
    args.staging_host='';args.approve_live=False
    base=kit.check_target(args,mutate=False)
    data=kit.init_state(base)
    kit.require_preflight(data,base)
    op,_=kit.admin(base)
    comp=kit.admin_get(op,base,'/competition')
    if comp.get('phase')!='SETUP':
        raise RuntimeError('Refusing all sandbox POSTs: competition phase is not SETUP.')
    contestants=kit.admin_get(op,base,'/contestants').get('contestants',[])
    refs=kit.admin_get(op,base,'/reference-bots').get('bots',[])
    if len([r for r in refs if r.get('selected') and r.get('enabled') and not r.get('archived')])!=5:
        raise RuntimeError('Five protected selected reference bots not confirmed.')
    if len([t for t in contestants if str(t.get('team') or '').casefold()=='temp'])!=1:
        raise RuntimeError('Protected temp team not confirmed. Aborting.')
    original_refs={str(r['id']):r.get('sourceSha256') or r.get('source_sha256')
                   for r in data['preflight']['references']}
    for ref in refs:
        if str(ref.get('id')) in original_refs and (ref.get('sourceSha256') or ref.get('source_sha256'))!=original_refs[str(ref['id'])]:
            raise RuntimeError('Protected reference-bot hash changed since initial preflight. Aborting.')
    if any(str(data['teams'][team].get('upload'))!='valid' for team in TARGETS):
        raise RuntimeError('The two expected valid uploads were not present in local state.')
    all_rows=kit.rows()
    all_names={r['team']:i for i,r in enumerate(all_rows,1)}
    to_post=[]; restored=[]; bad=[]
    for team in TARGETS:
        state=data['teams'][team]
        submission=state.get('submissionId')
        if str(submission)!=str(EXPECTED_SUBMISSIONS[team]):
            bad.append(f'{team}: local submission changed from expected {EXPECTED_SUBMISSIONS[team]} to {submission}')
            continue
        match_team=[t for t in contestants if str(t.get('team') or '').casefold()==team.casefold()]
        if len(match_team)!=1:
            bad.append(f'{team}: server has {len(match_team)} matching participant teams; cannot repair jobs')
            continue
        if not match_team[0].get('submissionCount'):
            bad.append(f'{team}: admin shows no uploaded submission; cannot repair jobs')
            continue
        index=all_names[team]
        seed=20261101+index
        opponent='balanced'
        rec=state['sandbox'].setdefault('1',{})
        if rec.get('id'):
            print(f'ALREADY RECONCILED {team}: {rec["id"]}; no POST',flush=True)
            continue
        if rec.get('seed') not in (None,seed) or rec.get('opponent') not in (None,opponent):
            bad.append(f'{team}: local seed/opponent differs from expected wave-1 configuration')
            continue
        rec.update({'seed':seed,'opponent':opponent})
        jobs=server_jobs(op,base,team)
        matches=exact_matches(jobs,team,seed,opponent,submission)
        if len(matches)==1:
            job=matches[0]
            rec.update(id=job['id'],status='queued',recoveredAt=kit.now(),
                       serverStatusOnRecovery=job.get('status'))
            kit.atomic_json(kit.STATE_FILE,data)
            restored.append(team)
            print(f'RECOVERED {team}: {job["id"]} serverStatus={job.get("status")}; no POST',flush=True)
        elif len(matches)>1:
            bad.append(f'{team}: {len(matches)} exact sandbox jobs on server; manual inspection required')
        elif jobs:
            bad.append(f'{team}: server has {len(jobs)} DIFFERENT sandbox jobs; do not submit another')
        elif rec.get('repairAttemptedAt'):
            bad.append(f'{team}: previous targeted repair attempt at {rec["repairAttemptedAt"]} has uncertain result; no repeat POST')
        else:
            try:
                participant,session,_=kit.session(team,base,create=False)
                code,summary,_=kit.request(participant,base,'GET','/botlab/'+quote(team))
                kit.must(code,200,summary,f'{team} participant Bot Lab check')
                current=(summary.get('currentSubmission') or {})
                if str(current.get('id'))!=str(submission) or current.get('validation_status','valid') not in ('valid',None):
                    raise RuntimeError('participant account has unexpected latest bot version')
                to_post.append((team,participant,session,rec))
                print(f'CONFIRMED MISSING {team}: registered, upload #{submission}, 0 sandbox jobs, expected seed {seed}, opponent {opponent}',flush=True)
            except Exception as exc:
                bad.append(f'{team}: participant confirmation failed: {str(exc)[:160]}')
    if bad:
        kit.atomic_json(kit.STATE_FILE,data)
        for detail in bad:print('STOP:',detail,flush=True)
        print('No POST jobs sent. Some existing IDs may have been restored locally.',flush=True)
        return 2
    if not to_post:
        print('No new jobs needed. All existing jobs reconciled locally. Choose menu 7 to resume monitoring.',flush=True)
        return 0
    print('The following REAL new sandbox POSTs will be sent ONCE:',', '.join(t[0] for t in to_post),flush=True)
    response=input('To approve ONLY these missing sandbox jobs type POST MISSING 003 004: ').strip()
    if response!='POST MISSING 003 004':
        print('Cancelled, no POST jobs sent.',flush=True)
        return 2
    failures=0
    for team,participant,sess,rec in to_post:
        # Persist this irreversible intention BEFORE sending, preventing repeated attempts after a crash/502.
        rec.update(status='ambiguous',repairAttemptedAt=kit.now(),reconciliation='manual-approved-single-attempt')
        kit.atomic_json(kit.STATE_FILE,data)
        body=urlencode({'seed':rec['seed'],'opponent':rec['opponent']}).encode('ascii')
        try:
            code,result,ms=kit.request(participant,base,'POST','/botlab/'+quote(team)+'/sandbox',body,
                      headers={'Content-Type':'application/x-www-form-urlencoded',
                               'X-Participant-CSRF':sess['csrfToken']},timeout=40,retry_read=False)
            if code==202 and isinstance(result,dict) and result.get('id'):
                rec.update(id=result['id'],status='queued',http=202,submitMs=ms)
                kit.event('approved_targeted_sandbox_repair',team,{'id':result['id'],'seed':rec['seed']})
                print(f'QUEUED {team}: {result["id"]}',flush=True)
            else:
                failures+=1
                rec['http']=code
                print(f'STOP {team}: HTTP {code}; acceptance unknown. DO NOT retry this POST.',flush=True)
        except Exception as exc:
            failures+=1
            print(f'STOP {team}: {str(exc)[:180]}; acceptance unknown. DO NOT retry this POST.',flush=True)
        finally:
            kit.atomic_json(kit.STATE_FILE,data)
    if failures:
        print('Some POST results were ambiguous; use read-only reconciliation; never rerun targeted POST.',flush=True)
        return 2
    print('SUCCESS: all missing sandbox wave-1 job IDs are now confirmed. Resume menu 7.',flush=True)
    return 0

if __name__=='__main__':
    import sys
    try:sys.exit(main())
    except Exception as exc:
        print('STOP:',str(exc)[:500],file=sys.stderr)
        sys.exit(2)
