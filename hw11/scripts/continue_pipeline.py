import os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
log=ROOT/'results/experiment-A-repeat.txt'
deadline=time.monotonic()+600
while 'Experiment A verified:' not in log.read_text():
 if 'Traceback' in log.read_text():raise RuntimeError('Experiment A failed; pipeline stopped')
 if time.monotonic()>deadline:raise TimeoutError('Waiting for Experiment A')
 time.sleep(3)
with (ROOT/'results/kubernetes-tests.txt').open('w') as out:
 result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_kubernetes.py','-v'],
                       cwd=ROOT,env={**os.environ,'HW11_K8S_TESTS':'1'},stdout=out,stderr=out)
if result.returncode:raise RuntimeError('Kubernetes checks failed; no matrix launched')
print('Five Kubernetes checks passed; beginning full matrix.',flush=True)
subprocess.run([sys.executable,'-u','scripts/run_matrix.py'],cwd=ROOT,check=True)

subprocess.run([sys.executable,'-u','scripts/experiment_c.py'],cwd=ROOT,check=True)
