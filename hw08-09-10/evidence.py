"""Reproduce red/green proofs without running the owner's make check command."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

PROJECT=Path(__file__).resolve().parent
ORIGINAL='f40eae0'


def main():
    out=PROJECT/'docs/evidence';out.mkdir(parents=True,exist_ok=True)
    records=[]
    with tempfile.TemporaryDirectory(prefix='hw8910-original-') as tmp:
        baseline=Path(tmp)
        for name in ['release.py','lab.py','service.py']:
            (baseline/name).write_bytes(subprocess.check_output(['git','show',f'{ORIGINAL}:hw08-09-10/{name}'],cwd=PROJECT))
        jobs=[('before',str(PROJECT/'tests_integration'),{'HW8910_PROJECT':str(baseline)},1),
              ('before-contracts',str(PROJECT/'tests'),{'PYTHONPATH':str(baseline)},1),
              ('contracts',str(PROJECT/'tests'),{},0),
              ('after-stdlib',str(PROJECT/'tests_integration'),{'HW8910_HTTP_ENGINE':'stdlib'},0),
              ('after-fastapi',str(PROJECT/'tests_integration'),{'HW8910_HTTP_ENGINE':'fastapi'},0)]
        for label,directory,extra,expected in jobs:
            # Baseline contracts contain only the original, unmodified public tests.
            if label=='before-contracts':
                testdir=baseline/'tests';testdir.mkdir()
                (testdir/'test_release.py').write_bytes((PROJECT/'tests/test_release.py').read_bytes())
                directory=str(testdir)
            cwd=baseline if label=='before-contracts' else PROJECT
            command=[sys.executable,'-m','unittest','discover','-s',directory,'-v']
            start=time.perf_counter()
            result=subprocess.run(command,cwd=cwd,env={**os.environ,**extra},text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.txt')).write_text(result.stdout+'\nEXIT_CODE='+str(result.returncode)+'\n')
            records.append({'label':label,'command':command,'exit_code':result.returncode,'seconds':time.perf_counter()-start})
            print(label,result.returncode,flush=True)
            if bool(result.returncode)!=bool(expected):raise RuntimeError('Unexpected result: '+label)
    diff=subprocess.check_output(['git','diff',ORIGINAL,'--','hw08-09-10/release.py','hw08-09-10/lab.py','hw08-09-10/service.py','hw08-09-10/backend.py'],cwd=PROJECT.parent)
    (out/'fixes.diff').write_bytes(diff)
    (out/'test-runs.json').write_text(json.dumps({'original_commit':ORIGINAL,'runs':records},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
