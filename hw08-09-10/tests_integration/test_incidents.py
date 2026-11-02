"""Same black-box checks against the original and corrected launch contracts."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from unittest.mock import patch

PROJECT=Path(os.environ.get('HW8910_PROJECT',Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0,str(PROJECT))
import release


def request(port,path,payload=None):
    data=json.dumps(payload).encode() if payload is not None else None
    req=Request(f'http://127.0.0.1:{port}{path}',data=data,headers={'Content-Type':'application/json'})
    try:
        with build_opener(ProxyHandler({})).open(req,timeout=10) as response: return response.status,json.load(response)
    except HTTPError as exc: return exc.code,json.load(exc)


class Incidents(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'workspace'
        result=self.cli('init')
        self.assertEqual(result.returncode,0,result.stdout)

    def cli(self,*args):
        return subprocess.run([sys.executable,str(PROJECT/'lab.py'),'--workspace',str(self.root),*args],
                              cwd=PROJECT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)

    def successful_run(self,*args):
        p=self.cli('run',*args);self.assertEqual(p.returncode,0,p.stdout);return p.stdout

    def pointer(self): return (self.root/'accepted.json').read_bytes()

    def server(self,warmup=0):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        output=open(Path(self.tmp.name)/f'server-{port}.txt','w');self.addCleanup(output.close)
        p=subprocess.Popen([sys.executable,str(PROJECT/'service.py'),'--workspace',str(self.root),
                            '--port',str(port),'--warmup-seconds',str(warmup)],cwd=PROJECT,stdout=output,stderr=output)
        def stop():
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        self.addCleanup(stop)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if p.poll() is not None:self.fail('Server exited: '+(Path(self.tmp.name)/f'server-{port}.txt').read_text())
            try:
                if request(port,'/health')[0]==200:return port,stop
            except (URLError,ConnectionError):pass
            time.sleep(.03)
        self.fail('Server health timed out')

    def ready(self,port):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if request(port,'/ready')[0]==200:return
            time.sleep(.03)
        self.fail('Server not ready')

    def test_01_cache_resume_and_changed_bytes_subprocess(self):
        failed=self.cli('run','--fail-after-prepare')
        self.assertNotEqual(failed.returncode,0);self.assertIn('PREPARED',failed.stdout)
        self.assertIn('CACHE_HIT',self.successful_run())
        (self.root/'input.txt').write_text('Changed bytes at the same path\n')
        self.assertIn('PREPARED',self.successful_run())
        self.assertEqual(len(list((self.root/'cache').glob('*.json'))),2)

    def test_02_each_preparation_setting_invalidates_subprocess(self):
        self.successful_run()
        original=json.loads((self.root/'config.json').read_text())
        for name,value in [('tokenizer_revision','r2'),('template_sha256','f'*64),('max_length',256),('code_revision','prepare-v2')]:
            (self.root/'config.json').write_text(json.dumps({**original,name:value}))
            self.assertIn('PREPARED',self.successful_run(),name)
        self.assertEqual(len(list((self.root/'cache').glob('*.json'))),5)

    def test_03_incomplete_foreign_nan_reports_subprocess(self):
        before=hashlib.sha256(self.pointer()).hexdigest()
        for report in ['report-incomplete.json','report-A.json']:
            bad=self.cli('run','--report',report)
            self.assertNotEqual(bad.returncode,0,bad.stdout)
            self.assertEqual(hashlib.sha256(self.pointer()).hexdigest(),before)
        report=json.loads((self.root/'report-B.json').read_text());report['metrics']['accuracy']=float('nan')
        (self.root/'nan.json').write_text(json.dumps(report))
        self.assertNotEqual(self.cli('run','--report','nan.json').returncode,0)
        self.assertEqual(hashlib.sha256(self.pointer()).hexdigest(),before)

    def test_04_rejection_and_mock_disk_failure(self):
        before=self.pointer()
        self.assertNotEqual(self.cli('run','--report','report-reject.json').returncode,0)
        self.assertEqual(self.pointer(),before)
        m=json.loads((self.root/'manifest-B.json').read_text());r=json.loads((self.root/'report-B.json').read_text())
        with patch('os.replace',side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):release.publish(m,r,self.root/'accepted.json')
        self.assertEqual(self.pointer(),before)
        self.assertEqual(list(self.root.glob('*.tmp')),[])

    def test_05_identical_publication_after_process_restart(self):
        self.successful_run();first=self.pointer();self.successful_run()
        self.assertEqual(self.pointer(),first)
        events=(self.root/'publications.jsonl').read_text().splitlines()
        self.assertEqual(len(events),1,'Duplicate actual publication events')

    def test_06_http_readiness_before_warmup(self):
        port,_=self.server(warmup=2)
        self.assertEqual(request(port,'/health')[0],200)
        self.assertFalse(request(port,'/debug')[1]['warmup_finished'])
        self.assertEqual(request(port,'/ready')[0],503)
        self.assertEqual(request(port,'/generate',{'prompt':'hello','max_new_tokens':8})[0],503)
        self.assertEqual(request(port,'/debug')[1]['calls'],0)
        self.ready(port)
        self.assertEqual(request(port,'/generate',{'prompt':'hello','max_new_tokens':8})[0],200)

    def test_07_http_loaded_version_publish_restart_and_rollback(self):
        port,stop=self.server();self.ready(port)
        payload={'prompt':'version','max_new_tokens':8}
        self.assertEqual(request(port,'/generate',payload)[1]['model_id'],'fixture-A')
        self.successful_run()
        response=request(port,'/generate',payload)[1]
        self.assertEqual(response['model_id'],'fixture-A','Pointer must not advertise unloaded B')
        self.assertIn(response['model_id'],response['answer'])
        stop();port,stop=self.server();self.ready(port)
        response=request(port,'/generate',payload)[1]
        self.assertEqual(response['model_id'],'fixture-B');self.assertIn('fixture-B',response['answer'])
        m=json.loads((self.root/'manifest-A.json').read_text());r=json.loads((self.root/'report-A.json').read_text())
        release.publish(m,r,self.root/'accepted.json')
        stop();port,_=self.server();self.ready(port)
        response=request(port,'/generate',payload)[1]
        self.assertEqual(response['model_id'],'fixture-A');self.assertIn('fixture-A',response['answer'])
        print('OBSERVED A -> pointer B / loaded A -> restart B -> rollback/restart A',flush=True)

    def test_08_http_validation_precedes_backend_call(self):
        port,_=self.server();self.ready(port)
        before=request(port,'/debug')[1]['calls']
        for payload in [{'prompt':'','max_new_tokens':8},{'prompt':'x','max_new_tokens':0},
                        {'prompt':'x','max_new_tokens':100000},{'prompt':'x','max_new_tokens':'8'},
                        {'prompt':'x','max_new_tokens':True},['x']]:
            code,_=request(port,'/generate',payload)
            self.assertTrue(400<=code<500,(payload,code))
            self.assertEqual(request(port,'/debug')[1]['calls'],before)
        code,result=request(port,'/generate',{'prompt':'valid','max_new_tokens':8})
        self.assertEqual(code,200);self.assertTrue(result['request_id'])
        self.assertEqual(request(port,'/debug')[1]['calls'],before+1)


if __name__=='__main__':unittest.main(verbosity=2)
