"""Force-kill only after an actual first content chunk from a warmed A Pod."""
import json,select,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT,ENV,TOOLS,Observer,k,pods,debug_ip,api_request


def main():
    candidates=[p for p in pods() if not p['metadata'].get('deletionTimestamp') and any(c['type']=='Ready' and c['status']=='True' for c in p['status'].get('conditions',[]))]
    target=next(p for p in candidates if debug_ip(p['status']['podIP'])['warmup_finished'] and debug_ip(p['status']['podIP'])['model_id']=='simulated-model-A')
    ip=target['status']['podIP'];name=target['metadata']['name']
    code="""import http.client,json,time
from client import one
saved=http.client.HTTPResponse.readline
seen=False
def tapped(self,*a,**kw):
 global seen
 line=saved(self,*a,**kw)
 if line and not seen:
  piece=json.loads(line)
  if 'part' in piece:
   seen=True;print(json.dumps({'event':'first_chunk','payload':piece,'status':self.status}),flush=True)
 return line
http.client.HTTPResponse.readline=tapped
row=one(URL,{'index':0,'client':0,'chunks':64,'interval':.3,'timeout':70},RUN,time.monotonic(),time.time())
print(json.dumps({'event':'result','row':row}),flush=True)
""".replace('URL',repr('http://'+ip+':8091/generate')).replace('RUN',repr('A-force-active-'+str(int(time.time()))))
    args=[TOOLS/'kubectl','--kubeconfig',ENV['KUBECONFIG'],'-n','hw11','exec','client-0','--','python','-u','-c',code]
    with Observer('A-forced-active-stream'):
        process=subprocess.Popen(list(map(str,args)),cwd=ROOT,env=ENV,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            available,_,_=select.select([process.stdout],[],[],20)
            if not available:raise TimeoutError('No first content chunk; do not claim an active-stream kill')
            first=json.loads(process.stdout.readline())
            assert first.get('event')=='first_chunk' and first['status']==200 and first['payload']['part']==0
            assert first['payload']['warmup_finished_at_accept'] and first['payload']['model_id']=='simulated-model-A'
            killed_at=time.time();k('delete','pod',name,'--grace-period=0','--force','--wait=false')
            output,errors=process.communicate(timeout=70)
            assert process.returncode==0,errors
            result=next(json.loads(s)['row'] for s in output.splitlines() if json.loads(s).get('event')=='result')
            assert result['outcome']=='aborted' and result['parts']>0 and not result['complete'],result
            old=ROOT/'results/forced-termination-request.json'
            if old.exists():
                previous=ROOT/'results/forced-termination-before-handshake.json'
                if previous.exists():previous=ROOT/'results'/('forced-previous-'+str(int(time.time()))+'.json')
                old.rename(previous)
            old.write_text(json.dumps(result,indent=2)+'\n')
            (ROOT/'results/forced-first-chunk.json').write_text(json.dumps(first,indent=2)+'\n')
            attempts=[]
            recover_deadline=time.monotonic()+35
            while time.monotonic()<recover_deadline:
                number=len(attempts)
                probe="from client import one;import json,time;print(json.dumps(one('http://balanced:8091/generate',{'index':"+str(number)+",'client':0,'chunks':1,'timeout':4},'A-recovery-"+str(int(killed_at))+"',time.monotonic(),time.time())))"
                from lab import exec_json
                row=exec_json(probe);attempts.append(row)
                (ROOT/'results/forced-recovery-attempts.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in attempts))
                if row['outcome']=='completed' and row['model_id']=='simulated-model-A':break
                time.sleep(.3)
            else:raise TimeoutError('No successful recovery attempt; every retry is retained')
            first_success=row['sent_epoch']+row['duration_seconds']
            response={'status':row['status'],'model_id':row['model_id'],'first_success':row,'recovery_attempts':len(attempts)}
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                active=[p for p in pods() if not p['metadata'].get('deletionTimestamp') and any(c['type']=='Ready' and c['status']=='True' for c in p['status'].get('conditions',[]))]
                if len(active)>=2 and all(debug_ip(p['status']['podIP'])['warmup_finished'] for p in active):break
                time.sleep(1)
            else:raise TimeoutError('Replacement failed to become Ready')
            full_ready=time.time()
            response.update(killed_pod=name,kill_epoch=killed_at,first_success_epoch=first_success,full_ready_epoch=full_ready,
                            first_success_seconds=first_success-killed_at,full_ready_seconds=full_ready-killed_at,
                            active_pods=[p['metadata']['name'] for p in active])
            (ROOT/'results/forced-termination-recovery.json').write_text(json.dumps(response,indent=2)+'\n')
            print('Force-kill verified after first content; stream aborted and service recovered.',flush=True)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)


if __name__=='__main__':main()
