"""Offline integration test for provision_test_teams.py against an in-memory local fake API."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import re
import subprocess
import sys
import threading
from urllib.parse import unquote

KIT=Path(__file__).resolve().parent

class Handler(BaseHTTPRequestHandler):
    lock=threading.Lock()
    teams={}
    tokens={}
    jobs=[]
    heartbeats=[]
    def log_message(self, *args):pass
    def reply(self, status, obj, cookies=None):
        data=json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        if cookies:self.send_header('Set-Cookie',cookies)
        self.end_headers();self.wfile.write(data)
    def session(self):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception:return None
        morsel=cookie.get('farmcraft_participant')
        if not morsel:return None
        token=morsel.value
        team=self.tokens.get(token)
        if not team:return None
        return (team,'csrf-'+team)
    def do_GET(self):
        if self.path in ('/health','/ready'):
            self.reply(200,{'status':'ok'});return
        if self.path=='/api/participants/session':
            user=self.session()
            if not user:self.reply(401,{'detail':'Not signed in'});return
            self.reply(200,{'team':user[0],'csrfToken':user[1]});return
        if self.path.startswith('/botlab/'):
            team=unquote(self.path.split('/')[2]);user=self.session()
            if user is None or user[0]!=team:self.reply(403,{'detail':'Forbidden'});return
            self.reply(200,{'currentSubmission':{'id':1} if self.teams[team] else None});return
        self.reply(404,{'detail':'Unknown path'})
    def do_POST(self):
        content=self.rfile.read(int(self.headers.get('Content-Length','0')))
        if self.path=='/api/participants/session':
            team=json.loads(content)['team']
            with self.lock:
                if team in self.teams:
                    self.reply(409,{'detail':'Already registered'});return
                self.teams[team]=False
                token='token'+str(len(self.tokens)+1)
                self.tokens[token]=team
            self.reply(200,{'team':team,'csrfToken':'csrf-'+team},f'farmcraft_participant={token}; Path=/; HttpOnly; Max-Age=28800');return
        user=self.session()
        if not user or self.headers.get('X-Participant-CSRF')!='csrf-'+user[0]:
            self.reply(403,{'detail':'CSRF invalid'});return
        if self.path=='/api/participants/heartbeat':
            data=json.loads(content)
            if data.get('latencyMs') is not None or data.get('idle') is not False:
                self.reply(422,{'detail':'Bad heartbeat'});return
            with self.lock:self.heartbeats.append(user[0])
            self.reply(200,{'status':'ok'});return
        if self.path=='/botlab/upload':
            if b'filename="agent.py"' not in content or user[0].encode() not in content:
                self.reply(422,{'detail':'Bad upload'});return
            self.teams[user[0]]=True
            self.reply(200,{'submission':{'id':1},'validation':{'valid':True,'errors':[]}});return
        if self.path.startswith('/botlab/') and self.path.endswith('/sandbox'):
            with self.lock:self.jobs.append(user[0]);jobid=str(len(self.jobs))
            self.reply(202,{'id':jobid,'status':'queued'});return
        self.reply(404,{'detail':'Unknown path'})


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with TemporaryDirectory() as d:
            args=[sys.executable,str(KIT/'provision_test_teams.py'),'--base-url',base,'--execute',
                  '--runtime-dir',str(Path(d)/'runtime'),'--arrival-delay','0', '--workers','3']
            result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
            assert result.returncode==0,result.stdout
            report=json.loads((Path(d)/'runtime/provision_results.json').read_text())
            assert report['created']==20 and report['uploaded']==20 and report['errors']==0,report
            print('PASS: 20 isolated team registrations, 20 CSRF-protected uploads, 20 session cookie files')
            result=subprocess.run(args[:-1]+['3','--mode','sandbox','--max-sandbox-jobs','4'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
            assert result.returncode==0,result.stdout
            report=json.loads((Path(d)/'runtime/provision_results.json').read_text())
            assert report['restored']==20 and report['existing_uploads']==20 and report['sandbox_queued']==4 and report['errors']==0,report
            print('PASS: 20 session restores, 20 upload skips, 4 sandbox jobs queued with CSRF')
            assert len(Handler.jobs)==4
            from http.cookiejar import MozillaCookieJar
            from urllib.request import HTTPCookieProcessor, build_opener
            from keep_teams_online import heartbeat_batch
            from csv import DictReader
            with (KIT/'teams.csv').open(encoding='utf-8',newline='') as csvf:
                teams=[row['team'] for row in DictReader(csvf)]
            sessions=[]
            for team in teams:
                path=Path(d)/'runtime'/'sessions'/f'{team}.cookies.txt'
                jar=MozillaCookieJar(str(path))
                jar.load(ignore_discard=True, ignore_expires=True)
                sessions.append((team,build_opener(HTTPCookieProcessor(jar))))
            ok, failures=heartbeat_batch(sessions,base)
            assert ok==20 and not failures,(ok,failures)
            assert len(Handler.heartbeats)==20
            print('PASS: 20 authenticated QA presence heartbeats accepted by mock API')
    finally:
        server.shutdown();thread.join()

if __name__=='__main__':main()
