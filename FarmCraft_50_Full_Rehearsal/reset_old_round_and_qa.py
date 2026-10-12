#!/usr/bin/env python3
"""Reviewed, transactional reset of old qualification and exactly scoped QA20 cleanup.

Read-only PLAN by default. --execute requires matching saved SHA, verified pg_dump,
explicit human confirmation and repeat invariants. No reference or temp writes.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'runtime'
PLAN=RUNTIME/'reset_qa_plan.json'
QA={f'QA26_B2C9C5_{i:02d}' for i in range(1,21)}
PROTECTED='temp'

class Halt(Exception):pass

def stable(o):return json.dumps(o,sort_keys=True,separators=(',',':'),default=str)
def digest(o):return hashlib.sha256(stable(o).encode()).hexdigest()
def query(conn,sql,params=None):return [dict(x) for x in conn.execute(text(sql),params or {}).mappings().all()]
def scalar(conn,sql,params=None):return conn.execute(text(sql),params or {}).scalar()
def json_ready(rows):return json.loads(json.dumps(rows,default=str))
def phase_event(row):return row['phase'] if row else 'missing'

def read_snapshot(conn):
    phase=query(conn,'SELECT id,phase,started_at,reference_snapshot_json,evaluation_config_json,qualifier_roster_json,standings_json FROM competition_state WHERE id=1')
    if len(phase)!=1 or phase[0]['phase'] not in ('SETUP','QUALIFICATION_OPEN'):
        raise Halt('Only SETUP or approved leftover QUALIFICATION_OPEN can be reset. Found '+str(phase_event(phase[0] if phase else None)))
    cfg=query(conn,'SELECT id,mode,reference_count,registration_capacity,qualifier_count FROM event_config WHERE id=1')
    if len(cfg)!=1:raise Halt('event_config row 1 missing')
    refs=query(conn,'SELECT id,family_id,version,display_name,source_sha256,object_key,selected,enabled,archived,validation_status,test_status FROM reference_bots ORDER BY id')
    selected=[r for r in refs if r['selected'] and r['enabled'] and not r['archived']]
    if len(selected)!=5 or cfg[0]['reference_count']!=5:raise Halt(f'Expected 5 selected, enabled reference bots, found {len(selected)}')
    protected=query(conn,'SELECT id,username,session_version,blocked,suspended_reason FROM teams WHERE lower(username)=:name',{'name':PROTECTED})
    if len(protected)!=1:raise Halt('Protected team temp missing or ambiguous')
    pid=protected[0]['id']
    temp_sub=query(conn,'SELECT id,team_id,version,object_key,validation_status,official_score,is_active FROM submissions WHERE team_id=:id ORDER BY id',{'id':pid})
    ids=sorted(QA)
    teams=query(conn,'SELECT id,username FROM teams WHERE username = ANY(:names) ORDER BY username',{'names':ids})
    tids=[r['id'] for r in teams]
    subs=query(conn,'SELECT id,team_id,version,object_key FROM submissions WHERE team_id = ANY(:ids) ORDER BY id',{'ids':tids})
    sids=[r['id'] for r in subs]
    jobs=query(conn,'SELECT id,type,status,team_id,submission_id FROM simulation_jobs WHERE team_id = ANY(:ids) OR submission_id = ANY(:sids) ORDER BY id',{'ids':tids,'sids':sids})
    claims=query(conn,'SELECT id,team_id,job_id,submission_id,round_started_at FROM official_submission_claims WHERE team_id = ANY(:ids) OR submission_id = ANY(:sids) ORDER BY id',{'ids':tids,'sids':sids})
    if any(j['team_id'] is not None and j['team_id'] not in tids for j in jobs):
        raise Halt('A job associated with a QA submission belongs to another team. Refuse cross-team deletion.')
    if any(c['team_id'] not in tids for c in claims):
        raise Halt('An official claim associated with QA submission belongs to another team. Refuse cross-team deletion.')
    all_running=query(conn,"SELECT id,type,status,team_id FROM simulation_jobs WHERE status IN ('queued','running') ORDER BY id LIMIT 8")
    if all_running:raise Halt('Active jobs exist. Let them finish or cancel them via Admin first: '+str(all_running[:6]))
    tournament=query(conn,'SELECT id,state_json FROM tournament_state WHERE id=1')
    tournament_state=json.loads(tournament[0]['state_json']) if tournament else {}
    if tournament_state.get('status') in ('starting','round_running','next_round','final'):
        raise Halt('An active tournament state is present; refusing reset')
    tgames=int(scalar(conn,'SELECT count(*) FROM tournament_games') or 0)
    if tgames:raise Halt(f'{tgames} historical tournament_games exist. Requires explicit archived-game review before this tool can clear a competition; no deletion performed.')
    all_teams=int(scalar(conn,'SELECT count(*) FROM teams WHERE is_rehearsal IS FALSE') or 0)
    if all_teams-len(teams)+50>cfg[0]['registration_capacity']:
        raise Halt(f'Team capacity insufficient after scoped cleanup: {all_teams-len(teams)+50} needed, capacity {cfg[0]["registration_capacity"]}. Do not change event settings implicitly.')
    snapshot={
       'target':{'host':conn.engine.url.host,'database':conn.engine.url.database,'port':conn.engine.url.port},
       'competition':{'phase':phase[0]['phase'],'startedAt':str(phase[0]['started_at'])},
       'event':cfg[0],
       'protectedTeam':protected[0],
       'protectedSubmissions':temp_sub,
       'referenceBots':refs,
       'oldQATeams':teams,
       'oldQASubmissions':subs,
       'oldQAJobs':jobs,
       'oldQAOfficialClaims':claims,
       'tournamentStatus':tournament_state.get('status','missing'),
       'tournamentGames':tgames,
       'rehearsalTeamsUnrelated':int(scalar(conn,"SELECT count(*) FROM teams WHERE is_rehearsal IS TRUE") or 0),
       'otherTeamsPreserved':all_teams-len(teams),
    }
    # Ensure API preflight matches the DB; this protects against mistaken Neon connection URL.
    pre=RUNTIME/'preflight.json'
    if not pre.exists():raise Halt('Missing runtime/preflight.json from LIVE organizer preflight. Run Check from main launcher first.')
    expected=json.loads(pre.read_text('utf-8'))
    if expected.get('target')!='https://neural-coliseum-api.onrender.com':
        raise Halt('Preflight target does not match intended live API.')
    pt=expected.get('protectedTeam',[])
    if len(pt)!=1 or pt[0].get('teamId')!=pid or pt[0].get('submissionCount')!=len(temp_sub):
        raise Halt('Neon database does not match the protected temp identity in live API preflight.')
    api_refs={r['id']:(r['sourceSha256'],r['selected'],r['enabled'],r['archived']) for r in expected.get('references',[])}
    db_refs={r['id']:(r['source_sha256'],r['selected'],r['enabled'],r['archived']) for r in refs}
    if api_refs!=db_refs:raise Halt('Neon reference bot IDs/hashes/selection differ from live API preflight. Refuse.')
    if expected.get('competitionPhase')!=phase[0]['phase']:
        raise Halt('Neon competition phase differs from live API preflight. Refresh preflight.')
    return json_ready(snapshot)

RESET_TOURNAMENT={'status':'registration','message':'Registration is open. Waiting for players to join.',
   'playersCount':0,'maxPlayers':100,'registeredPlayers':[],'currentRound':0,'totalRoundsEstimate':0,
   'currentMatches':[],'roundsHistory':[],'byes':[],'eliminatedPlayers':[], 'allMatches':[],
   'champion':None,'finalScore':None,'error':None,'isLive':False,'selectedQualifiers':[]}

def run():
    p=argparse.ArgumentParser()
    p.add_argument('--execute',action='store_true')
    p.add_argument('--approve-hash',default='')
    p.add_argument('--backup-file',default='')
    p.add_argument('--confirmation',default='')
    args=p.parse_args()
    url=os.environ.get('DATABASE_URL','')
    if not url.startswith(('postgresql://','postgres://','postgresql+psycopg://')):raise Halt('DATABASE_URL must be a real Neon PostgreSQL URL')
    if url.startswith('postgres://'):url='postgresql+psycopg://'+url.removeprefix('postgres://')
    if url.startswith('postgresql://'):url='postgresql+psycopg://'+url.removeprefix('postgresql://')
    engine=create_engine(url,poolclass=NullPool,connect_args={'connect_timeout':15})
    if engine.dialect.name!='postgresql':raise Halt('Refuse non-PostgreSQL database')
    RUNTIME.mkdir(exist_ok=True)
    with engine.begin() as conn:
        # Same transactional lock as qualification phase transitions; freeze competing changes.
        conn.execute(text('SELECT pg_advisory_xact_lock(78426136)'))
        if args.execute:conn.execute(text('SELECT pg_advisory_xact_lock(78426135)'))
        snap=read_snapshot(conn)
        sha=digest(snap)
        if not args.execute:
            artifact={'planSha256':sha,'plannedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'preview':snap}
            PLAN.write_text(json.dumps(artifact,indent=2,ensure_ascii=False),encoding='utf-8')
            print('PLAN ONLY: no rows updated or deleted.')
            print(f'PostgreSQL: {snap["target"]["host"]} / {snap["target"]["database"]}')
            print(f'Phase: {snap["competition"]["phase"]};  protected: temp ({len(snap["protectedSubmissions"])} submissions) + {len(snap["referenceBots"])} reference versions')
            print(f'Old QA teams: {len(snap["oldQATeams"])}; submission IDs: {len(snap["oldQASubmissions"])}; jobs: {len(snap["oldQAJobs"])}; official claims: {len(snap["oldQAOfficialClaims"])}')
            for t in snap['oldQATeams']:print(f'  DELETE QA team only: {t["username"]} (id {t["id"]})')
            print('Other teams preserved:',snap['otherTeamsPreserved'],'(including temp); source/replay blobs left untouched')
            print('SHA256:',sha)
            print('Plan file:',PLAN)
            return
        if not PLAN.is_file():raise Halt('No reviewed plan available: run plan first')
        saved=json.loads(PLAN.read_text('utf-8'))
        if saved.get('planSha256')!=sha or digest(saved.get('preview',{}))!=sha or args.approve_hash!=sha:
            raise Halt('Exact deletion plan has changed; rerun read-only plan and review again')
        if args.confirmation!='RESET OLD QA ROUND ONLY':raise Halt('Explicit reset confirmation missing')
        b=Path(args.backup_file)
        if not b.is_file() or b.stat().st_size<10000:raise Halt('Missing/invalid verified pg_dump backup')
        if (RUNTIME/'backup_verified.json').is_file():
            verification=json.loads((RUNTIME/'backup_verified.json').read_text('utf-8-sig'))
        else:raise Halt('Missing backup verification marker from launcher')
        backup_sha=hashlib.sha256()
        with b.open('rb') as backup_stream:
            for chunk in iter(lambda:backup_stream.read(1024*1024),b''):backup_sha.update(chunk)
        if verification.get('sha256')!=backup_sha.hexdigest() or verification.get('sourceHost')!=snap['target']['host'] or verification.get('sourceDatabase')!=snap['target']['database']:
            raise Halt('Backup checksum/DB identity not verified')
        ids=[t['id'] for t in snap['oldQATeams']]
        sids=[s['id'] for s in snap['oldQASubmissions']]
        jids=[j['id'] for j in snap['oldQAJobs']]
        conn.execute(text('DELETE FROM official_submission_claims WHERE team_id = ANY(:ids) OR submission_id = ANY(:sids)'),{'ids':ids,'sids':sids})
        conn.execute(text('DELETE FROM pipeline_events WHERE job_id = ANY(:jids)'),{'jids':jids})
        conn.execute(text('DELETE FROM sandbox_runs WHERE submission_id = ANY(:sids)'),{'sids':sids})
        conn.execute(text('DELETE FROM evaluations WHERE submission_id = ANY(:sids)'),{'sids':sids})
        conn.execute(text('DELETE FROM simulation_jobs WHERE id = ANY(:jids)'),{'jids':jids})
        conn.execute(text('DELETE FROM participant_sessions WHERE team_id = ANY(:ids)'),{'ids':ids})
        conn.execute(text('DELETE FROM team_strategies WHERE team_id = ANY(:ids)'),{'ids':ids})
        conn.execute(text('DELETE FROM submissions WHERE team_id = ANY(:ids)'),{'ids':ids})
        conn.execute(text('DELETE FROM teams WHERE id = ANY(:ids)'),{'ids':ids})
        conn.execute(text("UPDATE competition_state SET phase='SETUP',reference_snapshot_json='[]',evaluation_config_json='{}',qualifier_roster_json='[]',standings_json='[]',started_at=NULL,updated_at=now() WHERE id=1"))
        conn.execute(text("UPDATE event_config SET mode='DEVELOPMENT',official_enabled=FALSE,tournament_enabled=FALSE,registrations_enabled=TRUE,uploads_enabled=TRUE,sandbox_enabled=TRUE,updated_at=now() WHERE id=1"))
        if scalar(conn,'SELECT count(*) FROM tournament_state WHERE id=1'):
            conn.execute(text('UPDATE tournament_state SET state_json=:state,updated_at=now() WHERE id=1'),{'state':json.dumps(RESET_TOURNAMENT)})
        else:
            conn.execute(text('INSERT INTO tournament_state (id,state_json,updated_at) VALUES (1,:state,now())'),{'state':json.dumps(RESET_TOURNAMENT)})
        # Re-check within same transaction without relying on new API preflight (which still shows old phase).
        after_temp=query(conn,'SELECT id,team_id,version,object_key,validation_status,official_score,is_active FROM submissions WHERE team_id=:id ORDER BY id',{'id':snap['protectedTeam']['id']})
        after_ref=query(conn,'SELECT id,family_id,version,display_name,source_sha256,object_key,selected,enabled,archived,validation_status,test_status FROM reference_bots ORDER BY id')
        if json_ready(after_temp)!=snap['protectedSubmissions'] or json_ready(after_ref)!=snap['referenceBots']:
            raise Halt('Protection invariant failed: rollback all changes')
        if scalar(conn,'SELECT count(*) FROM teams WHERE username = ANY(:names)',{'names':sorted(QA)}):
            raise Halt('Old QA team still exists: rollback')
        metadata={'planSha256':sha,'oldQATeamsRemoved':len(ids),'jobsRemoved':len(jids),'referenceBotsPreserved':len(after_ref),'protectedTeam':'temp','backupName':b.name}
        conn.execute(text('INSERT INTO admin_audit_log (action,target,metadata_json,created_at) VALUES (:a,:t,:m,now())'),{'a':'qa_round_reset','t':'QA26_B2C9C5','m':json.dumps(metadata)})
        # end transaction commits once, after all checks
    print('SUCCESS: Old QA accounts deleted; stale qualification returned to SETUP.')
    print('Protected: temp team, all temp submissions and five reference bots unchanged.')
    print('Next: run Check from the launcher and verify phase SETUP before provisioning.')

if __name__=='__main__':
    try:run()
    except (Halt,Exception) as e:
        print('STOP:',str(e)[:500],file=sys.stderr)
        sys.exit(2)
