"""Local mock-API E2E for safe harness mechanics (not Kaggriculture gameplay)."""
import http.server,json,sys,tempfile,threading,unittest,urllib.parse,uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import rehearsal as s

class MockServer(http.server.BaseHTTPRequestHandler):
    requests=[];teams={};sessions={};jobs={};phase='SETUP';official={}
    def log_message(self,*args):pass
    def send(self,body,status=200,cookie=None):
        raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        if cookie:self.send_header('Set-Cookie','farmcraft_participant='+cookie+'; Path=/')
        self.end_headers();self.wfile.write(raw)
    def route(self,body=None):
        path=urllib.parse.urlparse(self.path).path
        q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if self.command=='POST' and path=='/api/participants/session':
            team=body['team'];MockServer.teams.setdefault(team,{'submission':None});token=uuid.uuid4().hex;MockServer.sessions[token]=team
            return self.send({'team':team,'csrfToken':'csrf','teamId':len(MockServer.teams)},cookie=token)
        cookie=self.headers.get('Cookie','').split('farmcraft_participant=')[-1].split(';')[0]
        team=MockServer.sessions.get(cookie)
        if path=='/api/participants/session':
            return self.send({'team':team,'csrfToken':'csrf'} if team else {'detail':'not signed in'},200 if team else 401)
        if path=='/api/participants/heartbeat':return self.send({'status':'ok'})
        if path.startswith('/api/admin/'):
            if path=='/api/admin/reference-bots':return self.send({'bots':[{'id':i,'selected':True,'enabled':True,'archived':False,'sourceSha256':str(i)} for i in range(5)]})
            if path=='/api/admin/contestants':return self.send({'contestants':[{'team':'temp','teamId':123,'submissionCount':1},*({'team':t,'teamId':i,'submissionCount':int(bool(d['submission']))} for i,(t,d) in enumerate(MockServer.teams.items()))]})
            if path=='/api/admin/competition':return self.send({'phase':MockServer.phase,'settings':{'qualifierCount':16}})
            if path=='/api/admin/metrics':return self.send({'workers':{'total':2},'contestants':len(MockServer.teams),'health':{'postgres':'healthy'}})
            if path=='/api/admin/competition/standings':return self.send({'entries':[]})
            if path=='/api/admin/tournament':return self.send({'status':'completed','champion':{'team':'temp'},'allMatches':[]})
            if path=='/api/admin/tournament/games':return self.send({'games':[]})
            if path.startswith('/api/admin/jobs'):return self.send({'jobs':[]})
            if path=='/api/admin/pipeline':return self.send({'jobs':[]})
        if path.startswith('/botlab/') and path.endswith('/submit') and self.command=='POST':
            if MockServer.phase!='QUALIFICATION_OPEN':return self.send({'detail':'not open'},423)
            if team in MockServer.official:return self.send({'detail':'already submitted'},409)
            jid=str(uuid.uuid4());MockServer.official[team]=jid
            MockServer.jobs[jid]={'status':'completed','result':{'rating':123,'botFinalMoney':999},'worker':'worker1'}
            return self.send({'id':jid},202)
        if path=='/botlab/upload' and self.command=='POST':
            if not team:return self.send({'detail':'unauthorized'},401)
            MockServer.teams[team]['submission']={'id':len(MockServer.teams),'validation_status':'valid'}
            return self.send({'submission':MockServer.teams[team]['submission'],'validation':{'valid':True}})
        if path.startswith('/botlab/') and path.endswith('/sandbox') and self.command=='POST':
            jid=str(uuid.uuid4());replay='e'*32
            MockServer.jobs[jid]={'status':'completed','result':{'botFinalMoney':900,'opponentFinalMoney':400,'replayId':replay},'worker':'worker1'}
            return self.send({'id':jid},202)
        if path.startswith('/botlab/') and self.command=='GET':
            requested=path.split('/')[-1]
            if team!=requested:return self.send({'detail':'forbidden'},403)
            return self.send({'currentSubmission':MockServer.teams.get(team,{}).get('submission')})
        if path.startswith('/jobs/'):
            jid=path.split('/')[-1]
            return self.send(MockServer.jobs[jid] if jid in MockServer.jobs else {'detail':'missing'},200 if jid in MockServer.jobs else 404)
        if path.startswith('/replays/'):
            if path.endswith('analytics'):return self.send({'steps':12,'finalCash':900})
            if path.endswith('playback'):return self.send({'totalSteps':12,'players':[[{'step':i,'farm':{'tiles':[[None]*10]*10}} for i in range(12)]]})
            if '/frame/' in path:return self.send({'step':0,'farm':{'tiles':[[None]*10]*10}})
        return self.send({'detail':'not found: '+path},404)
    def do_GET(self):self.route()
    def do_POST(self):
        raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
        try:body=json.loads(raw)
        except Exception:body={}
        self.route(body)

class TestHarness(unittest.TestCase):
    def test_three_team_full_journey(self):
        MockServer.teams={};MockServer.sessions={};MockServer.jobs={};MockServer.phase='SETUP';MockServer.official={}
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),MockServer)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_address[1]}'
        class Args:pass
        a=Args();a.base_url=base;a.approve_live=False;a.staging_host='';a.delay=0;a.wave=1;a.poll_seconds=3;a.max_minutes=1
        a.phase='sandbox1';a.duration_minutes=1;a.permit_unbenchmarked=True
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            all_rows=s.rows()
            with patch.object(s,'RUNTIME',path),patch.object(s,'STATE_FILE',path/'state.json'),patch.object(s,'rows',lambda:all_rows[:3]),patch.object(s,'admin',lambda base:(s.build_opener(), 'csrf')):
                data=s.init_state(base)
                s.preflight(a,base,data)
                s.cmd_provision(a,base,data)
                for wave in (1,2):
                    a.wave=wave;s.cmd_sandbox(a,base,data)
                    a.phase=f'sandbox{wave}';s.cmd_monitor(a,base,data)
                    s.cmd_analytics(a,base,data)
                MockServer.phase='QUALIFICATION_OPEN'
                s.cmd_official(a,base,data)
                a.phase='round1';s.cmd_monitor(a,base,data)
                MockServer.phase='QUALIFICATION_FINALIZED'
                s.cmd_tournament(a,base,data)
                with patch.object(s,'ROOT',path):
                    s.cmd_report(a,base,data)
                self.assertEqual(len(MockServer.teams),3)
                self.assertEqual(len(MockServer.official),3)
                self.assertTrue((path/'state.json').exists())
                for t,v in data['teams'].items():
                    self.assertEqual(v['sandbox']['1']['status'],'completed')
                    self.assertEqual(v['sandbox']['2']['status'],'completed')
                    self.assertTrue(v['analytics']['1']['ok'])
                    self.assertEqual(v['official']['status'],'completed')
        server.shutdown()
        server.server_close()

if __name__=='__main__':
    s.original_rows=s.rows()
    unittest.main()
