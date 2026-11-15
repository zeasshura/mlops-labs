import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT,Observer,helm,k,run_load,prometheus


def main():
    helm(warmupSeconds=20,serviceAffinity='ClientIP',**{'hpa.enabled':False})
    out=ROOT/'results/matrix-progress.jsonl'
    for policy,service in [('normal','balanced'),('affinity','sticky'),('fixed','api')]:
        if policy=='fixed':
            helm(serviceAffinity='None',warmupSeconds=20,**{'hpa.enabled':False})
            (ROOT/'results/fixed-service.yaml').write_text(k('get','service','api','-o','yaml').stdout)
        for traffic in ['uniform','hot']:
            for repetition in range(1,4):
                label=f'B-{policy}-{traffic}-{repetition}'
                if (ROOT/'results/runs'/(label+'-meta.json')).exists():continue
                with Observer(label):records,metadata=run_load(label,service,traffic)
                time.sleep(6)
                window=int(time.time()-metadata['start_epoch'])+2
                prom={}
                for metric in ['hw11_ttfc_seconds','hw11_duration_seconds']:
                    prom[metric]=prometheus(f'histogram_quantile(0.95,sum by(le,pod)(increase({metric}_bucket[{window}s])))')
                prom['alerts']=__import__('lab').http('http://127.0.0.1:19090/api/v1/rules')
                (ROOT/'results/runs'/(label+'-prometheus.json')).write_text(json.dumps(prom,separators=(',',':'))+'\n')
                with out.open('a') as f:f.write(json.dumps(metadata)+'\n')
    print('All 18 full 120-second runs completed.',flush=True)


if __name__=='__main__':main()
