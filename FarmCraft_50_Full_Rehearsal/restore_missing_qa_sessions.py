#!/usr/bin/env python3
"""Recover only missing rehearsal participant sessions via existing admin recovery APIs.

Never creates teams, uploads bots, submits jobs, or changes competition phase.
Issuing recovery intentionally invalidates existing sessions for the *selected* QA
team, so every mutation requires an explicit organizer confirmation.
"""
from __future__ import annotations
import argparse,sys,time
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rehearsal as s


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',default='https://neural-coliseum-api.onrender.com')
    args=p.parse_args()
    base=s.check_target(args,mutate=False)
    data=s.init_state(base)
    s.require_preflight(data,base)
    admin_op,admin_csrf=s.admin(base)
    records=s.admin_get(admin_op,base,'/contestants').get('contestants',[])
    indexed={r['team'].casefold():r for r in records if isinstance(r,dict) and r.get('team')}
    missing=[]
    for r in s.rows():
        team=r['team']
        if not team.startswith('FC26_R50_') or team=='temp':
            raise RuntimeError('Team name outside protected QA prefix; stopped')
        row=indexed.get(team.casefold())
        if not row or not row.get('teamId'):
            raise RuntimeError(f'{team}: not registered in organizer account list; stop')
        if data['teams'][team].get('upload')!='valid':
            raise RuntimeError(f'{team}: expected validated upload is missing in local data; stop')
        cookie_file=s.RUNTIME/'sessions'/f'{team}.cookies.txt'
        if not cookie_file.exists():
            missing.append((team,row))
            print('MISSING COOKIE:',team,flush=True)
            continue
        opener,jar=s.opener_for(team)
        code,payload,_=s.request(opener,base,'GET','/api/participants/session',timeout=35)
        if code==200 and payload.get('team','').casefold()==team.casefold() and payload.get('teamId')==row['teamId']:
            continue
        if code==200:
            raise RuntimeError(f'{team}: session authenticated as DIFFERENT team/id; manual investigation required')
        if code in (401,403):
            missing.append((team,row))
            print('EXPIRED COOKIE:',team,flush=True)
        else:
            raise RuntimeError(f'{team}: auth probe HTTP {code} (transient/API error). NOT issuing recovery code.')
        time.sleep(.12)
    if not missing:
        print('ALL 50 QA SESSIONS VALID. No recovery actions or other HTTP POSTs were sent.')
        return 0
    print(f'\n{len(missing)} existing QA team session(s) need organizer recovery: '+', '.join(t for t,_ in missing))
    print('Recovery will invalidate older sessions ONLY for these listed QA teams, then store their renewed cookies locally.')
    decision=input('To approve session recovery for ONLY these QA teams, type RECOVER QA SESSIONS ONLY: ').strip()
    if decision!='RECOVER QA SESSIONS ONLY':
        raise RuntimeError('Session recovery not approved; no recovery POST sent')
    repaired=[]
    for team,entry in missing:
        # Race-check: do not rotate if another process has restored the session.
        op,jar=s.opener_for(team)
        code,payload,_=s.request(op,base,'GET','/api/participants/session',timeout=35)
        if code==200 and payload.get('team','').casefold()==team.casefold():
            print('ALREADY RESTORED:',team)
            continue
        if code not in (401,403):
            raise RuntimeError(f'{team}: session state unexpectedly HTTP {code}; no recovery POST for this team')
        # The recovery token stays in RAM; never save to JSON/state/logs.
        code,issued,_=s.request(admin_op,base,'POST','/api/admin/contestants/'+quote(team)+'/recovery',
            {'confirmation':'RESET SESSION','reason':'Restore original 50-team test participant login'},
            headers={'X-Admin-CSRF':admin_csrf},retry_read=False)
        s.must(code,200,issued,'admin recovery issue for '+team)
        token=issued.get('recoveryCode')
        if not token or issued.get('team','').casefold()!=team.casefold():
            raise RuntimeError(f'{team}: missing/mismatched one-time recovery code; stop')
        code,identity,_=s.request(op,base,'POST','/api/participants/recover',
            {'team':team,'recoveryCode':token},retry_read=False)
        token=None
        s.must(code,200,identity,'participant recovery consume for '+team)
        if identity.get('team','').casefold()!=team.casefold() or identity.get('teamId')!=entry['teamId'] or not identity.get('csrfToken'):
            raise RuntimeError(f'{team}: recovery returned wrong account or no CSRF; cookie NOT saved')
        path=s.RUNTIME/'sessions'/f'{team}.cookies.txt';path.parent.mkdir(parents=True,exist_ok=True)
        jar.save(ignore_discard=True,ignore_expires=True)
        try:path.chmod(0o600)
        except OSError:pass
        verify_code,verify, _=s.request(op,base,'GET','/api/participants/session')
        if verify_code!=200 or verify.get('team','').casefold()!=team.casefold():
            raise RuntimeError(f'{team}: new cookie failed read-back; inspect before continuing')
        repaired.append(team)
        print('RECOVERED EXISTING ACCOUNT SESSION:',team,flush=True)
        time.sleep(.3)
    print('Restored saved participant sessions:',len(repaired),'of',len(missing))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,ValueError,KeyError) as e:
        print('STOP:',str(e),file=sys.stderr)
        sys.exit(2)
