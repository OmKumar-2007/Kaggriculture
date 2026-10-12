"""Offline regression checks; never performs external network calls."""
import io, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import rehearsal as h

class DummyResponse:
    def __init__(self,body):
        import json
        self.status=200
        self.payload=json.dumps(body).encode()
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.payload[:n]

class FakeOpener:
    def __init__(self):self.count=0
    def open(self,request,timeout):
        self.count+=1
        if self.count==1:
            raise HTTPError(request.full_url,500,'Transient',{},io.BytesIO(b'{"detail":"temporary replay worker error"}'))
        return DummyResponse({'steps':720})

class RetryTests(unittest.TestCase):
    def test_http_500_get_is_retried_without_post(self):
        op=FakeOpener()
        with patch.object(h.time,'sleep',return_value=None):
            code,body,_=h.request(op,'http://127.0.0.1:8000','GET','/replays/id/analytics')
        self.assertEqual(code,200)
        self.assertEqual(body.get('steps'),720)
        self.assertEqual(op.count,2)

    def test_analytics_does_not_need_participant_session(self):
        fake_data={'teams':{'FC26_R50_001':{'analytics':{},'sandbox':{'1':{'status':'completed','replayId':'f'*32}}}}}
        class Args:wave=1;delay=0
        responses=[{'steps':720,'finalCash':100},
                   {'totalSteps':720,'players':[[{'step':i} for i in range(720)]]},
                   {'step':0,'farm':{'tiles':[['EMPTY']]}}]
        def mock_request(op,base,method,path,**kwargs):return (200,responses.pop(0),2)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(h,'rows',lambda:[{'team':'FC26_R50_001'}]), \
             patch.object(h,'require_preflight',lambda data,base:None), \
             patch.object(h,'admin',lambda base:('admin_open','csrf')), \
             patch.object(h,'session',side_effect=AssertionError('Participant cookie not permitted')), \
             patch.object(h,'request',side_effect=mock_request), \
             patch.object(h,'event',lambda *a,**k:None), \
             patch.object(h,'STATE_FILE',Path(tmp)/'state.json'):
            h.cmd_analytics(Args(),'http://127.0.0.1:8000',fake_data)
        self.assertTrue(fake_data['teams']['FC26_R50_001']['analytics']['1']['ok'])

    def test_incomplete_analytics_stops_without_sum_type_error(self):
        fake_data={'teams':{'FC26_R50_001':{'analytics':{},'sandbox':{'1':{'status':'completed','replayId':'f'*32}}},
                            'FC26_R50_002':{'analytics':{},'sandbox':{'1':{'status':'completed','replayId':'e'*32}}}}}
        class Args:wave=1;delay=0
        def mock_request(op,base,method,path,**kwargs):return (500,{'detail':'server error'},2)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(h,'rows',lambda:[{'team':k} for k in fake_data['teams']]), \
             patch.object(h,'require_preflight',lambda data,base:None), \
             patch.object(h,'admin',lambda base:('admin_open','csrf')), \
             patch.object(h,'request',side_effect=mock_request), \
             patch.object(h,'event',lambda *a,**k:None), \
             patch.object(h,'STATE_FILE',Path(tmp)/'state.json'), \
             patch.object(h,'RUNTIME',Path(tmp)):
            with self.assertRaisesRegex(RuntimeError,'0/2 replays verified'):
                h.cmd_analytics(Args(),'http://127.0.0.1:8000',fake_data)

if __name__=='__main__':unittest.main()
