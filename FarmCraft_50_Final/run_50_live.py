"""FarmCraft isolated staging 50-team LIVE harness. Uses real Azure API; never executes automatically on import.
Requires: pip install requests. Run with --execute and explicit admin password env var.
No destructive reset or VM operations. Admin mode MAINTENANCE + phase SETUP + no contestants required.
"""
import argparse, concurrent.futures, datetime, hashlib, json, os, pathlib, sys, threading, time
import requests
ROOT=pathlib.Path(__file__).resolve().parent
BASE='https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
TEAMS=[f'LOAD50_20261013_{n:03d}' for n in range(1,51)]
EXPECTED={'farmcraft-kr-01','farmcraft-kr-02','farmcraft-id-01','farmcraft-id-02'}
OUT=ROOT/'private-evidence';OUT.mkdir(exist_ok=True)
TERMINAL={'completed','failed','timeout','cancelled'}

def timestamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def api(s,method,path,**kw):
    r=s.request(method,BASE+path,timeout=60,**kw)
    if not r.ok:raise RuntimeError(f'{method} {path}: HTTP {r.status_code}: {r.text[:300]}')
    return r.json()
def save(d):
    p=OUT/'load50_state.json';tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(d,indent=2,default=str),encoding='utf-8')
    try:os.chmod(tmp,0o600)
    except OSError:pass
    tmp.replace(p)
def admin_session():
    password=os.environ.pop('FARMCRAFT_STAGING_ADMIN_PASSWORD',None)
    if not password:raise RuntimeError('FARMCRAFT_STAGING_ADMIN_PASSWORD missing from process environment')
    s=requests.Session();v=api(s,'POST','/api/admin/login',json={'password':password});password=None
    s.headers['x-admin-csrf']=v['csrfToken'];return s

def gates(s,current,**changes):
    fields=('mode','registrationsEnabled','uploadsEnabled','sandboxEnabled','officialEnabled','tournamentEnabled','leaderboardVisible','submissionLimit','submissionCooldownSeconds')
    payload={k:current[k] for k in fields if k in current};payload.update(changes)
    return api(s,'PUT','/api/admin/event',json=payload)

def check(admin):
    r=api(admin,'GET','/ready');event=api(admin,'GET','/api/admin/event');c=api(admin,'GET','/api/admin/competition')
    ws=api(admin,'GET','/api/admin/remote-workers')['workers'];participants=api(admin,'GET','/api/admin/contestants')['contestants']
    refs=api(admin,'GET','/api/admin/reference-bots')['bots']
    eligible={w['name'] for w in ws if w['status']=='idle' and w.get('availableSlots',0)>=1}
    assert r['status']=='ready' and all(r['checks'].values()),r
    assert c['phase']=='SETUP',f"Expected fresh SETUP, got {c['phase']}"
    assert event['mode']=='MAINTENANCE',f"Expected MAINTENANCE, got {event['mode']}"
    assert not any(event[k] for k in ('registrationsEnabled','uploadsEnabled','sandboxEnabled','officialEnabled','tournamentEnabled'))
    assert not participants,f"Expected no contestants, got {len(participants)}; refuse contamination"
    assert EXPECTED<=eligible,f'Need four idle workers, found {sorted(eligible)}'
    assert c['settings']['referenceCount']==3 and c['settings']['qualificationSeedCount']==1
    assert c['settings']['qualifierCount']==16
    selected=[b for b in refs if b.get('selected') and b.get('enabled') and not b.get('archived')]
    assert len(selected)==3 and all(b.get('validationStatus')=='valid' and b.get('testStatus')=='passed' for b in selected),'Expected three validated and tested reference bots'
    assert not any(j['status'] in ('queued','running') for j in api(admin,'GET','/api/admin/jobs?limit=500')['jobs']),'Active jobs remain'
    return event

def login(name):
    s=requests.Session();v=api(s,'POST','/api/participants/session',json={'team':name})
    assert v['team']==name
    s.headers['x-participant-csrf']=v['csrfToken']
    return s

def ensure_sources():
    x={}
    for name in TEAMS:
        path=ROOT/'bots'/name/'main.py';source=path.read_bytes()
        assert len(source)<100000
        compile(source,str(path),'exec')
        x[name]=(source,hashlib.sha256(source).hexdigest())
    assert len({h for _,h in x.values()})==50
    return x

