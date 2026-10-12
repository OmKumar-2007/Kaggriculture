#!/usr/bin/env python3
"""Read-only server reconciliation of a previously submitted FarmCraft QA sandbox wave.

Writes only to the existing local runtime/state.json. DOES NOT submit or retry jobs.
Queries authenticated organizer /api/admin/jobs (which includes seed/opponent),
unlike participant /teams/{team}/jobs (which omits those fields).
"""
from __future__ import annotations
import argparse
from urllib.parse import urlencode
import rehearsal as kit


def exact_matches(jobs, team: str, seed: int, opponent: str, submission_id: int):
    return [j for j in jobs
            if isinstance(j, dict) and j.get('type') == 'sandbox'
            and str(j.get('team') or '').casefold() == team.casefold()
            and str(j.get('seed')) == str(seed)
            and str(j.get('opponent')) == opponent
            and str(j.get('submissionId')) == str(submission_id)
            and j.get('id')]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wave',type=int,required=True,choices=(1,2))
    parser.add_argument('--base-url',default='https://neural-coliseum-api.onrender.com')
    args=parser.parse_args()
    # The organizer endpoint is read-only. No --approve-live / --execute accepted.
    args.staging_host=''
    base=kit.check_target(args,mutate=False)
    data=kit.init_state(base)
    kit.require_preflight(data,base)
    wave=str(args.wave)
    allrows=kit.rows()
    started=sum(bool(data['teams'][r['team']]['sandbox'].get(wave)) for r in allrows)
    if started==0:
        raise RuntimeError(f'Wave {wave} has no recorded submissions; refuse to infer that it was launched.')
    need=[(i,r) for i,r in enumerate(allrows,1)
          if not data['teams'][r['team']]['sandbox'].get(wave,{}).get('id')]
    print(f'Wave {wave}: {50-len(need)}/50 local IDs; checking {len(need)} missing against organizer history.',flush=True)
    if not need:
        return 0
    # Mark missing IDs unsafe to resubmit BEFORE network lookups. Saves guard state on interruption.
    for index,r in need:
        team=r['team'];s=data['teams'][team]
        rec=s['sandbox'].setdefault(wave,{})
        rec.update(status='ambiguous',seed=20261101+(args.wave-1)*1000+index,
                   opponent=('balanced' if args.wave==1 else 'animal'))
        rec.setdefault('at',kit.now())
    kit.atomic_json(kit.STATE_FILE,data)
    # One admin login; never print or persist the password.
    op,_=kit.admin(base)
    comp=kit.admin_get(op,base,'/competition')
    if comp.get('phase')!='SETUP':
        raise RuntimeError(f'Competition phase is {comp.get("phase")}; refuse reconciliation in an unexpected phase.')
    recovered=0;unresolved=[]
    for index,r in need:
        team=r['team'];s=data['teams'][team]
        rec=s['sandbox'][wave]
        seed=rec['seed'];opponent=rec['opponent'];submission=s.get('submissionId')
        if not submission:
            unresolved.append((team,'local submission ID missing'))
            print(f'UNRESOLVED {team}: local submission ID missing')
            continue
        try:
            params=urlencode({'team':team,'job_type':'sandbox','limit':100})
            jobs=kit.admin_get(op,base,'/jobs?'+params).get('jobs',[])
            matched=exact_matches(jobs,team,seed,opponent,submission)
            if len(matched)==1:
                j=matched[0]
                rec['id']=j['id']
                rec['status']='queued'  # Always repoll: completed jobs need their replay/result recorded locally.
                rec['recoveredAt']=kit.now()
                rec['serverStatusOnRecovery']=j.get('status')
                kit.event('sandbox_admin_reconciled',team,{'wave':wave,'id':j['id']})
                recovered+=1
                print(f'RECOVERED {team}: {j["id"]} (server: {j.get("status")})',flush=True)
            else:
                reason=f'{len(matched)} exact matching jobs on server'
                rec['reconciliation']='manual-review'
                unresolved.append((team,reason))
                kit.event('sandbox_manual_review',team,{'wave':wave,'matches':len(matched)})
                print(f'UNRESOLVED {team}: {reason}; no POST was retried',flush=True)
        except Exception as exc:
            reason=str(exc)[:180]
            unresolved.append((team,reason))
            kit.event('sandbox_reconcile_read_error',team,{'wave':wave,'message':reason})
            print(f'UNRESOLVED {team}: admin read failed: {reason}',flush=True)
        finally:
            kit.atomic_json(kit.STATE_FILE,data)
    print(f'Wave {wave}: {recovered} IDs recovered; {len(unresolved)} unresolved; NO HTTP POST submissions sent.',flush=True)
    if unresolved:
        print('STOP: Do not use menu option 3 to resubmit these teams. Inspect above and seek manual reconciliation.',flush=True)
        return 2
    return 0

if __name__=='__main__':
    import sys
    try:sys.exit(main())
    except Exception as exc:
        print('STOP:',str(exc)[:500],file=sys.stderr)
        sys.exit(2)
