#!/usr/bin/env python3
"""Strictly scoped removal of previous QA26_B2C9C5_nn accounts from the same PostgreSQL.

Requires actual DATABASE_URL, trusted repository code, verified pg_dump backup,
a plan fingerprint, and typed confirmation. NEVER resets competition/reference bots.
Object blobs are deliberately preserved; generate a separate, reviewed list for
orphan cleanup later. This tool is not usable through public participant APIs.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,sys
from pathlib import Path
from sqlalchemy import select,delete,func,or_

PREFIX='QA26_B2C9C5_'
NAMES={f'{PREFIX}{i:02d}' for i in range(1,21)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',type=Path,required=True,help='Path to local Kaggriculture checkout containing backend/')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--plan-sha',default='',help='Expected checksum printed by dry-run')
    p.add_argument('--backup-file',type=Path,help='Existing independently verified PostgreSQL backup, required before deletion')
    p.add_argument('--confirm',default='',help='Exact text DELETE OLD QA20 ONLY')
    args=p.parse_args()
    if not os.environ.get('DATABASE_URL') or not os.environ['DATABASE_URL'].startswith(('postgresql://','postgres://','postgresql+psycopg://')):
        raise RuntimeError('DATABASE_URL must be set to the confirmed production/staging PostgreSQL connection (never an implicit SQLite fallback).')
    root=args.repo_root.resolve()
    if not (root/'backend'/'services'/'storage.py').exists():raise RuntimeError('Invalid --repo-root')
    sys.path.insert(0,str(root))
    from backend.services.storage import (store,Team,Submission,SimulationJob,PipelineEvent,OfficialSubmissionClaim,
        SandboxRun,Evaluation,ParticipantSession,TeamStrategy,ReferenceBot,CompetitionState,TournamentGame)
    # Ensure the active engine points at the exact requested database.
    url=str(store.engine.url)
    if store.engine.dialect.name!='postgresql':raise RuntimeError('Backend Store is not using PostgreSQL.')
    if url.split('@')[-1].split('?')[0]!=os.environ['DATABASE_URL'].split('@')[-1].split('?')[0]:
        raise RuntimeError('Loaded backend database target does not match DATABASE_URL; refuse to delete')
    with store.session() as db:
        phase=db.get(CompetitionState,1)
        if phase and phase.phase!='SETUP':raise RuntimeError(f'Competition phase {phase.phase!r}; cleanup only in SETUP. Do not reset phase automatically.')
        protected=db.scalar(select(Team).where(func.lower(Team.username)=='temp'))
        if not protected:raise RuntimeError('Protected personal team temp not present. Refuse.')
        temp_submissions=[(x.id,x.version,x.object_key,x.official_score) for x in db.scalars(select(Submission).where(Submission.team_id==protected.id).order_by(Submission.id)).all()]
        refs=db.scalars(select(ReferenceBot).order_by(ReferenceBot.id)).all()
        active=[r for r in refs if r.selected and r.enabled and not r.archived]
        if len(refs)<5:raise RuntimeError(f'Expected at least 5 reference bot records, got {len(refs)}. Refuse.')
        refs_snapshot=[(r.id,r.family_id,r.version,r.source_sha256,r.object_key,r.selected,r.enabled,r.archived) for r in refs]
        existing=db.scalars(select(Team).where(Team.username.in_(sorted(NAMES))).order_by(Team.username)).all()
        extra_names=[t.username for t in existing if t.username not in NAMES]
        if extra_names:raise RuntimeError('Unexpected identity in cleanup candidates: '+str(extra_names))
        ids=[x.id for x in existing]
        submissions=db.scalars(select(Submission).where(Submission.team_id.in_(ids))).all() if ids else []
        sids=[s.id for s in submissions]
        jobs=db.scalars(select(SimulationJob).where(or_(SimulationJob.team_id.in_(ids),SimulationJob.submission_id.in_(sids)))).all() if ids else []
        active_jobs=[j.id for j in jobs if j.status in ('queued','running')]
        if active_jobs:raise RuntimeError('Active QA jobs exist; wait or cancel them through authorized admin flow before cleanup: '+str(active_jobs[:5]))
        official=db.scalars(select(OfficialSubmissionClaim).where(OfficialSubmissionClaim.team_id.in_(ids))).all() if ids else []
        if official:raise RuntimeError('Old QA teams hold official claims. Require separate reviewed cleanup before changing official history.')
        games=db.scalars(select(TournamentGame).where(or_(TournamentGame.player_zero.in_(sorted(NAMES)),TournamentGame.player_one.in_(sorted(NAMES))))).all()
        if games:raise RuntimeError('Old QA team appears in tournament games. Do not modify tournament history automatically.')
        # Preserve everything linked to temp and reference bots; never delete competition tables.
        plan={'targetHost':store.engine.url.host,'targetDatabase':store.engine.url.database,'preservedTeam':protected.username,
              'referenceBotHashes':[r[3] for r in refs_snapshot],
              'teams':[{'id':t.id,'name':t.username} for t in existing],
              'submissionIds':sorted(sids),'jobIds':sorted(j.id for j in jobs),
              'objectKeysLeftIntact':sorted(s.object_key for s in submissions),
              'replayIdsLeftIntact':[]}
        # Get replay IDs from sandbox_runs, no deletion of any replay blobs here.
        if sids:
            plan['replayIdsLeftIntact']=[x.replay_id for x in db.scalars(select(SandboxRun).where(SandboxRun.submission_id.in_(sids))).all() if x.replay_id]
        raw=json.dumps(plan,sort_keys=True,separators=(',',':')).encode()
        sha=hashlib.sha256(raw).hexdigest()
        print(json.dumps({'dryRun':not args.execute,'planSha256':sha,'plan':plan},indent=2))
        if not args.execute:
            print('\nDRY RUN ONLY. Inspect candidate team names, hashes and object keys, create/verify pg_dump, then authorize exact plan SHA.')
            return
        if args.confirm!='DELETE OLD QA20 ONLY' or args.plan_sha!=sha:
            raise RuntimeError('Execution blocked: --confirm and --plan-sha must match current dry-run')
        if not args.backup_file or not args.backup_file.is_file() or args.backup_file.stat().st_size<1024:
            raise RuntimeError('Execution blocked: provide a verified nonempty pg_dump --format=custom backup file')
        if len(existing)!=20:raise RuntimeError('Expected all original 20 QA teams for scoped cleanup. Handle partial populations manually.')
        jids=[j.id for j in jobs]
        # Foreign keys and dependent records in the same DB transaction.
        if jids:db.execute(delete(PipelineEvent).where(PipelineEvent.job_id.in_(jids)))
        if sids:
            db.execute(delete(SandboxRun).where(SandboxRun.submission_id.in_(sids)))
            db.execute(delete(Evaluation).where(Evaluation.submission_id.in_(sids)))
        if jids:db.execute(delete(SimulationJob).where(SimulationJob.id.in_(jids)))
        db.execute(delete(ParticipantSession).where(ParticipantSession.team_id.in_(ids)))
        db.execute(delete(TeamStrategy).where(TeamStrategy.team_id.in_(ids)))
        db.execute(delete(Submission).where(Submission.team_id.in_(ids)))
        db.execute(delete(Team).where(Team.id.in_(ids)))
        db.flush()
        after_submissions=[(x.id,x.version,x.object_key,x.official_score) for x in db.scalars(select(Submission).where(Submission.team_id==protected.id).order_by(Submission.id)).all()]
        if temp_submissions!=after_submissions:raise RuntimeError('temp submissions changed; rollback')
        if db.scalar(select(Team.id).where(func.lower(Team.username)=='temp'))!=protected.id:
            raise RuntimeError('Protected team temp changed; rollback')
        after=db.scalars(select(ReferenceBot).order_by(ReferenceBot.id)).all()
        if refs_snapshot!=[(r.id,r.family_id,r.version,r.source_sha256,r.object_key,r.selected,r.enabled,r.archived) for r in after]:
            raise RuntimeError('Reference metadata changed; rollback')
        if db.scalars(select(Team).where(Team.username.in_(sorted(NAMES)))).first():
            raise RuntimeError('Deleted QA rows still present; rollback')
        print('All QA records deleted transactionally; temp and reference metadata unchanged. Note: orphan blobs intentionally retained.')

if __name__=='__main__':
    try:main()
    except Exception as exc: print('STOP:',str(exc)[:400],file=sys.stderr);sys.exit(2)
