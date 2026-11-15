"""Commands always address this task's kubeconfig and hw11 namespace."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler

ROOT=Path(__file__).resolve().parent
NS='hw11'
ENV={**os.environ,'KUBECONFIG':str(ROOT/'.runtime/kubeconfig'),'KIND_EXPERIMENTAL_PROVIDER':'podman'}
TOOLS=ROOT/'.tools'


def command(args,check=True,**kw):
    p=subprocess.run([str(x) for x in args],cwd=ROOT,env=ENV,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**kw)
    if check and p.returncode:raise RuntimeError(' '.join(map(str,args[:5]))+'\n'+p.stdout[-5000:])
    return p


def k(*args,check=True,**kw):return command([TOOLS/'kubectl','--kubeconfig',ENV['KUBECONFIG'],'-n',NS,*args],check=check,**kw)


def obj(*args):return json.loads(k(*args,'-o','json').stdout)


def pods():return obj('get','pods','-l','app=hw11-api')['items']


def helm(wait=True,**values):
    args=[TOOLS/'helm','upgrade','--install','hw11','chart','-n',NS,'--create-namespace','--timeout','180s']
    if wait:args.append('--wait')
    for key,value in values.items():args.extend(['--set',f'{key}={str(value).lower() if type(value) is bool else value}'])
    result=command(args,timeout=210)
    if wait:k("rollout","status","deployment/api","--timeout=180s")
    return result


def exec_json(code,pod='client-0'):
    return json.loads(k('exec',pod,'--','python','-c',code,timeout=90).stdout)


def http(url,payload=None):
    from urllib.request import Request
    from urllib.error import HTTPError
    request=Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
    try:
        with build_opener(ProxyHandler({})).open(request,timeout=20) as response:return json.load(response)
    except HTTPError as exc:return {'status':exc.code,'body':exc.read().decode()}


def api_request(url='http://balanced:8091/generate',payload=None):
    payload=payload or {'prompt':'hello','max_new_tokens':1}
    code="import json,http.client;from urllib.parse import urlsplit;u=urlsplit("+repr(url)+");c=http.client.HTTPConnection(u.hostname,u.port,timeout=45);c.request('POST',u.path,json.dumps("+repr(payload)+"),{'Content-Type':'application/json','Connection':'close'});r=c.getresponse();print(json.dumps({'status':r.status,'body':r.read().decode()}))"
    return exec_json(code)


def debug_ip(ip):return exec_json("import urllib.request,json;print(urllib.request.urlopen('http://"+ip+":8091/debug').read().decode())")


def reset_cache():
    for pod in pods():
        if pod['metadata'].get('deletionTimestamp'):continue
        ip=pod['status'].get('podIP')
        if ip:
            response=exec_json("import urllib.request;print(urllib.request.urlopen(urllib.request.Request('http://"+ip+":8091/cache/reset',data=b'{}')).read().decode())")
            if not response.get('reset'):raise RuntimeError('Cache still busy')


def schedule(traffic,duration=120,rate=3):
    rows=[]
    for i in range(int(duration*rate)):
        client=(i%4) if traffic=='uniform' else (0 if i%5 else 1+(i//5)%3)
        rows.append({'index':i,'offset':i/rate,'client':client,'prefix':f'prefix-client-{client}',
                     'length':128 if i%2 else 512,'chunks':4,'interval':.06,'timeout':30})
    return rows


def run_load(label,service,traffic='uniform',duration=120,rate=3,reset=True):
    if reset:reset_cache()
    rows=schedule(traffic,duration,rate)
    schedules=ROOT/'results/schedules';schedules.mkdir(parents=True,exist_ok=True)
    schedule_path=schedules/(traffic+f'-{duration}s-{rate}rps.json')
    body=json.dumps(rows,separators=(',',':'))
    if schedule_path.exists():assert schedule_path.read_text()==body
    else:schedule_path.write_text(body)
    for index in range(4):
        k('exec','-i',f'client-{index}','--','python','-c',"import sys;open('/tmp/hw11-schedule.json','w').write(sys.stdin.read())",input=body)
    start=time.time()+5
    processes=[]
    for index in range(4):
        args=[TOOLS/'kubectl','--kubeconfig',ENV['KUBECONFIG'],'-n',NS,'exec',f'client-{index}','--','python','client.py',
              '--url',f'http://{service}:8091/generate','--schedule','/tmp/hw11-schedule.json','--client',str(index),
              '--start-at',str(start),'--run-id',label]
        processes.append(subprocess.Popen(list(map(str,args)),cwd=ROOT,env=ENV,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
    records=[]
    # Drain all four stdout pipes concurrently: a full pipe must not stall a load client.
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs=list(pool.map(lambda process: process.communicate(timeout=duration+70),processes))
    for process,(output,errors) in zip(processes,outputs):
        if process.returncode:raise RuntimeError(errors[-3000:])
        records.extend(json.loads(line) for line in output.splitlines() if line.strip())
    records.sort(key=lambda r:r['index']);assert len(records)==len(rows),(len(records),len(rows))
    directory=ROOT/'results/runs';directory.mkdir(parents=True,exist_ok=True)
    (directory/(label+'.jsonl')).write_text(''.join(json.dumps(row,separators=(',',':'))+'\n' for row in records))
    metadata={'run_id':label,'service':service,'traffic':traffic,'duration_seconds':duration,'rate':rate,'start_epoch':start,
              'end_epoch':time.time(),'schedule_sha256':hashlib.sha256(body.encode()).hexdigest(),
              'cache_initial':('empty, verified reset on both warmed pods' if reset else 'not reset; lifecycle experiment retains cache state'),'keep_alive':False,
              'planned':len(rows),'sent':len(records),'completed':sum(r['outcome']=='completed' for r in records)}
    (directory/(label+'-meta.json')).write_text(json.dumps(metadata,indent=2)+'\n')
    print(label,metadata['completed'],'/',len(records),'completed',flush=True)
    return records,metadata


class Observer:
    def __init__(self,phase):self.phase=phase;self.stop=threading.Event();self.thread=None
    def __enter__(self):
        def collect():
            path=ROOT/'results/timeline.jsonl'
            with path.open('a') as output:
                while not self.stop.is_set():
                    try:
                        ps=pods();es=obj('get','endpointslices','-l','kubernetes.io/service-name=balanced')['items']
                        hs=k('get','hpa','api','-o','json',check=False)
                        record={'epoch':time.time(),'monotonic':time.monotonic(),'phase':self.phase,
                          'pods':[{'name':p['metadata']['name'],'ip':p['status'].get('podIP'),'deleting':p['metadata'].get('deletionTimestamp'),
                           'ready':any(c['type']=='Ready' and c['status']=='True' for c in p['status'].get('conditions',[])),
                           'created':p['metadata']['creationTimestamp'],'restarts':sum(c['restartCount'] for c in p['status'].get('containerStatuses',[]))} for p in ps],
                          'endpoints':[{'pod':e.get('targetRef',{}).get('name'),'conditions':e.get('conditions')} for s in es for e in s.get('endpoints',[])]}
                        if hs.returncode==0:record['hpa']=json.loads(hs.stdout).get('status') or {}
                        output.write(json.dumps(record,separators=(',',':'))+'\n');output.flush()
                    except Exception as exc:output.write(json.dumps({'epoch':time.time(),'phase':self.phase,'observer_error':str(exc)[:300]})+'\n');output.flush()
                    self.stop.wait(1)
        self.thread=threading.Thread(target=collect,daemon=True);self.thread.start();return self
    def __exit__(self,*args):self.stop.set();self.thread.join(timeout=20)


def prometheus(query,when=None):
    params={'query':query}
    if when is not None:params['time']=when
    return http('http://127.0.0.1:19090/api/v1/query?'+urlencode(params))