def run(args):
    prior=OUT/'load50_state.json'
    if prior.exists():raise RuntimeError(f'Prior state exists at {prior}. Reconcile, do not duplicate.')
    sources=ensure_sources();admin=admin_session();original=check(admin)
    d={'startedAt':timestamp(),'base':BASE,'teams':{},'observations':[]};save(d)
    sessions={}
    try:
        gates(admin,original,mode='DEVELOPMENT',registrationsEnabled=True,uploadsEnabled=True,sandboxEnabled=False,officialEnabled=False,tournamentEnabled=False,leaderboardVisible=False)
        for name in TEAMS:
            s=login(name);sessions[name]=s
            src,sha=sources[name]
            obj=api(s,'POST','/botlab/upload',data={'username':name},files={'agent':('main.py',src,'text/x-python')})
            assert obj['validation']['valid'],f'Invalid {name}: {obj["validation"]}'
            assert api(s,'POST',f'/botlab/{name}/validate')['valid']
            d['teams'][name]={'sha256':sha,'submissionId':obj['submission']['id'],'uploadAt':timestamp()};save(d)
            print('UPLOADED',name,flush=True)
        assert sessions[TEAMS[0]].get(BASE+f'/botlab/{TEAMS[1]}',timeout=30).status_code==403
        gates(admin,original,mode='MAINTENANCE',registrationsEnabled=False,uploadsEnabled=False,sandboxEnabled=False,officialEnabled=False,tournamentEnabled=False)
        phase=api(admin,'POST','/api/admin/competition/start-qualification',json={'confirmation':'START QUALIFICATION','openAccess':False})
        assert phase['phase']=='QUALIFICATION_OPEN'
        assert len(phase['referencePool'])==3 and len(phase['evaluationConfig']['seeds'])==1
        assert phase['evaluationConfig']['sides']==[0,1]
        gates(admin,original,mode='QUALIFICATION',registrationsEnabled=False,uploadsEnabled=False,sandboxEnabled=False,officialEnabled=True,tournamentEnabled=False,leaderboardVisible=True)
        print('READY FOR LIVE 50-TEAM TEST: 50 uploads, 4 workers, Round 1 open',flush=True)
        if args.hold_before_burst:
            input('Operator checkpoint: press Enter to release the synchronized 50-submission burst. ')
        barrier=threading.Barrier(50)
        def submit(name):
            barrier.wait(timeout=30)
            t=time.time();v=api(sessions[name],'POST',f'/botlab/{name}/submit')
            return name,t,time.time(),v
        d['burstStartAt']=timestamp();save(d)
        results=[];errors=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            futures={executor.submit(submit,name):name for name in TEAMS}
            for future in concurrent.futures.as_completed(futures):
                name=futures[future]
                try:
                    returned,t0,t1,v=future.result()
                    assert returned==name
                    d['teams'][name].update(jobId=v['id'],requestStartEpoch=t0,requestEndEpoch=t1)
                    results.append((name,t0,t1,v))
                except Exception as exc:
                    d['teams'][name]['submitError']=str(exc)[:500]
                    errors.append(name)
                save(d)
                print('SUBMISSION',name,'accepted' if name not in errors else 'failed',flush=True)
        if errors:raise RuntimeError(f'{len(errors)} submission requests failed. State records accepted IDs; reconcile before retrying: {errors}')
        assert len({d['teams'][n]['jobId'] for n in TEAMS})==50
        d['burstAcceptedAt']=timestamp();save(d)
        print('50_OFFICIAL_ACCEPTED request-start-skew=',max(x[1] for x in results)-min(x[1] for x in results),flush=True)
        gates(admin,original,mode='MAINTENANCE',registrationsEnabled=False,uploadsEnabled=False,sandboxEnabled=False,officialEnabled=False,tournamentEnabled=False,leaderboardVisible=True)
        deadline=time.monotonic()+args.max_minutes*60
        while time.monotonic()<deadline:
            jobs=api(admin,'GET','/api/admin/jobs?job_type=official&limit=500')['jobs']
            byid={j['id']:j for j in jobs};subset={name:byid.get(d['teams'][name]['jobId']) for name in TEAMS}
            if any(x is None for x in subset.values()):raise RuntimeError('Some accepted official jobs missing from admin jobs API')
            counts={s:sum(x['status']==s for x in subset.values()) for s in ['queued','running','completed','failed','timeout','cancelled']}
            d['observations'].append({'at':timestamp(),'counts':counts});save(d)
            print('ROUND1',timestamp(),counts,flush=True)
            if sum(counts[s] for s in TERMINAL)==50:break
            time.sleep(15)
        else:raise TimeoutError('Round 1 timeout')
        assert counts['completed']==50,f'Not all 50 jobs completed: {counts}'
        replays=set()
        for name in TEAMS:
            jid=d['teams'][name]['jobId'];job=api(admin,'GET',f'/api/admin/jobs/{jid}');result=job['result'];games=result['matchResults']
            assert job['status']=='completed' and result['status']=='complete' and len(games)==result['games']==6
            for game in games:
                rid=game['replayId'];assert rid not in replays;replays.add(rid)
                analytics=api(admin,'GET',f'/replays/{rid}/analytics');assert analytics['steps']>0
                assert api(admin,'GET',f'/replays/{rid}/frame/0')
                assert api(admin,'GET',f'/replays/{rid}/frame/{analytics["steps"]-1}')
            d['teams'][name].update(status='completed',rating=result['rating'],games=6,worker=job.get('worker'),queueWaitSeconds=job.get('queueWaitSeconds'),runtimeSeconds=job.get('runtimeSeconds'),attempts=job.get('attempts'))
            save(d)
        assert len(replays)==300
        standings=api(admin,'GET','/api/admin/competition/standings')['entries']
        assert len(standings)==50 and {x['team'] for x in standings}==set(TEAMS)
        d['round1']={'completedAt':timestamp(),'jobs':50,'games':300,'replays':300,'standings':standings};save(d)
        print('ROUND1_SUCCESS 50 jobs 300 real games 300 replay/frame/analytics verifications',flush=True)
        # Finish round 2 using the reviewed 30-team harness's existing bracket workflow (Claude adaptation required).
        if args.round2:
            phase=api(admin,'POST','/api/admin/competition/close-qualification',json={'confirmation':'CLOSE QUALIFICATION'})
            if phase['phase']=='QUALIFICATION_CLOSING':
                final=api(admin,'POST','/api/admin/competition/finalize',json={'confirmation':'FINALIZE QUALIFICATION'})
                assert len(final['qualifiers'])==16
            preview=api(admin,'GET','/api/admin/competition/bracket-preview')
            assert preview['capacity']==16 and preview['byes']==0
            lock=api(admin,'POST','/api/admin/competition/lock-bracket',json={'confirmation':'LOCK BRACKET'})
            assert lock['qualifiers']==16
            gates(admin,original,mode='TOURNAMENT',registrationsEnabled=False,uploadsEnabled=False,sandboxEnabled=False,officialEnabled=False,tournamentEnabled=True,leaderboardVisible=True)
            started=api(admin,'POST','/api/admin/tournament/start',json={'confirmation':'START TOURNAMENT'})
            d['round2JobId']=started['job']['id'];save(d)
            deadline=time.monotonic()+args.max_minutes*60
            while time.monotonic()<deadline:
                comp=api(admin,'GET','/api/admin/competition');tour=api(admin,'GET','/api/admin/tournament')
                print('ROUND2',timestamp(),comp['phase'],tour['status'],flush=True)
                if comp['phase']=='TOURNAMENT_COMPLETED':break
                if tour['status']=='error':raise RuntimeError(f'Tournament error: {tour.get("error")}')
                time.sleep(15)
            else:raise TimeoutError('Round 2 timeout')
            games=api(admin,'GET','/api/admin/tournament/games')['games'];assert len(games)>=30
            assert len({g['replayId'] for g in games})==len(games)
            for game in games:
                analytics=api(admin,'GET',f'/replays/{game["replayId"]}/analytics');assert analytics['steps']>0
            matches=tour.get('allMatches',[])
            champion=tour.get('champion')
            champion_name=champion.get('username') if isinstance(champion,dict) else champion
            assert len(matches)==15 and champion_name in {x['team'] for x in final['qualifiers']}
            assert next(x for x in matches if x['round']==4)['winner']==champion_name
            d['round2']={'completedAt':timestamp(),'games':len(games),'champion':champion_name,'matches':matches};save(d)
            print('ROUND2_COMPLETED',d['round2']['champion'],flush=True)
    finally:
        try:gates(admin,original,mode='MAINTENANCE',registrationsEnabled=False,uploadsEnabled=False,sandboxEnabled=False,officialEnabled=False,tournamentEnabled=False,leaderboardVisible=False)
        except Exception as e:print('WARNING: RESTORE GATES FAILED:',str(e),file=sys.stderr)
        d['finishedAt']=timestamp();save(d)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--round2',action='store_true');p.add_argument('--hold-before-burst',action='store_true');p.add_argument('--max-minutes',type=int,default=90)
    a=p.parse_args()
    if not a.execute:
        ensure_sources();print('DRY PREFLIGHT PASSED: 50 distinct source files. Add --execute to mutate staging.');sys.exit(0)
    run(a)
