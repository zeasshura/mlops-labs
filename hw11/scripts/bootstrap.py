"""Task-local, checksum-verified tools. Does not change global kubeconfig or prune anything."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'.tools'
NODE='kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a'
IMAGES=['docker.io/prom/prometheus:v3.5.0','docker.io/grafana/grafana:12.1.1',
 'registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.17.0','registry.k8s.io/metrics-server/metrics-server:v0.8.0']


def fetch(url):
    with urllib.request.urlopen(url,timeout=180) as response:return response.read()


def verified(url,checksum_url):
    payload=fetch(url);expected=fetch(checksum_url).decode().split()[0]
    if hashlib.sha256(payload).hexdigest()!=expected:raise ValueError('Checksum mismatch: '+url)
    return payload


def run(args):subprocess.run(list(map(str,args)),cwd=ROOT,env={**os.environ,'KIND_EXPERIMENTAL_PROVIDER':'podman'},check=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['tools','create','preload','deploy','delete'])
    args=p.parse_args();TOOLS.mkdir(exist_ok=True);(ROOT/'.runtime').mkdir(exist_ok=True)
    if args.action=='tools':
        targets={'kind':('https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/kind-linux-amd64',
                         'https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/kind-linux-amd64.sha256sum'),
                 'kubectl':('https://dl.k8s.io/release/v1.34.0/bin/linux/amd64/kubectl','https://dl.k8s.io/release/v1.34.0/bin/linux/amd64/kubectl.sha256')}
        for name,(url,check) in targets.items():
            path=TOOLS/name;path.write_bytes(verified(url,check));path.chmod(0o755)
        archive=verified('https://get.helm.sh/helm-v3.18.6-linux-amd64.tar.gz','https://get.helm.sh/helm-v3.18.6-linux-amd64.tar.gz.sha256sum')
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            (TOOLS/'helm').write_bytes(tar.extractfile('linux-amd64/helm').read())
        (TOOLS/'helm').chmod(0o755)
    elif args.action=='create':
        run([TOOLS/'kind','create','cluster','--name','mlops-hw11','--config','kind.yaml','--image',NODE,'--kubeconfig','.runtime/kubeconfig','--wait','180s'])
        run(['podman','update','--cpu-period','100000','--cpu-quota','400000','--memory','4g','--memory-swap','4g','--pids-limit','4096','mlops-hw11-control-plane'])
    elif args.action=='preload':
        run(['podman','build','--memory','512m','--cpu-period','100000','--cpu-quota','200000','-t','localhost/hw11-api:1.0.1','.'])
        for index,image in enumerate(['localhost/hw11-api:1.0.1',*IMAGES]):
            if index:run(['podman','pull',image])
            target=ROOT/'.runtime'/f'preload-{index}.tar'
            run(['podman','save','--format','docker-archive','-o',target,image])
            run([TOOLS/'kind','load','image-archive',target,'--name','mlops-hw11'])
            target.unlink()
    elif args.action=='deploy':
        run([TOOLS/'kubectl','--kubeconfig','.runtime/kubeconfig','apply','-f','monitoring/metrics-server.yaml'])
        run([TOOLS/'helm','upgrade','--install','hw11','chart','--kubeconfig','.runtime/kubeconfig','-n','hw11','--create-namespace','--wait','--timeout','180s'])
        run([TOOLS/'kubectl','--kubeconfig','.runtime/kubeconfig','-n','hw11','rollout','status','deployment/api','--timeout=180s'])
    else:
        # Only this named cluster. Existing MLflow/Postgres and shared image caches are not removed.
        run([TOOLS/'kind','delete','cluster','--name','mlops-hw11','--kubeconfig','.runtime/kubeconfig'])


if __name__=='__main__':main()
