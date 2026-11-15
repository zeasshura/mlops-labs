"""Save bounded monitoring data for exactly the recorded workload intervals."""
import json,sys
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT,http,k,pods


def harvest():
    directory=ROOT/'results/monitoring';directory.mkdir(exist_ok=True,parents=True)
    queries={'queue':'hw11_waiting','running':'hw11_running','ready':'kube_deployment_status_replicas_ready{namespace="hw11",deployment="api"}',
             'cpu':'sum by(pod)(rate(container_cpu_usage_seconds_total{namespace="hw11",container="api"}[30s]))',
             'ram':'sum by(pod)(container_memory_working_set_bytes{namespace="hw11",container="api"})'}
    for p in sorted((ROOT/'results/runs').glob('[BC]-*-meta.json')):
        meta=json.loads(p.read_text());out={}
        if (directory/(meta['run_id']+'.json')).exists():continue
        for name,query in queries.items():
            params={'query':query,'start':meta['start_epoch'],'end':meta['end_epoch'],'step':5}
            out[name]=http('http://127.0.0.1:19090/api/v1/query_range?'+urlencode(params))
        (directory/(meta['run_id']+'.json')).write_text(json.dumps(out,separators=(',',':'))+'\n')
    for pod in pods():
        name=pod['metadata']['name']
        result=k('logs',name,'--timestamps=true',check=False)
        if result.returncode==0:(directory/(name+'-server.txt')).write_text(result.stdout)
    (directory/'targets.json').write_text(json.dumps(http('http://127.0.0.1:19090/api/v1/targets'),indent=2)+'\n')
    print('Monitoring query ranges and server request journals exported.',flush=True)


if __name__=='__main__':harvest()
