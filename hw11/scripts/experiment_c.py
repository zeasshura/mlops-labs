import json,sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT,Observer,helm,k,obj,pods,run_load,http


def wait_replicas(number,timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        d=obj('get','deployment','api')['status']
        h=obj('get','hpa','api').get('status',{})
        if d.get('replicas')==number and d.get('readyReplicas')==number and h.get('desiredReplicas')==number and h.get('currentReplicas')==number:return {'epoch':time.time(),'deployment':d,'hpa':h}
        time.sleep(3)
    raise TimeoutError(f'No stable {number} Ready replicas')


def main():
    from harvest import harvest
    harvest()
    # Remove the preceding workload from the resource metrics window.
    time.sleep(60)
    helm(warmupSeconds=20,serviceAffinity='None',**{'hpa.enabled':True})
    k('get','--raw','/apis/metrics.k8s.io/v1beta1/namespaces/hw11/pods')
    k('get','hpa','api','-o','yaml')
    initial=wait_replicas(2)
    (ROOT/'results/hpa-initial.json').write_text(json.dumps(initial,indent=2)+'\n')
    (ROOT/'results/hpa-config.yaml').write_text(k('get','hpa','api','-o','yaml').stdout)
    stopped=threading.Event()
    def rules():
        with (ROOT/'results/alert-states.jsonl').open('w') as stream:
            while not stopped.is_set():
                try:
                    data=http('http://127.0.0.1:19090/api/v1/rules')
                    states={r['name']:{'state':r['state'],'health':r.get('health'),'alerts':r.get('alerts',[]),'lastError':r.get('lastError')}
                            for g in data['data']['groups'] for r in g['rules'] if r.get('type')=='alerting'}
                    stream.write(json.dumps({'epoch':time.time(),'states':states},separators=(',',':'))+'\n');stream.flush()
                except Exception as exc:stream.write(json.dumps({'epoch':time.time(),'error':str(exc)[:300]})+'\n');stream.flush()
                stopped.wait(2)
    thread=threading.Thread(target=rules,daemon=True);thread.start()
    evidence={'initial':initial}
    try:
        with Observer('C-computational-pressure') as observer:
            rows,meta=run_load('C-cpu-pressure','balanced','uniform',120,12)
            evidence['pressure']=meta;evidence['after_pressure']=obj('get','hpa','api')['status']
            observer.phase='C-first-cooldown';cool_start=time.time();down=wait_replicas(2,240)
            evidence['first_scale_down']={**down,'idle_started':cool_start,'wait_seconds':down['epoch']-cool_start}
        with Observer('C-hot-affinity') as observer:
            rows,meta=run_load('C-hot-affinity','sticky','hot',120,3)
            evidence['hot']=meta;evidence['after_hot']=obj('get','hpa','api')['status']
            evidence['hot_pods']=[{'pod':p['metadata']['name'],'created':p['metadata']['creationTimestamp'],'ip':p['status'].get('podIP')} for p in pods()]
            observer.phase='C-final-recovery';cool_start=time.time();down=wait_replicas(2,240)
            evidence['final_scale_down']={**down,'idle_started':cool_start,'wait_seconds':down['epoch']-cool_start}
        # Wait until BOTH alert rules have returned to inactive after sufficient hold time.
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            data=http('http://127.0.0.1:19090/api/v1/rules')
            states=[r.get('state') for g in data.get('data',{}).get('groups',[]) for r in g['rules'] if r.get('type')=='alerting']
            if len(states)==2 and all(s=='inactive' for s in states):break
            time.sleep(3)
        else:raise TimeoutError('Alerts did not recover')
        (ROOT/'results/hpa-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print('Real HPA pressure, 2->3->2, hot affinity and alert recovery recorded.',flush=True)
    finally:stopped.set();thread.join(timeout=10)
    states=[json.loads(s) for s in (ROOT/'results/alert-states.jsonl').read_text().splitlines()]
    for name in ['HighFirstChunkLatency','HighFailureFraction']:
        observed={r.get('states',{}).get(name,{}).get('state') for r in states}
        assert {'inactive','pending','firing'}<=observed,(name,observed)
    timeline=[json.loads(s) for s in (ROOT/'results/timeline.jsonl').read_text().splitlines()]
    assert any(r.get('phase','').startswith('C-') and r.get('hpa',{}).get('currentReplicas')==3 for r in timeline)
    print('Both alerts passed inactive -> pending -> firing -> inactive assertions.',flush=True)
    harvest()


if __name__=='__main__':
    main()
    import subprocess
    subprocess.run([sys.executable,'-u',str(ROOT/'scripts/force_failure.py')],cwd=ROOT,check=True)
    subprocess.run([sys.executable,'-u',str(ROOT/'scripts/warmup_comparison.py')],cwd=ROOT,check=True)
