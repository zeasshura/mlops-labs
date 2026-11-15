import json
import os
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT,k,obj,pods,debug_ip,api_request,exec_json


def content(response):
    if response['status']!=200:raise AssertionError(response)
    return json.loads(response['body'].splitlines()[-1])


def evidence(name,payload):
    directory=ROOT/'results/checks';directory.mkdir(exist_ok=True,parents=True)
    (directory/(name+'.json')).write_text(json.dumps(payload,indent=2)+'\n')


@unittest.skipUnless(os.getenv('HW11_K8S_TESTS')=='1','Enable actual Kubernetes checks explicitly')
class KubernetesChecks(unittest.TestCase):
    def test_01_warmup_excluded_from_ready_endpoints(self):
        old={p['metadata']['name'] for p in pods()}
        k('rollout','restart','deployment/api')
        observations=[];found=False;deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            for pod in pods():
                if pod['metadata']['name'] in old or not pod['status'].get('podIP'):continue
                try:state=debug_ip(pod['status']['podIP'])
                except Exception:continue
                if not state['warmup_finished']:
                    endpoints=obj('get','endpointslices','-l','kubernetes.io/service-name=balanced')['items']
                    active=[e.get('targetRef',{}).get('name') for s in endpoints for e in s.get('endpoints',[]) if e.get('conditions',{}).get('ready')]
                    self.assertNotIn(pod['metadata']['name'],active)
                    response=api_request('http://'+pod['status']['podIP']+':8091/generate')
                    self.assertEqual(response['status'],503)
                    observations.append({'pod':pod['metadata']['name'],'backend':state,'active_endpoints':active,'response':response})
                    found=True;break
            if found:break
            time.sleep(.5)
        self.assertTrue(found,'No real unready warmup interval observed')
        k('rollout','status','deployment/api','--timeout=180s')
        evidence('warmup',observations)

    def test_02_loaded_artifact_after_rollback(self):
        original=json.loads((ROOT/'results/rollback-response.json').read_text())
        expected=content(original)['model_id'];observed=[]
        for pod in pods():
            if pod['metadata'].get('deletionTimestamp'):continue
            state=debug_ip(pod['status']['podIP'])
            self.assertEqual(state['model_id'],expected)
            self.assertEqual(state['runtime_sha256'],'2cbfcc2c2599d0df8999f8f80d015c710b6e96ce153936833f8c511cfc5fa4ca')
            observed.append(state)
        evidence('rollback-version',observed)

    def test_03_pod_replacement_restores_version_and_dialogue(self):
        history=[{'role':'user','content':'CONTROL_ALPHA_11'}]
        before=content(api_request(payload={'prompt':'continue','max_new_tokens':1,'history':history}))
        old={p['metadata']['name'] for p in pods()}
        k('delete','pod',before['pod'],'--wait=false')
        k('rollout','status','deployment/api','--timeout=180s')
        new=[p for p in pods() if p['metadata']['name'] not in old and not p['metadata'].get('deletionTimestamp')]
        self.assertTrue(new)
        after=content(api_request('http://'+new[0]['status']['podIP']+':8091/generate',{'prompt':'continue','max_new_tokens':1,'history':history}))
        self.assertNotEqual(after['pod'],before['pod']);self.assertEqual(after['model_id'],before['model_id'])
        self.assertEqual(after['history'],['CONTROL_ALPHA_11'])
        evidence('replacement-dialogue',{'before':before,'after':after})

    def test_04_rejected_and_aborted_attempts_counted(self):
        pod=next(p for p in pods() if not p['metadata'].get('deletionTimestamp'));ip=pod['status']['podIP']
        code="""import json,http.client,urllib.request,re,time
ip=IP
url='http://'+ip+':8091'
def counts():
 text=urllib.request.urlopen(url+'/metrics').read().decode()
 out={}
 for line in text.splitlines():
  if line.startswith('hw11_requests_total{'):
   outcome=re.search('outcome="([^"]+)"',line).group(1);out[outcome]=float(line.rsplit(' ',1)[1])
 return out
before=counts()
c=http.client.HTTPConnection(ip,8091);c.request('POST','/generate',json.dumps({'prompt':''}),{'Content-Type':'application/json'});r=c.getresponse();status=r.status;r.read();c.close()
c=http.client.HTTPConnection(ip,8091);c.request('POST','/generate',json.dumps({'prompt':'disconnect','max_new_tokens':32,'chunk_interval':.2}),{'Content-Type':'application/json'});r=c.getresponse();first=json.loads(r.readline());r.close();c.close()
for _ in range(40):
 after=counts()
 if after.get('aborted',0)>before.get('aborted',0):break
 time.sleep(.1)
print(json.dumps({'before':before,'after':after,'reject_status':status,'first_chunk':first}))
""".replace('IP',repr(ip))
        result=exec_json(code)
        self.assertEqual(result['reject_status'],400)
        self.assertGreaterEqual(result['after'].get('rejected',0)-result['before'].get('rejected',0),1)
        self.assertGreaterEqual(result['after'].get('aborted',0)-result['before'].get('aborted',0),1)
        evidence('accounting',result)

    def test_05_two_dialogues_are_isolated(self):
        observed=[]
        for marker in ['CONTROL_ALPHA_11','CONTROL_BETA_11']:
            result=content(api_request(payload={'prompt':'continue','max_new_tokens':1,'history':[{'role':'user','content':marker}]}))
            self.assertEqual(result['history'],[marker]);observed.append(result)
        evidence('dialogue-isolation',observed)
