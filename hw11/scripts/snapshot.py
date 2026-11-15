"""Capture versions and storage accounting without copying kubeconfig or secret data."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT,TOOLS,k,obj,command


def main():
    node=obj('get','node','mlops-hw11-control-plane')
    images={}
    names=['localhost/hw11-api:1.0.1','docker.io/library/python:3.12.12-slim','docker.io/prom/prometheus:v3.5.0',
           'docker.io/grafana/grafana:12.1.1','registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.17.0',
           'registry.k8s.io/metrics-server/metrics-server:v0.8.0']
    for name in names:
        result=command(['podman','image','inspect',name,'--format','{{json .}}'])
        data=json.loads(result.stdout)
        images[name]={key:data.get(key) for key in ['Id','Size','RepoDigests']}
    limits=json.loads(command(['podman','inspect','mlops-hw11-control-plane','--format','{{json .HostConfig}}']).stdout)
    snapshot={'epoch':time.time(),'host_python':platform.python_version(),'kind':command([TOOLS/'kind','version']).stdout.strip(),
      'helm':command([TOOLS/'helm','version','--short']).stdout.strip(),
      'kubectl':json.loads(command([TOOLS/'kubectl','version','--client','-o','json']).stdout),
      'podman':json.loads(command(['podman','version','--format','json']).stdout),
      'node_info':{key:node['status']['nodeInfo'].get(key) for key in ['architecture','containerRuntimeVersion','kernelVersion','kubeletVersion','osImage']},
      'node_capacity':node['status']['capacity'],'node_allocatable':node['status']['allocatable'],
      'actual_limits':{key:limits.get(key) for key in ['Memory','MemorySwap','CpuQuota','CpuPeriod','PidsLimit']},'images':images,
      'metrics_api':obj('get','apiservice','v1beta1.metrics.k8s.io').get('status')}
    (ROOT/'results/versions.json').write_text(json.dumps(snapshot,indent=2)+'\n')
    k('wait','pod','-l','app=hw11-api','--for=condition=Ready','--timeout=120s')
    mounts=json.loads(command(['podman','inspect','mlops-hw11-control-plane','--format','{{json .Mounts}}']).stdout)
    volumes=[]
    for mount in mounts:
        if mount['Type']=='volume':
            measured=int(command(['podman','unshare','du','-sb',mount['Source']]).stdout.split()[0])
            volumes.append({'name':mount['Name'],'destination':mount['Destination'],'apparent_bytes':measured})
    disk=shutil.disk_usage(ROOT)
    def size(path):return int(command(['du','-sb',path]).stdout.split()[0])
    footprint={'epoch':time.time(),'disk_free_bytes_after':disk.free,'disk_free_bytes_before':json.loads((ROOT/'results/preflight.json').read_text())['disk_free_bytes'],
      'task_directory_apparent_bytes':size(ROOT),'runtime_archives_and_kubeconfig_bytes':size(ROOT/'.runtime'),
      'tools_bytes':size(ROOT/'.tools'),'venv_apparent_bytes':size(ROOT/'.venv'),
      'podman_system_df':command(['podman','system','df']).stdout,
      'own_node_volumes':volumes,
      'node_size':json.loads(command(['podman','container','inspect','--size','mlops-hw11-control-plane','--format','{{json .SizeRw}}']).stdout),
      'note':'Free-space delta includes global shared caches and concurrent host activity. Image virtual sizes are not added as physical usage.'}
    (ROOT/'results/footprint.json').write_text(json.dumps(footprint,indent=2)+'\n')
    (ROOT/'results/resource-metrics.json').write_text(k('get','--raw','/apis/metrics.k8s.io/v1beta1/namespaces/hw11/pods').stdout+'\n')
    (ROOT/'results/final-state.txt').write_text(k('get','pods,svc,hpa','-o','wide').stdout)
    print('Versions, real limits, images, resource metrics and disk footprint recorded.',flush=True)


if __name__=='__main__':main()
