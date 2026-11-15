"""Final controlled A comparison: same image, schedule, duration, limits, cold replacement."""
from concurrent.futures import ThreadPoolExecutor
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT,Observer,helm,k,pods,debug_ip,run_load


def fully_warm():
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        active=[p for p in pods() if not p['metadata'].get('deletionTimestamp')]
        if len(active)==2:
            try:
                if all(debug_ip(p['status']['podIP'])['warmup_finished'] for p in active):return
            except Exception:pass
        time.sleep(1)
    raise TimeoutError('Could not establish two warmed A replicas')


def main():
    outcomes={}
    with ThreadPoolExecutor(max_workers=1) as pool:
        for broken,name in [(True,'broken'),(False,'fixed')]:
            helm(brokenReadiness=broken,warmupSeconds=20,maxRunning=1,serviceAffinity='None',**{'hpa.enabled':False})
            fully_warm()
            with Observer('A-matched-'+name):
                load=pool.submit(run_load,'A-matched-'+name,'balanced','uniform',40,2,False)
                time.sleep(1);k('rollout','restart','deployment/api')
                records,metadata=load.result()
                k('rollout','status','deployment/api','--timeout=180s')
            premature=[r for r in records if r['outcome']=='completed' and r.get('warmup_finished_at_accept') is False]
            outcomes[name]={'premature':len(premature),'n':len(records),'metadata':metadata}
            print(name,len(premature),'premature /',len(records),'attempts',flush=True)
    assert outcomes['broken']['premature']>0 and outcomes['fixed']['premature']==0
    assert outcomes['broken']['metadata']['schedule_sha256']==outcomes['fixed']['metadata']['schedule_sha256']
    (ROOT/'results/warmup-matched-comparison.json').write_text(json.dumps(outcomes,indent=2)+'\n')
    # Leave the configured HPA available for the author's final check and demonstration.
    time.sleep(40)
    helm(brokenReadiness=False,serviceAffinity='None',warmupSeconds=20,**{'hpa.enabled':True})
    print('Matched warmup comparison passed; fixed probes and HPA restored.',flush=True)


if __name__=='__main__':main()
