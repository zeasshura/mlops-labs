"""Automated Prefect process-boundary experiments and real release rejection."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler
from release import digest

PROJECT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser();p.add_argument('--real',action='store_true');p.add_argument('--port',type=int,default=4208);p.add_argument('--workspace',type=Path);p.add_argument('--crash-workspace',type=Path)
    args=p.parse_args();out=PROJECT/'docs/evidence';out.mkdir(exist_ok=True,parents=True)
    env={**os.environ,'PREFECT_HOME':str(PROJECT/'.prefect'),'PREFECT_SERVER_ANALYTICS_ENABLED':'false',
         'PREFECT_API_URL':f'http://127.0.0.1:{args.port}/api'}
    server_output=(out/'prefect-server.txt').open('w')
    server=subprocess.Popen([str(PROJECT/'.venv/bin/prefect'),'server','start','--host','127.0.0.1','--port',str(args.port)],
                            cwd=PROJECT,env=env,stdout=server_output,stderr=server_output)
    records=[]
    def invoke(label,root,flags=(),expected=0):
        pointer=root/'accepted.json'
        before=digest(pointer.read_bytes()) if pointer.exists() else None
        cmd=[sys.executable,str(PROJECT/'flow.py'),'--workspace',str(root),*flags]
        result=subprocess.run(cmd,cwd=PROJECT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
        (out/(label+'.txt')).write_text(result.stdout+'\nEXIT_CODE='+str(result.returncode)+'\n')
        after=digest(pointer.read_bytes()) if pointer.exists() else None
        records.append({'label':label,'command':cmd,'exit_code':result.returncode,'accepted_before_sha256':before,'accepted_after_sha256':after})
        print(label,result.returncode,flush=True)
        if bool(result.returncode)!=bool(expected):raise RuntimeError('Unexpected flow result: '+label+'\n'+result.stdout[-2000:])
        return before,after
    try:
        deadline=time.monotonic()+90
        while True:
            if server.poll() is not None:raise RuntimeError('Prefect server exited: '+(out/'prefect-server.txt').read_text()[-2000:])
            try:
                with build_opener(ProxyHandler({})).open(env['PREFECT_API_URL']+'/health',timeout=2) as r:
                    if r.status==200:break
            except (URLError,TimeoutError):pass
            if time.monotonic()>deadline:raise TimeoutError('Prefect startup timeout')
            time.sleep(.3)
        if args.real:
            root=args.workspace.resolve() if args.workspace else PROJECT/'.runtime/real'
            invoke('real-prefect-baseline',root,['--role','baseline'])
            before,after=invoke('real-prefect-candidate-reject',root,['--role','candidate'],1)
            assert before==after,'Rejected real candidate changed the pointer'
            (PROJECT/'docs/real/accepted.json').write_bytes((root/'accepted.json').read_bytes())
        else:
            root=args.workspace.resolve() if args.workspace else PROJECT/'.lab-flow-evidence'
            subprocess.run([sys.executable,str(PROJECT/'lab.py'),'--workspace',str(root),'init'],check=True,cwd=PROJECT)
            before,after=invoke('prefect-failed',root,['--fail-after-prepare'],1);assert before==after
            invoke('prefect-resumed',root)
            before,after=invoke('prefect-repeated',root);assert before==after
            assert len((root/'publications.jsonl').read_text().splitlines())==1
            (root/'input.txt').write_text('Modified bytes at the same path\n')
            invoke('prefect-input-changed',root)
            assert len(list((root/'cache').glob('*.json')))==2
            crash=args.crash_workspace.resolve() if args.crash_workspace else PROJECT/'.lab-flow-crash'
            subprocess.run([sys.executable,str(PROJECT/'lab.py'),'--workspace',str(crash),'init'],check=True,cwd=PROJECT)
            invoke('prefect-pointer-crash',crash,['--fail-after-pointer'],1)
            invoke('prefect-pointer-recovered',crash)
            invoke('prefect-pointer-repeated',crash)
            assert len((crash/'publications.jsonl').read_text().splitlines())==1
            records.append({'pointer_crash_events':1,'pointer_crash_recovered':not (crash/'pending-release.json').exists()})
        (out/('real-flow-runs.json' if args.real else 'flow-runs.json')).write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    finally:
        server.terminate()
        try:server.wait(timeout=15)
        except subprocess.TimeoutExpired:server.kill();server.wait()
        server_output.close()


if __name__=='__main__':main()
