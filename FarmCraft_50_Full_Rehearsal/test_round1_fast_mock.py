"""Offline checks: no external HTTP, no actual official job creation."""
import tempfile,types,unittest
from unittest.mock import patch
import rehearsal
import round1_fast_precheck as fast

class TestFastRound1(unittest.TestCase):
    def mkrow(self,i):
        return {'team':f'FC26_R50_{i:03d}','family':'A','sha256':'fake','bot_file':'a.py'}

    def test_waiver_keeps_wave1_mandatory(self):
        rows=[self.mkrow(i) for i in range(1,3)]
        refs=[{'id':i,'version':1,'sourceSha256':str(i),'selected':True,'enabled':True,'archived':False} for i in range(1,6)]
        data={'preflight':{'target':'https://neural-coliseum-api.onrender.com','protectedTeamExists':True,'references':refs}, 'qualityGatePassed':True, 'teams':{}}
        for i,r in enumerate(rows):
            data['teams'][r['team']]={'upload':'valid','submissionId':i+1,'sandbox':{'1':{'status':'completed','id':str(i),'contestantStatus':'complete'},'2':{'status':'ambiguous'}},'analytics':{'1':{'ok':True}},'official':{}}
        args=types.SimpleNamespace(allow_unverified_wave2=True,permit_unbenchmarked=False,delay=0)
        base='https://neural-coliseum-api.onrender.com'
        with patch.object(rehearsal,'rows',return_value=rows),patch.object(rehearsal,'admin',return_value=(None,'a')),patch.object(rehearsal,'admin_get',side_effect=lambda op,base,path: {'phase':'QUALIFICATION_OPEN'} if path=='/competition' else {'bots':refs}),patch.object(rehearsal,'session',return_value=(None,{'csrfToken':'c'},'valid')),patch.object(rehearsal,'request',return_value=(202,{'id':'fake-id'},1)) as req,patch.object(rehearsal,'atomic_json'),patch.object(rehearsal,'event'):
            rehearsal.cmd_official(args,base,data)
            self.assertEqual(req.call_count,2)
            data['teams'][rows[0]['team']]['sandbox']['1']['status']='failed'
            with self.assertRaises(RuntimeError):rehearsal.cmd_official(args,base,data)

    def test_no_waiver_blocks_missing_wave2(self):
        rows=[self.mkrow(1)]
        refs=[{'id':i,'version':1,'sourceSha256':str(i),'selected':True,'enabled':True,'archived':False} for i in range(1,6)]
        data={'preflight':{'target':'https://neural-coliseum-api.onrender.com','protectedTeamExists':True,'references':refs}, 'qualityGatePassed':True,'teams':{rows[0]['team']:{'upload':'valid','submissionId':1,'sandbox':{'1':{'status':'completed'},'2':{'status':'ambiguous'}},'analytics':{'1':{'ok':True}}}}}
        args=types.SimpleNamespace(allow_unverified_wave2=False,permit_unbenchmarked=False,delay=0)
        with patch.object(rehearsal,'rows',return_value=rows),patch.object(rehearsal,'admin',return_value=(None,'a')),patch.object(rehearsal,'admin_get',side_effect=lambda op,base,path:{'phase':'QUALIFICATION_OPEN'} if path=='/competition' else {'bots':refs}):
            with self.assertRaises(RuntimeError):rehearsal.cmd_official(args,'https://neural-coliseum-api.onrender.com',data)

    def test_precheck_stops_if_one_of_49_still_queued(self):
        rows=[self.mkrow(i) for i in range(1,51)]
        refs=[{'id':i,'version':1,'sourceSha256':str(i),'selected':True,'enabled':True,'archived':False} for i in range(1,6)]
        url='https://neural-coliseum-api.onrender.com'
        snap={'protectedTeamExists':True,'selectedReferenceCount':5,'references':refs,'protectedTeam':[{'teamId':1,'submissionCount':2,'latestVersion':2}]}
        state={'target':url,'preflight':snap,'qualityGatePassed':True,'teams':{}}
        jobs=[]
        for i,r in enumerate(rows,1):
            w2={'status':'ambiguous','seed':20262101+i,'opponent':'animal'} if i==45 else {'id':f'job{i}','status':'queued','seed':20262101+i,'opponent':'animal'}
            state['teams'][r['team']]={'upload':'valid','submissionId':i+101,'sandbox':{'1':{'id':f'w1{i}','status':'completed'},'2':w2},'analytics':{'1':{'ok':True}}}
            if i!=45:jobs.append({'id':f'job{i}','type':'sandbox','team':r['team'],'opponent':'animal','seed':20262101+i,'status':'queued' if i==1 else 'completed'})
        def admin_get(op,base,path):
            if path=='/competition':return {'phase':'QUALIFICATION_OPEN'}
            if path=='/reference-bots':return {'bots':refs}
            if path=='/contestants':return {'contestants':[{'team':'temp','teamId':1,'submissionCount':2,'latestVersion':2}]+[{'team':r['team']} for r in rows]}
            if 'job_type=official' in path:return {'jobs':[]}
            if 'job_type=sandbox' in path:return {'jobs':jobs}
            raise AssertionError(path)
        with patch.object(fast,'load_json',return_value=state),patch.object(fast,'rows',return_value=rows),patch.object(fast,'admin',return_value=(None,'c')),patch.object(fast,'admin_get',side_effect=admin_get):
            with self.assertRaisesRegex(RuntimeError,'Timed out'):
                fast.inspect(url,wait_minutes=0,poll_seconds=0)
            jobs[0]['status']='completed'
            fast.inspect(url,wait_minutes=0,poll_seconds=0)

if __name__=='__main__':unittest.main()
