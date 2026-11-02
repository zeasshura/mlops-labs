"""Real A+B pipeline; final acceptance checks are deliberately left to the user."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
(ROOT/'logs').mkdir(exist_ok=True)
(ROOT/'metrics').mkdir(exist_ok=True)
ENV = dict(os.environ, OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', PYTHONUNBUFFERED='1',
           PYTHONPATH=str(ROOT), PATH=str(ROOT/'tools')+os.pathsep+str(ROOT/'.venv/bin')+os.pathsep+os.environ['PATH'])
ENV['NO_PROXY'] = ENV['no_proxy'] = '127.0.0.1,localhost,' + ENV.get('NO_PROXY', '')
status_path=Path('metrics/pipeline-status.json')
status = (json.loads(status_path.read_text()) if '--resume' in sys.argv and status_path.exists()
          else dict(started_utc=datetime.now(timezone.utc).isoformat(), stages=[]))
status['state']='running'
status.pop('error',None)
status.pop('finished_utc',None)

def save():
    Path('metrics/pipeline-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')

def run(name, args, allowed=()):
    previous=next((s for s in reversed(status['stages']) if s['name']==name),None)
    if '--resume' in sys.argv and previous and (previous['exit_code']==0 or previous['exit_code'] in allowed):
        print(f'Уже выполнено: {name}',flush=True)
        return previous['exit_code']
    status['current_stage']=name; save()
    print(f'Запуск {name}',flush=True)
    with Path(f'logs/{name}.log').open('w') as log:
        code=subprocess.call(args,env=ENV,stdout=log,stderr=subprocess.STDOUT)
    status['stages'].append(dict(name=name,exit_code=code,log=f'logs/{name}.log'));save()
    if code and code not in allowed:
        raise RuntimeError(f'{name}: exit {code}, см. logs/{name}.log')
    return code

PYTHON=sys.executable
try:
    run('sweep',[PYTHON,'-m','src.sweep'])
    run('report',[PYTHON,'-m','src.report'])
    run('candidate',[PYTHON,'-m','evaluation.cli','candidate'])
    if not Path('evaluation/baseline.json').exists():
        run('baseline-init',[PYTHON,'-m','evaluation.cli','baseline-init'])
    run('evaluate',[PYTHON,'-m','evaluation.cli','evaluate'])
    gate_code=run('quality-gate',[PYTHON,'-m','evaluation.cli','gate'],allowed=(1,))
    run('negative-gate',[PYTHON,'-m','evaluation.cli','negative'])
    if gate_code==0:
        run('promote',[PYTHON,'-m','evaluation.cli','promote'])
    else:
        print('Качество не прошло: champion не назначается; candidate остаётся доступным.',flush=True)
    run('storage-proof',[PYTHON,'scripts/prove_storage.py'])
    run('finalize',[PYTHON,'scripts/finalize_reports.py'])
    status.update(state='completed',check='manual_pending')
except Exception as exc:
    status.update(state='failed',error=str(exc))
    print(str(exc),file=sys.stderr,flush=True)
finally:
    status['finished_utc']=datetime.now(timezone.utc).isoformat();save()
sys.exit(0 if status['state']=='completed' else 1)
