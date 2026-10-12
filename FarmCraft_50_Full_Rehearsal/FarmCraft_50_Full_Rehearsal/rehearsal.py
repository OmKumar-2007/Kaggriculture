#!/usr/bin/env python3
"""FarmCraft 50-team HTTP end-to-end rehearsal.

Uses the *actual* registered participant sessions and admin APIs. Do not run
on the event deployment until the organizer approves the rehearsal window.
No phase-transition or data deletion endpoints are invoked by this script.
"""
from __future__ import annotations
import argparse,csv,datetime,getpass,hashlib,json,os,statistics,sys,time
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlparse,urlencode
from urllib.request import HTTPCookieProcessor,Request,build_opener
from uuid import uuid4
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'runtime'; RUNTIME.mkdir(exist_ok=True)
STATE_FILE=RUNTIME/'state.json'
LIVE={'neural-coliseum-api.onrender.com','neural-coliseum.onrender.com'}
DONE={'completed','failed','timeout','cancelled'}
PROTECTED_TEAM='temp'

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.pending')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    tmp.replace(path)
def load_json(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else (default if default is not None else {})
def rows():
    with (ROOT/'teams.csv').open(encoding='utf-8',newline='') as f: out=list(csv.DictReader(f))
    if len(out)!=50 or len({r['team'].lower() for r in out})!=50 or any(r['team'].lower()=='temp' for r in out):
        raise RuntimeError('Expected exactly 50 unique test teams, never temp')
    return out

def check_target(args,mutate=False):
    url=args.base_url.rstrip('/')
    u=urlparse(url)
    if u.scheme not in ('https','http') or not u.hostname or u.path not in ('','/') or u.query or u.username or u.password or u.fragment:
        raise RuntimeError('Use an API origin only, e.g. https://neural-coliseum-api.onrender.com')
    host=u.hostname.lower()
    if host in LIVE:
        if u.scheme!='https' or (mutate and not args.approve_live):
            raise RuntimeError('LIVE CHANGES BLOCKED: requires HTTPS and --approve-live. Obtain organizer permission first.')
    elif host not in ('localhost','127.0.0.1','::1'):
        if u.scheme!='https' or not args.staging_host or host!=args.staging_host.lower():
            raise RuntimeError('Remote nonproduction requires --staging-host EXACT_HOST and HTTPS')
    state=load_json(STATE_FILE)
    if state.get('target') and state['target']!=url:
        raise RuntimeError(f"Saved team sessions belong to {state['target']}; never reuse on {url}. Use an isolated kit copy.")
    return url

def init_state(base):
    data=load_json(STATE_FILE,{'target':base,'createdAt':now(),'teams':{},'phases':{},'errors':[]})
    if data.get('target')!=base:raise RuntimeError('Target differs from saved state')
    data.setdefault('teams',{});data.setdefault('errors',[]);data.setdefault('phases',{})
    for r in rows():data['teams'].setdefault(r['team'],{'family':r['family'],'sha256':r['sha256'],'sandbox':{},'analytics':{}})
    atomic_json(STATE_FILE,data)
    return data

def event(kind,team='',details=None):
    with (RUNTIME/'events.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'at':now(),'kind':kind,'team':team,'details':details or {}},default=str)+'\n')

def error(data,phase,team,exc):
    msg=str(exc)[:350]
    rec={'at':now(),'phase':phase,'team':team,'error':msg}
    data.setdefault('errors',[]).append(rec)
    event('failure',team,rec)
    print(f'  ERROR {team}: {msg}',flush=True)

def request(opener,base,method,path,body=None,headers=None,timeout=35,retry_read=True):
    raw=None
    if body is not None:
        if isinstance(body,dict):
            raw=json.dumps(body).encode('utf-8');headers={'Content-Type':'application/json',**(headers or {})}
        else:raw=body
    req=Request(base+path,data=raw,method=method,headers={'Accept':'application/json','User-Agent':'FarmCraft-Rehearsal50/1.0',**(headers or {})})
    last=None
    for attempt in range(4 if retry_read and method=='GET' else 1):
        started=time.perf_counter()
        try:
            with opener.open(req,timeout=timeout) as response:
                code=response.status;content=response.read(12_000_000)
        except HTTPError as exc:
            code=exc.code;content=exc.read(2_000)
        except (TimeoutError,URLError,OSError) as exc:
            if method=='GET' and attempt<3:
                time.sleep(min(6,2**attempt));continue
            raise RuntimeError(f'{method} {path} network issue: {exc}') from exc
        latency=round((time.perf_counter()-started)*1000,1)
        if code in (502,503,504) and method=='GET' and attempt<3:
            time.sleep(min(6,2**attempt));continue
        try:obj=json.loads(content.decode('utf-8'))
        except (ValueError,UnicodeDecodeError):obj={'detail':content.decode('utf-8',errors='replace')[:300]}
        if code>=400:
            detail=obj.get('detail',obj) if isinstance(obj,dict) else obj
            return code,{'detail':str(detail)[:300]},latency
        return code,obj,latency
    raise RuntimeError(f'{method} {path} repeatedly failed')

def must(code,expected,body,operation):
    if code!=expected:raise RuntimeError(f'{operation}: HTTP {code} {body.get("detail",body) if isinstance(body,dict) else str(body)[:200]}')
    return body

def opener_for(team):
    path=RUNTIME/'sessions'/f'{team}.cookies.txt';path.parent.mkdir(parents=True,exist_ok=True)
    jar=MozillaCookieJar(str(path))
    if path.exists():jar.load(ignore_discard=True,ignore_expires=True)
    return build_opener(HTTPCookieProcessor(jar)),jar

def session(team,base,create=False):
    assert team!=PROTECTED_TEAM and team.startswith('FC26_R50_')
    opener,jar=opener_for(team)
    path=RUNTIME/'sessions'/f'{team}.cookies.txt'
    if path.exists():
        code,payload,_=request(opener,base,'GET','/api/participants/session')
        if code==200 and payload.get('team','').casefold()==team.casefold():
            return opener,payload,'restored'
    if not create:raise RuntimeError(f'{team}: saved account session missing/expired. Never auto-register existing team; use organizer recovery.')
    code,payload,_=request(opener,base,'POST','/api/participants/session',{'team':team},retry_read=False)
    must(code,200,payload,'register')
    if payload.get('team','').casefold()!=team.casefold() or not payload.get('csrfToken'):
        raise RuntimeError('Server returned mismatched team or missing CSRF')
    jar.save(ignore_discard=True,ignore_expires=True)
    try:os.chmod(path,0o600)
    except OSError:pass
    return opener,payload,'created'

def upload_body(team,source):
    boundary='QA50_'+uuid4().hex
    payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="username"\r\n\r\n{team}\r\n'
             f'--{boundary}\r\nContent-Disposition: form-data; name="agent"; filename="agent.py"\r\nContent-Type: text/x-python\r\n\r\n').encode()+source+f'\r\n--{boundary}--\r\n'.encode()
    return payload,{'Content-Type':f'multipart/form-data; boundary={boundary}'}

def admin(base):
    op=build_opener(HTTPCookieProcessor())
    password=os.environ.get('FARMCRAFT_ADMIN_PASSWORD') or getpass.getpass('Organizer password (not saved): ')
    code,payload,_=request(op,base,'POST','/api/admin/login',{'password':password},retry_read=False)
    must(code,200,payload,'organizer authentication')
    return op,payload['csrfToken']

def admin_get(op,base,path):
    code,payload,_=request(op,base,'GET','/api/admin'+path)
    return must(code,200,payload,'admin '+path)

def preflight(args,base,data):
    op,csrf=admin(base)
    refs=admin_get(op,base,'/reference-bots').get('bots',[])
    teams=admin_get(op,base,'/contestants').get('contestants',[])
    cfg=admin_get(op,base,'/competition')
    metrics=admin_get(op,base,'/metrics')
    active=[x for x in refs if x.get('selected') and x.get('enabled') and not x.get('archived')]
    protected=[x for x in teams if x.get('team','').casefold()==PROTECTED_TEAM]
    snap={'at':now(),'target':base,'protectedTeamExists':bool(protected),
          'protectedTeam':[{k:x.get(k) for k in ('teamId','team','submissionCount','latestVersion')} for x in protected],
          'references':[{k:r.get(k) for k in ('id','familyId','family_id','version','displayName','display_name','sourceSha256','source_sha256','selected','enabled','archived')} for r in refs],
          'selectedReferenceCount':len(active),'competitionPhase':cfg.get('phase'),
          'competitionSettings':cfg.get('settings'), 'registeredTeams':len(teams),
          'workerSummary':metrics.get('workers'), 'health':metrics.get('health')}
    atomic_json(RUNTIME/'preflight.json',snap)
    print('Protected team temp:',bool(protected),' | reference bot versions:',len(refs),' | active selected:',len(active), '| phase:',cfg.get('phase'))
    print('Current real registered:',metrics.get('contestants'),' | workers:',(metrics.get('workers') or {}).get('total'))
    if not protected or len(refs)<5:
        raise RuntimeError('Preservation gate FAILED: expected personal team temp and at least five existing reference-bot records. Do NOT mutate.')
    if len(active)!=5:print('WARNING: Round 1 is expected to use five selected reference bots; select them in Admin before Round 1.')
    data['preflight']=snap;atomic_json(STATE_FILE,data)
    print('Saved reference and temp metadata snapshot:',RUNTIME/'preflight.json')

def require_preflight(data,base):
    snap=data.get('preflight',{})
    if snap.get('target')!=base or not snap.get('protectedTeamExists') or len(snap.get('references',[]))<5:
        raise RuntimeError('Run preflight first; verify protected temp and all five selected reference bots.')

def cmd_provision(args,base,data):
    require_preflight(data,base)
    quality=load_json(RUNTIME/'benchmark_results.json')
    validation=load_json(RUNTIME/'static_validation.json')
    valid_hashes={row['team']:row['sha256'] for row in rows()}
    passed=(validation.get('valid')==50 and len(quality.get('results',[]))==50
            and quality.get('benchmark')=='starter_crop'
            and all(row.get('passed') and row.get('sourceSha256')==valid_hashes.get(row.get('team')) for row in quality['results'])
            and {row['team'] for row in quality['results']}=={row['team'] for row in rows()})
    if not passed and not args.permit_unbenchmarked:
        raise RuntimeError('50-bot benchmark quality gate missing or failed. Run validate_agents.py and full benchmark_bots.py, improve weak bots, or explicitly --permit-unbenchmarked (not recommended).')
    if not passed:print('WARNING: 50 competitive agents have NOT passed a full real-game benchmark. Recording override.')
    data['qualityGatePassed']=bool(passed)
    atomic_json(STATE_FILE,data)
    for index,r in enumerate(rows(),1):
        team=r['team'];s=data['teams'][team]
        if s.get('upload')=='valid':continue
        try:
            op,identity,status=session(team,base,create=True)
            s['session']=status
            code,summary,_=request(op,base,'GET','/botlab/'+quote(team))
            must(code,200,summary,'Bot Lab summary')
            current=summary.get('currentSubmission')
            if current:
                # Existing uploaded bot may not match the source from this package.
                if not s.get('submissionId'):
                    raise RuntimeError('Team already has a submission but no local verified hash. Refusing to overwrite; inspect manually.')
                if s['submissionId']!=current.get('id'):
                    raise RuntimeError('Server submission changed. Refusing to overwrite.')
                s['upload']='valid';atomic_json(STATE_FILE,data);continue
            source=(ROOT/r['bot_file']).read_bytes()
            if hashlib.sha256(source).hexdigest()!=r['sha256']:raise RuntimeError('Local bot source hash mismatch')
            payload,headers=upload_body(team,source)
            code,uploaded,ms=request(op,base,'POST','/botlab/upload',payload,
                headers={**headers,'X-Participant-CSRF':identity['csrfToken']},timeout=50,retry_read=False)
            must(code,200,uploaded,'bot upload')
            validation=uploaded.get('validation',{})
            if not validation.get('valid'):raise RuntimeError('Invalid upload: '+str(validation.get('errors')))
            s.update(upload='valid',submissionId=(uploaded.get('submission') or {}).get('id'),uploadMs=ms)
            event('upload',team,{'status':'valid','submissionId':s['submissionId'],'ms':ms})
            print(f'[{index:02d}/50] {team}: uploaded v1',flush=True)
        except Exception as e:error(data,'provision',team,e)
        atomic_json(STATE_FILE,data)
        if args.delay:time.sleep(args.delay)
    success=sum(data['teams'][r['team']].get('upload')=='valid' for r in rows())
    print(f'PROVISION: {success}/50 valid uploads (any errors recorded in state.json).')
    if success<len(rows()):sys.exit(2)

def latest_jobs(op,base,team):
    code,payload,_=request(op,base,'GET','/teams/'+quote(team)+'/jobs?limit=100')
    must(code,200,payload,'team jobs')
    return payload if isinstance(payload,list) else (payload.get('jobs') or [])

def cmd_sandbox(args,base,data):
    require_preflight(data,base)
    wave=str(args.wave)
    if args.wave==2:
        missing=[r['team'] for r in rows() if data['teams'][r['team']]['sandbox'].get('1',{}).get('status')!='completed' or
            data['teams'][r['team']]['sandbox'].get('1',{}).get('contestantStatus')=='contestant_error']
        if missing:raise RuntimeError(f'Wave 1 incomplete for {len(missing)} teams. Monitor/fix before wave 2.')
    chosen=['balanced','animal']
    for index,r in enumerate(rows(),1):
        team=r['team'];s=data['teams'][team]
        existing=s['sandbox'].get(wave)
        if existing and (existing.get('id') or existing.get('status')=='ambiguous'):
            continue
        if s.get('upload')!='valid':error(data,'sandbox'+wave,team,'Bot upload not verified');continue
        try:
            op,identity,_=session(team,base,create=False)
            code,summary,_=request(op,base,'GET','/botlab/'+quote(team))
            must(code,200,summary,'pre-sandbox summary')
            current=summary.get('currentSubmission') or {}
            if current.get('id')!=s.get('submissionId'):
                raise RuntimeError('Submission version changed; canceling sandbox')
            opponent=chosen[args.wave-1]
            seed=20261101+(args.wave-1)*1000+index
            body=urlencode({'seed':seed,'opponent':opponent}).encode('ascii')
            code,job,latency=request(op,base,'POST','/botlab/'+quote(team)+'/sandbox',body,
                headers={'Content-Type':'application/x-www-form-urlencoded','X-Participant-CSRF':identity['csrfToken']},timeout=40,retry_read=False)
            if code==202 and isinstance(job,dict) and job.get('id'):
                s['sandbox'][wave]={'id':job['id'],'status':'queued','opponent':opponent,'seed':seed,'submitMs':latency,'at':now()}
                event('sandbox_queued',team,{'wave':wave,'id':job['id'],'ms':latency})
                print(f'[{index:02d}/50] sandbox {wave}: {team} queued {job["id"]}',flush=True)
            else:
                # IMPORTANT: ambiguous 502 may have accepted POST. Never blind-retry.
                s['sandbox'][wave]={'status':'ambiguous','http':code,'opponent':opponent,'seed':seed,'at':now()}
                raise RuntimeError(f'Sandbox POST HTTP {code} (unknown acceptance): {job.get("detail",str(job)[:120])}')
        except Exception as e:error(data,'sandbox'+wave,team,e)
        atomic_json(STATE_FILE,data)
        if args.delay:time.sleep(args.delay)
    print('Queued or resumed wave',wave,'; run monitor --phase sandbox'+wave)

def cmd_reconcile(args,base,data):
    """Resolve ambiguous 502 POSTs through read-only team job history; never double submit."""
    require_preflight(data,base)
    count=0
    for r in rows():
        team=r['team'];s=data['teams'][team]
        possibilities=[('sandbox',str(w),s['sandbox'].get(str(w),{})) for w in (1,2)]
        possibilities.append(('official','official',s.get('official',{})))
        if not any(j.get('status')=='ambiguous' for _,_,j in possibilities):continue
        try:
            op,_,_=session(team,base)
            history=latest_jobs(op,base,team)
            for kind,w,j in possibilities:
                if j.get('status')!='ambiguous':continue
                matches=[x for x in history if x.get('type')==kind and
                      (kind=='official' or (str(x.get('seed'))==str(j.get('seed')) and x.get('opponent')==j.get('opponent')))]
                if len(matches)==1 and matches[0].get('id'):
                    j['id']=matches[0]['id'];j['status']=matches[0].get('status','queued')
                    event('ambiguous_post_reconciled',team,{'kind':kind,'jobId':j['id']})
                    count+=1
                    print(team,kind,'recovered job',j['id'])
                else:
                    event('manual_reconciliation_needed',team,{'kind':kind,'matches':len(matches)})
                    print(team,kind,'needs manual reconciliation; matching jobs',len(matches))
        except Exception as exc:error(data,'reconcile',team,exc)
        atomic_json(STATE_FILE,data)
    print('Reconciled ambiguous submissions:',count)

def cmd_official(args,base,data):
    require_preflight(data,base)
    op,csrf=admin(base)
    comp=admin_get(op,base,'/competition')
    if comp.get('phase')!='QUALIFICATION_OPEN':raise RuntimeError('Organizer must START Round 1 from admin UI first (QUALIFICATION_OPEN).')
    refs=admin_get(op,base,'/reference-bots').get('bots',[])
    if sum(bool(x.get('selected') and x.get('enabled') and not x.get('archived')) for x in refs)!=5:
        raise RuntimeError('Expected exactly 5 selected active reference bots before official qualification.')
    prev=data['preflight'].get('references',[])
    prev_map={str(x['id']):x for x in prev}
    if {str(x.get('id')) for x in refs}!={str(x.get('id')) for x in prev}:
        raise RuntimeError('Reference bot version list changed since initial preflight. Inspect and re-run preflight; no official submissions sent.')
    for r in refs:
        a=prev_map.get(str(r.get('id')))
        if a and (a.get('sourceSha256') or a.get('source_sha256')) != (r.get('sourceSha256') or r.get('source_sha256')):
            raise RuntimeError('Reference source SHA changed; ABORT')
    missing=[r['team'] for r in rows() if any(data['teams'][r['team']]['sandbox'].get(str(w),{}).get('status')!='completed' or
          data['teams'][r['team']]['sandbox'].get(str(w),{}).get('contestantStatus')=='contestant_error' or
          not data['teams'][r['team']]['analytics'].get(str(w),{}).get('ok') for w in (1,2))]
    if missing:raise RuntimeError(f'Official submission blocked: {len(missing)} QA teams lack completed sandbox + analytics checks.')
    if not data.get('qualityGatePassed') and not args.permit_unbenchmarked:
        raise RuntimeError('Quality gate was bypassed during upload; explicit --permit-unbenchmarked required if proceeding.')
    for i,r in enumerate(rows(),1):
        team=r['team'];s=data['teams'][team]
        if s.get('official',{}).get('id') or s.get('official',{}).get('status')=='ambiguous':continue
        try:
            opener,identity,_=session(team,base,create=False)
            code,payload,ms=request(opener,base,'POST','/botlab/'+quote(team)+'/submit',b'',
                headers={'X-Participant-CSRF':identity['csrfToken']},timeout=60,retry_read=False)
            if code==202 and payload.get('id'):
                s['official']={'id':payload['id'],'status':'queued','at':now(),'submitMs':ms}
                event('official_queued',team,{'id':payload['id'],'ms':ms})
                print(f'[{i:02d}/50] official: {team} queued',flush=True)
            else:
                s['official']={'status':'ambiguous','http':code,'at':now()}
                raise RuntimeError(f'Official HTTP {code}. Do not retry one-attempt submissions blindly: {payload.get("detail",payload)}')
        except Exception as e:error(data,'official',team,e)
        atomic_json(STATE_FILE,data)
        time.sleep(args.delay)
    print('Official requests sent. Do not re-run ambiguous official submissions without admin reconciliation.')

def job_records(data,phase):
    if phase=='round1':
        return [(r['team'],data['teams'][r['team']].get('official',{})) for r in rows()]
    wave=phase[-1]
    return [(r['team'],data['teams'][r['team']]['sandbox'].get(wave,{})) for r in rows()]

def cmd_monitor(args,base,data):
    require_preflight(data,base)
    pending=job_records(data,args.phase)
    if any(not j.get('id') for t,j in pending):
        raise RuntimeError('Not all 50 jobs have confirmed IDs; inspect state.json and reconcile failures before monitoring.')
    deadline=time.monotonic()+args.max_minutes*60
    while True:
        counted={}
        for team,j in pending:
            if j.get('status') in DONE:
                counted[j['status']]=counted.get(j['status'],0)+1;continue
            try:
                op,session_data,_=session(team,base)
                code,resp,ms=request(op,base,'GET','/jobs/'+j['id'],timeout=30)
                must(code,200,resp,'job status')
                # Keep QA session alive for lengthy official evaluations; the
                # backend refreshes session TTL on authenticated heartbeats.
                hcode,hpayload,_=request(op,base,'POST','/api/participants/heartbeat',
                    {'idle':True,'latencyMs':None},headers={'X-Participant-CSRF':session_data['csrfToken']},
                    timeout=25,retry_read=False)
                if hcode!=200:
                    event('heartbeat_warning',team,{'phase':args.phase,'http':hcode})
                new_status=resp.get('status','unknown')
                if new_status!=j.get('status'):
                    event('job_status',team,{'phase':args.phase,'job':j['id'],'status':new_status})
                    print(team,j['id'][:8],new_status,flush=True)
                j['status']=new_status
                j['lastCheck']=now()
                j['worker']=resp.get('worker') or resp.get('workerId') or resp.get('worker_id')
                j['result']=resp.get('result')
                if new_status in DONE:
                    j['error']=resp.get('error')
                    j['startedAt']=resp.get('startedAt') or resp.get('started_at')
                    j['completedAt']=resp.get('completedAt') or resp.get('completed_at')
                    result=resp.get('result') or {}
                    j['replayId']=(result.get('replayId') if isinstance(result,dict) else None)
                    j['botScore']=(result.get('botFinalMoney') if isinstance(result,dict) else None)
                    j['contestantStatus']=(result.get('status') if isinstance(result,dict) else None)
                    if j['contestantStatus']=='contestant_error':
                        error(data,args.phase,team,'Evaluator reported contestant_error despite completed infrastructure job')
                counted[new_status]=counted.get(new_status,0)+1
            except Exception as exc:
                event('monitor_transient',team,{'phase':args.phase,'error':str(exc)[:120]})
                counted['poll_error']=counted.get('poll_error',0)+1
            atomic_json(STATE_FILE,data)
            time.sleep(0.12)
        print(now(),args.phase,counted,flush=True)
        if sum(j.get('status') in DONE for _,j in pending)==len(pending):break
        if time.monotonic()>deadline:
            print('Monitor time limit; jobs may still be running. Resumable.');break
        time.sleep(args.poll_seconds)
    stats={x:sum(j.get('status')==x for _,j in pending) for x in sorted(DONE)}
    print(args.phase,'terminal:',stats)
    if stats['completed']<len(pending):
        print('Not all 50 jobs successfully completed; check report, diagnose and rerun/resume safely.')

def cmd_analytics(args,base,data):
    require_preflight(data,base)
    wave=str(args.wave)
    for i,r in enumerate(rows(),1):
        team=r['team'];s=data['teams'][team]
        j=s['sandbox'].get(wave,{})
        if j.get('status')!='completed':continue
        if s['analytics'].get(wave,{}).get('ok'):continue
        rid=j.get('replayId') or (j.get('result') or {}).get('replayId')
        if not rid:error(data,'analytics'+wave,team,'Completed job has no replayId');continue
        try:
            op,_,_=session(team,base)
            code,an,ms=request(op,base,'GET',f'/replays/{rid}/analytics',timeout=80)
            must(code,200,an,'analytics')
            code,bundle,bms=request(op,base,'GET',f'/replays/{rid}/playback',timeout=80)
            must(code,200,bundle,'playback')
            steps=bundle.get('totalSteps');players=bundle.get('players') or []
            if not isinstance(steps,int) or steps<10 or not players or len(players[0])!=steps:
                raise RuntimeError('Playback bundle shape invalid')
            code,frame,fms=request(op,base,'GET',f'/replays/{rid}/frame/0',timeout=60)
            must(code,200,frame,'first frame')
            if frame.get('step')!=0 or not (frame.get('farm') or {}).get('tiles'):
                raise RuntimeError('First replay frame invalid')
            if an.get('steps')!=steps:raise RuntimeError('Analytics length does not match replay')
            s['analytics'][wave]={'ok':True,'steps':steps,'cash':an.get('finalCash'),'requestMs':ms,'bundleMs':bms,
                'frameMs':fms,'replayId':rid,'at':now()}
            event('analytics_verified',team,{'wave':wave,'replayId':rid,'steps':steps,'ms':bms})
            print(f'[{i:02d}/50] {team}: analytics + {steps}-frame replay verified',flush=True)
        except Exception as exc:error(data,'analytics'+wave,team,exc)
        atomic_json(STATE_FILE,data)
        time.sleep(args.delay)
    good=sum(data['teams'][r['team']]['analytics'].get(wave,{}).get('ok') for r in rows())
    print(f'Wave {wave} analytics/replay API verified: {good}/50 (browser UI separate)')

def cmd_heartbeat(args,base,data):
    require_preflight(data,base)
    if args.duration_minutes<=0 or args.duration_minutes>720:raise RuntimeError('Heartbeat duration must be 1..720 minutes')
    stop=time.monotonic()+args.duration_minutes*60
    while time.monotonic()<stop:
        ok=0
        for r in rows():
            team=r['team']
            try:
                op,identity,_=session(team,base)
                code,reply,_=request(op,base,'POST','/api/participants/heartbeat',{'idle':False,'latencyMs':None},
                    headers={'X-Participant-CSRF':identity['csrfToken']},retry_read=False)
                ok+=(code==200)
            except Exception as exc:event('heartbeat_error',team,{'error':str(exc)[:150]})
            time.sleep(0.08)
        print('Admin Teams & Sessions online heartbeat:',ok,'/50',flush=True)
        time.sleep(min(12,max(0,stop-time.monotonic())))

def cmd_tournament(args,base,data):
    require_preflight(data,base)
    op,csrf=admin(base)
    phase=admin_get(op,base,'/competition').get('phase')
    if phase not in ('QUALIFICATION_FINALIZED','TOURNAMENT_RUNNING','TOURNAMENT_COMPLETED','TOURNAMENT_FINISHED'):
        raise RuntimeError(f'Admin must finalize Round 1 and launch Round 2; current phase={phase}')
    started=time.monotonic();seen=''
    while time.monotonic()-started<args.max_minutes*60:
        status=admin_get(op,base,'/tournament')
        comp=admin_get(op,base,'/competition')
        snap={'at':now(),'competitionPhase':comp.get('phase'),'status':status}
        atomic_json(RUNTIME/'tournament_latest.json',snap)
        signature=json.dumps({k:status.get(k) for k in ('status','currentRound','champion','playersCount')},sort_keys=True)
        if signature!=seen:print('Tournament status:',signature,flush=True);seen=signature
        if (status.get('status') in ('completed','finished','done') or status.get('champion')):
            print('Tournament reported terminal result. Verify winner and all matches in Admin.')
            break
        if status.get('status')=='error':
            event('tournament_halted','',{'status':status.get('error','unknown')});break
        time.sleep(args.poll_seconds)
    atomic_json(RUNTIME/'tournament_latest.json',{'at':now(),'status':status})
    try:
        atomic_json(RUNTIME/'tournament_games.json',admin_get(op,base,'/tournament/games'))
        atomic_json(RUNTIME/'qualification_standings.json',admin_get(op,base,'/competition/standings'))
    except Exception as exc:event('admin_report_read_error','',{'error':str(exc)[:150]})

def cmd_snapshot(args,base,data):
    op,csrf=admin(base)
    for filename,path in [('admin_metrics.json','/metrics'),('admin_contestants.json','/contestants'),
                          ('admin_jobs.json','/jobs?limit=500'),('admin_competition.json','/competition'),
                          ('admin_standings.json','/competition/standings'),('admin_tournament.json','/tournament'),
                          ('admin_reference_bots.json','/reference-bots'),('admin_pipeline.json','/pipeline')]:
        try:atomic_json(RUNTIME/filename,admin_get(op,base,path))
        except Exception as exc:event('admin_snapshot_error','',{'endpoint':path,'error':str(exc)[:170]})
    print('Saved admin monitoring snapshots to',RUNTIME)

def cmd_report(args,base,data):
    report=ROOT/'reports';report.mkdir(exist_ok=True)
    records=[];jobs=[]
    for row in rows():
        s=data['teams'][row['team']]
        records.append({'team':row['team'],'family':row['family'],'source_sha256':row['sha256'],
           'upload':s.get('upload','none'),
           **{f'sandbox{w}_status':s['sandbox'].get(str(w),{}).get('status','none') for w in (1,2)},
           **{f'sandbox{w}_score':s['sandbox'].get(str(w),{}).get('botScore','') for w in (1,2)},
           **{f'analytics{w}':bool(s['analytics'].get(str(w),{}).get('ok')) for w in (1,2)},
           'official_status':s.get('official',{}).get('status','none'),
           'official_id':s.get('official',{}).get('id','')})
        for wave in ('1','2'):
            j=s['sandbox'].get(wave,{})
            if j:jobs.append({'team':row['team'],'phase':'sandbox'+wave,**j})
        if s.get('official'):jobs.append({'team':row['team'],'phase':'round1',**s['official']})
    for path,lines in [('teams.csv',records),('jobs.csv',jobs),('failures.csv',data.get('errors',[]))]:
        if lines:
            keys=list(dict.fromkeys(k for row in lines for k in row.keys()))
            with (report/path).open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader()
                for row in lines:
                    w.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    snapshots=[x for x in (RUNTIME/'admin_metrics.json', RUNTIME/'tournament_latest.json', RUNTIME/'qualification_standings.json') if x.exists()]
    terminal=sum(j.get('status')=='completed' for j in jobs)
    state_counts={a:sum(v.get('upload')=='valid' for v in data['teams'].values()) for a in ['uploaded']}
    status='NOT READY' if data.get('errors') or terminal<100 else 'PARTIAL VERIFIED (qualification/tournament not proven)'
    md=f'''# FarmCraft 50-Team Competition Rehearsal — Evidence Report

Generated: {now()}
Target: {base}
Protected participant: **temp**
Protected references: five selected source hashes in `runtime/preflight.json`.

## Measured completion

- Uploaded test bots: {state_counts['uploaded']}/50.
- Sandbox wave 1 completed: {sum(s['sandbox'].get('1',{}).get('status')=='completed' for s in data['teams'].values())}/50.
- Sandbox wave 2 completed: {sum(s['sandbox'].get('2',{}).get('status')=='completed' for s in data['teams'].values())}/50.
- Analytics and playback checks: {sum(sum(bool(s['analytics'].get(str(w),{}).get('ok')) for w in (1,2)) for s in data['teams'].values())}/100.
- Round 1 official jobs completed: {sum(s.get('official',{}).get('status')=='completed' for s in data['teams'].values())}/50.
- Failures and warnings logged: {len(data.get('errors',[]))}.
- Tournament latest snapshot present: {(RUNTIME/'tournament_latest.json').exists()}.

## Interpretation

Status: **{status}**. This is a test harness report, not proof of 50 strong bots or readiness until actual benchmark and game results are reviewed.
Real browser replay 10x verification requires `ui_replay_check.py`; API-only replay checks cannot prove UI interaction.
Live failure injection is intentionally prohibited.

## Evidence

- `teams.csv`: per-team progression.
- `jobs.csv`: queued/terminal jobs, scores and worker assignment.
- `failures.csv`: errors, including transient requests.
- `runtime/admin_*.json`: read-only admin dashboard snapshots (if captured).
- `runtime/tournament_latest.json`: bracket state (if captured).
- `runtime/qualification_standings.json`: qualification standings (if captured).
- `runtime/events.jsonl`: detailed event log.

## Required manual audit

Check the five reference bot hashes against the initial snapshot, confirm temp remains, inspect failed jobs in Render/VM logs,
review p95 latency and real evaluator games/minute, and inspect the Round 2 champion.
'''
    (report/'REPORT.md').write_text(md,encoding='utf-8')
    benchmark=load_json(RUNTIME/'benchmark_results.json')
    if benchmark:
        ranked=sorted(benchmark.get('results',[]),key=lambda x:(not x.get('passed'),-float(x.get('winRate',0))))
        intro='# Bot strength — actual public benchmark sample\n\n'
        intro+='Benchmark: '+str(benchmark.get('benchmark'))+'; do not infer tournament strength from two seeds.\n\n'
        intro+='| Team | Strategy | Win rate | Average money | Passed |\n|---|---|---:|---:|---|\n'
        intro+='\n'.join('| {team} | {family} | {winRate:.0%} | {meanMoney} | {passed} |'.format(**{**x,'meanMoney':x.get('meanMoney') or '-', 'winRate':x.get('winRate') or 0}) for x in ranked)
        (report/'BOT_PERFORMANCE.md').write_text(intro,encoding='utf-8')
    failures=data.get('errors',[])
    lines=['# Failures and corrections','',f'Recorded failure events: {len(failures)}.','',
      'This runner captures evidence but does not alter/deploy application source code.','',
      '| Time | Phase | Team | Reported error | Root cause | Code change | Retest |',
      '|---|---|---|---|---|---|---|']
    for f in failures:
        lines.append('| '+ ' | '.join(str(f.get(k,'')).replace('|','/').replace('\n',' ')[:140] for k in ('at','phase','team','error'))+' | Pending analysis | Not applied | Pending |')
    (report/'FIXES.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    metrics=load_json(RUNTIME/'admin_metrics.json')
    perf=['# Performance evidence', '', 'These metrics are snapshots, not validated sustained-load claims.', '',
      '- API p95 latency (admin snapshot): '+str((metrics.get('api') or {}).get('p95LatencyMs','not captured'))+' ms',
      '- Active evaluator registrations: '+str((metrics.get('workers') or {}).get('total','not captured')),
      '- Production queue status: '+json.dumps(metrics.get('queues',{})),
      '- Real evaluation throughput: not calculated without complete runtime/start timestamps',
      '', 'Investigate Render 502 incidents using Render service logs and timestamps in runtime/events.jsonl.']
    (report/'PERFORMANCE.md').write_text('\n'.join(perf)+'\n',encoding='utf-8')
    print('Generated reports:',report)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['preflight','provision','sandbox','monitor','analytics','official','heartbeat','tournament','snapshot','report','reconcile'])
    p.add_argument('--base-url',default='http://127.0.0.1:8000')
    p.add_argument('--approve-live',action='store_true',help='Explicitly permit production mutations; obtain organizer approval first')
    p.add_argument('--staging-host',default='')
    p.add_argument('--execute',action='store_true',help='Enable network writes; default is read-only dry-run for mutations')
    p.add_argument('--permit-unbenchmarked',action='store_true',help='Explicitly bypass full bot-quality benchmark; results may be weak (not recommended)')
    p.add_argument('--wave',type=int,choices=(1,2),default=1)
    p.add_argument('--phase',choices=('sandbox1','sandbox2','round1'),default='sandbox1')
    p.add_argument('--delay',type=float,default=1.0)
    p.add_argument('--poll-seconds',type=float,default=15.0)
    p.add_argument('--max-minutes',type=int,default=180)
    p.add_argument('--duration-minutes',type=int,default=5)
    args=p.parse_args()
    if args.delay<0.2 or not 3<=args.poll_seconds<=300 or not 1<=args.max_minutes<=720:
        p.error('delay>=0.2, poll seconds 3..300, max-minutes 1..720 required')
    mutate=args.action in ('provision','sandbox','official','heartbeat')
    base=check_target(args,mutate=mutate and args.execute)
    if mutate and not args.execute:
        print('DRY RUN: action',args.action,'target',base,'; add --execute and appropriate target approval to send requests')
        return 0
    data=init_state(base)
    cmd={'preflight':lambda:preflight(args,base,data),
       'provision':lambda:cmd_provision(args,base,data),
       'sandbox':lambda:cmd_sandbox(args,base,data),
       'monitor':lambda:cmd_monitor(args,base,data),
       'analytics':lambda:cmd_analytics(args,base,data),
       'official':lambda:cmd_official(args,base,data),
       'heartbeat':lambda:cmd_heartbeat(args,base,data),
       'tournament':lambda:cmd_tournament(args,base,data),
       'snapshot':lambda:cmd_snapshot(args,base,data),
       'report':lambda:cmd_report(args,base,data),
       'reconcile':lambda:cmd_reconcile(args,base,data)}
    cmd[args.action]()
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,HTTPError,URLError,KeyError,ValueError) as exc:
        print('STOP:',exc,file=sys.stderr);sys.exit(2)
