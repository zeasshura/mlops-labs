"""Real FastAPI smoke/reload and a bounded, reproducible 4+4 CPU load test."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from release import atomic_bytes, canonical

PROJECT=Path(__file__).resolve().parent


def request(port,path,payload=None,timeout=120):
    body=json.dumps(payload).encode() if payload is not None else None
    req=Request(f'http://127.0.0.1:{port}{path}',data=body,headers={'Content-Type':'application/json'})
    try:
        with build_opener(ProxyHandler({})).open(req,timeout=timeout) as response:return response.status,json.load(response)
    except HTTPError as exc:return exc.code,json.load(exc)


def start_server(root,output):
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    stream=output.open('w')
    proc=subprocess.Popen([sys.executable,str(PROJECT/'service.py'),'--workspace',str(root),
            '--engine','fastapi','--backend','real','--warmup-seconds','0','--debug','--port',str(port)],
            cwd=PROJECT,stdout=stream,stderr=stream)
    observations=[];deadline=time.monotonic()+180
    try:
        while time.monotonic()<deadline:
            if proc.poll() is not None:raise RuntimeError('Service exited: '+output.read_text()[-2000:])
            try:
                health=request(port,'/health',timeout=2);ready=request(port,'/ready',timeout=2)
                if len(observations)<2 or ready[0]==200:observations.append({'health':health,'ready':ready})
                if ready[0]==200:return proc,stream,port,observations
            except (URLError,ConnectionError,TimeoutError):pass
            time.sleep(.1)
        raise TimeoutError('Real backend did not become ready')
    except Exception:
        stop_server(proc,stream);raise


def stop_server(proc,stream):
    proc.terminate()
    try:proc.wait(timeout=15)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
    stream.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,default=PROJECT/'.runtime/real');p.add_argument('--count',type=int,default=4)
    args=p.parse_args();root=args.workspace.resolve();out=PROJECT/'docs/real';out.mkdir(parents=True,exist_ok=True)
    prompt=json.loads((root/'input.txt').read_text())['golden'][0]['input']
    manifest=json.loads((root/'accepted.json').read_text());limit=manifest['runtime']['generation']['max_new_tokens']
    payload={'prompt':prompt,'max_new_tokens':limit}
    proc,stream,port,observations=start_server(root,out/'server-first.txt')
    raw=[];summary=[]
    try:
        before=request(port,'/debug')[1]['calls'];invalid=[]
        for bad in [{'prompt':'','max_new_tokens':limit},{'prompt':'x','max_new_tokens':0},
                    {'prompt':'x','max_new_tokens':100000},{'prompt':'x','max_new_tokens':str(limit)},
                    {'prompt':'x','max_new_tokens':limit-1}]:
            code,response=request(port,'/generate',bad)
            invalid.append({'request':bad,'status':code,'response':response})
            assert 400<=code<500
        after=request(port,'/debug')[1]['calls'];assert before==after
        code,smoke=request(port,'/generate',payload);assert code==200
        assert smoke['model_id']==manifest['model_id'] and smoke['runtime_sha256']==manifest['runtime_sha256']
        atomic_bytes(out/'api-smoke.json',canonical({'synthetic':False,'health_ready':observations,'status':code,
              'request':payload,'response':smoke,'invalid_requests':invalid,'calls_before':before,'calls_after':after})+b'\n')
        for concurrency in (1,2):
            def one(index):
                started=time.perf_counter();row={'index':index,'concurrency':concurrency,'requested_max_new_tokens':limit}
                try:
                    status,response=request(port,'/generate',payload)
                    row.update(status=status,error=response.get('error'),**{k:response.get(k) for k in
                         ['request_id','model_id','runtime_sha256','output_tokens','generation_seconds','queue_seconds','total_seconds']})
                except Exception as exc:row.update(status=0,error=f'{type(exc).__name__}: {exc}')
                row['client_seconds']=time.perf_counter()-started
                return row
            start=time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:rows=list(pool.map(one,range(args.count)))
            duration=time.perf_counter()-start;raw.extend(rows)
            ok=[r for r in rows if r['status']==200 and not r['error']];errors=[r for r in rows if r not in ok]
            summary.append({'concurrency':concurrency,'n':len(rows),'successes':len(ok),'errors':len(errors),
                 'batch_seconds':duration,'successful_requests_per_second':len(ok)/duration,
                 'mean_success_seconds':sum(r['client_seconds'] for r in ok)/len(ok) if ok else None,
                 'max_success_seconds':max((r['client_seconds'] for r in ok),default=None),
                 'mean_error_seconds':sum(r['client_seconds'] for r in errors)/len(errors) if errors else None,
                 'max_error_seconds':max((r['client_seconds'] for r in errors),default=None)})
            print(summary[-1],flush=True)
    finally:stop_server(proc,stream)
    atomic_bytes(out/'load-requests.jsonl',b''.join(canonical(row)+b'\n' for row in raw))
    with (out/'load-summary.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
    atomic_bytes(out/'load-summary.json',canonical({'device':'CPU','count_per_mode':args.count,'same_request':payload,
          'results':summary,'limitations':'Sequential backend, 4 CPU threads, bounded queue; JSON completion latency only, no TTFT/ITL/p95'})+b'\n')
    # Reload the exact accepted release in a new process, not merely reread its pointer.
    proc,stream,port,observations=start_server(root,out/'server-restarted.txt')
    try:
        code,response=request(port,'/generate',payload)
        assert code==200 and response['model_id']==manifest['model_id'] and response['runtime_sha256']==manifest['runtime_sha256']
        atomic_bytes(out/'real-reload.json',canonical({'synthetic':False,'status':code,'health_ready':observations,'response':response})+b'\n')
    finally:stop_server(proc,stream)
    print('Real smoke, invalid-input checks, load and process reload verified.',flush=True)


if __name__=='__main__':main()
