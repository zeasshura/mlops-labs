import json,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT,ENV,TOOLS,Observer,command,k,obj,pods,helm,run_load,exec_json,api_request

HASHES={'A':'2cbfcc2c2599d0df8999f8f80d015c710b6e96ce153936833f8c511cfc5fa4ca','B':'555a4dd71e4b461730fd594f867bc838d45cc7e87ebf524cedce1a01b7f7378c'}


def long_request(ip,label,chunks=64,interval=.7):
    code="from client import one;import json,time;print(json.dumps(one("+repr(f'http://{ip}:8091/generate')+",{'index':0,'client':0,'chunks':"+str(chunks)+",'interval':"+str(interval)+",'timeout':70},"+repr(label)+",time.monotonic(),time.time())))"
    return exec_json(code)


def save(name,value):
    (ROOT/'results'/name).write_text(json.dumps(value,indent=2)+'\n')


def main():
    if '--resume-tail' not in sys.argv:k('rollout','status','deployment/api','--timeout=180s')
    pool=ThreadPoolExecutor(max_workers=3)
    try:
        if '--resume-rollout' not in sys.argv and '--resume-tail' not in sys.argv:
            with Observer('A-broken-warmup'):
                load=pool.submit(run_load,'A-warmup-before','balanced','uniform',40,2,False)
                time.sleep(1);k('rollout','restart','deployment/api')
                before,_=load.result();k('rollout','status','deployment/api','--timeout=180s')
            premature=[r for r in before if r.get('warmup_finished_at_accept') is False and r['outcome']=='completed']
            save('warmup-regression-before.json',{'expected_assertion':'All successful responses were warmed','passed':not premature,'premature_responses':len(premature)})
            assert premature,'Original defect not reproduced; do not claim a red proof'
            with Observer('A-fixed-warmup'):
                load=pool.submit(run_load,'A-warmup-after','balanced','uniform',55,2,False)
                time.sleep(1);helm(wait=False,brokenReadiness=False)
                after,_=load.result();k('rollout','status','deployment/api','--timeout=180s')
            assert not any(r.get('warmup_finished_at_accept') is False for r in after if r['outcome']=='completed')
            save('warmup-regression-after.json',{'passed':True,'premature_responses':0})
        if '--resume-tail' not in sys.argv:
            # A long stream has already emitted content when rollout starts.
            helm(maxRunning=2)
            old=pods()[0];ip=old['status']['podIP']
            with Observer('A-rolling-A-to-B'):
                long=pool.submit(long_request,ip,'A-long-rollout')
                load=pool.submit(run_load,'A-rollout','balanced','uniform',65,.5,False)
                time.sleep(3)
                change_started=time.time();helm(wait=False,modelVersion='B',modelSha256=HASHES['B'])
                long_result=long.result();records,_=load.result();k('rollout','status','deployment/api','--timeout=180s')
            save('rolling-long-stream.json',{'rollout_start_epoch':change_started,'old_pod':old['metadata']['name'],'request':long_result})
            assert long_result['outcome']=='completed' and long_result['parts']==64
            assert all(r['status']<500 and r['outcome']=='completed' for r in records), 'Rollout had failures; retain and fix'
        # Restore admitted A before demonstrating a deliberately unavailable B.
        helm(modelVersion='A',modelSha256=HASHES['A'])
        history=json.loads(command([TOOLS/'helm','history','hw11','-n','hw11','-o','json']).stdout)
        revision=history[-1]['revision']
        with Observer('A-unready-B-and-rollback'):
            helm(wait=False,modelVersion='B',modelSha256=HASHES['B'],neverReady=True)
            records,_=run_load('A-unready-B-fixed','balanced','uniform',35,.5,False)
            snapshot=obj('get','pods','-l','app=hw11-api')
            save('unready-B-pods.json',snapshot)
            assert all(r.get('model_id')=='simulated-model-A' for r in records if r['outcome']=='completed')
            command([TOOLS/'helm','rollback','hw11',str(revision),'-n','hw11','--wait','--timeout','180s'],timeout=200)
            k('rollout','status','deployment/api','--timeout=180s')
            response=api_request();save('rollback-response.json',response)
            assert 'simulated-model-A' in response['body']
        from force_failure import main as force_failure
        force_failure()
        print('Experiment A verified: bad/fixed warmup, zero-failure rollout, unready B, rollback, forced failure.',flush=True)
    finally:pool.shutdown(wait=True)


if __name__=='__main__':main()
