import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest


class LocalChecks(unittest.TestCase):
    def setUp(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.process=subprocess.Popen([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(self.port),'--log-level','error'],
            cwd=Path(__file__).resolve().parents[1],env={**os.environ,'WARMUP_SECONDS':'1'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:
                if self.request('GET','/health')[0]==200:return
            except OSError:time.sleep(.02)
        self.fail('Local HTTP server failed to start')

    def stop(self):
        self.process.terminate()
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()

    def request(self,method,path,payload=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        c.request(method,path,json.dumps(payload) if payload is not None else None,{'Content-Type':'application/json'})
        r=c.getresponse();status=r.status;data=json.loads(r.read());c.close();return status,data

    def test_health_is_not_readiness(self):
        self.assertEqual(self.request('GET','/health')[0],200)
        self.assertEqual(self.request('GET','/ready')[0],503)
        self.assertEqual(self.request('POST','/generate',{'prompt':'hello'})[0],503)
        time.sleep(1.1)
        self.assertEqual(self.request('GET','/ready')[0],200)

    def test_bad_input_never_calls_backend(self):
        before=self.request('GET','/debug')[1]['calls']
        for payload in [{'prompt':''},{'prompt':'x','max_new_tokens':True},{'prompt':'x','max_new_tokens':0},{'prompt':'x','history':['bad']}]:
            self.assertEqual(self.request('POST','/generate',payload)[0],400)
        self.assertEqual(self.request('GET','/debug')[1]['calls'],before)
