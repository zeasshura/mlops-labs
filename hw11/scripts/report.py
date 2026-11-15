"""Build tables, four scientific figures, and an HTML report from actual saved evidence."""
import collections
import csv
import html
import json
import math
import os
from pathlib import Path
import statistics
from datetime import datetime
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab import ROOT
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.runtime/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

RESULTS=ROOT/'results'
FIGURES=RESULTS/'figures'


def read(path):return json.loads(Path(path).read_text())

def lines(path):return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def percentile(values,p=.95):
    data=sorted(v for v in values if v is not None and math.isfinite(v))
    if not data:return None
    n=(len(data)-1)*p;lo=math.floor(n);hi=math.ceil(n)
    return data[lo]+(data[hi]-data[lo])*(n-lo)


def normalized(row):
    result=dict(row)
    # Preserve a discovered client accounting defect in its raw log, correct only the derived classification.
    if row.get('error')=='queue deadline':
        result.update(outcome='deadline',ttfc_seconds=None,parts=0)
    return result


def summarize(label,rows,meta=None):
    rows=[normalized(r) for r in rows];ok=[r for r in rows if r['outcome']=='completed']
    counts=collections.Counter(r['outcome'] for r in rows)
    per_pod={}
    for pod in sorted({r.get('pod') for r in rows if r.get('pod')}):
        subset=[r for r in rows if r.get('pod')==pod];good=[r for r in subset if r['outcome']=='completed']
        per_pod[pod]={'sent':len(subset),'completed':len(good),'rejected':sum(r['outcome']=='rejected' for r in subset),
                      'ttfc_p95':percentile([r.get('ttfc_seconds') for r in good]),
                      'queue_p95':percentile([r.get('queue_seconds') for r in good]),
                      'cache_hit_fraction':sum(r.get('cache_hit') is True for r in good)/len(good) if good else None}
    batch=max((r['sent_epoch']+r['duration_seconds'] for r in rows),default=0)-min((r['scheduled_epoch'] for r in rows),default=0)
    return {'run_id':label,'batch_seconds':batch,'completed_requests_per_second':len(ok)/batch if batch>0 else None,'planned':meta['planned'] if meta else len(rows),'sent':len(rows),'completed':len(ok),
            'rejected':counts['rejected'],'aborted':counts['aborted'],'deadline':counts['deadline'],'unsent':(meta['planned']-len(rows)) if meta else 0,
            'http_5xx':sum(r['status']>=500 for r in rows),'fail_fraction':(len(rows)-len(ok))/len(rows) if rows else None,
            'ttfc_p50':percentile([r.get('ttfc_seconds') for r in ok],.5),'ttfc_p95':percentile([r.get('ttfc_seconds') for r in ok]),
            'full_p50':percentile([r.get('duration_seconds') for r in ok],.5),'full_p95':percentile([r.get('duration_seconds') for r in ok]),
            'max_send_lag_seconds':max((r.get('send_lag_seconds',0) for r in rows),default=0),
            'worst_pod_share':max((v['sent'] for v in per_pod.values()),default=0)/len(rows) if rows else None,'per_pod':per_pod}


def save_figure(fig,name):
    fig.tight_layout();fig.savefig(FIGURES/(name+'.png'),dpi=180);fig.savefig(FIGURES/(name+'.svg'));plt.close(fig)


def figure_rollout(runs,meta,timeline):
    controlled='A-matched-broken' in runs
    labels=['A-matched-broken','A-matched-fixed','A-rollout'] if controlled else ['A-warmup-before','A-warmup-after','A-rollout']
    titles=['Ранняя готовность: исходный дефект','Исправленные probes','Штатный rollout A → B: 2 слота']
    fig,axes=plt.subplots(3,1,figsize=(12,10))
    for ax,label,title in zip(axes,labels,titles):
        m=meta[label];start=m['start_epoch']-5;end=m['end_epoch']+2
        relevant=[r for r in timeline if start<=r['epoch']<=end and 'pods' in r]
        ax.step([r['epoch']-start for r in relevant],[sum(p['ready'] and not p['deleting'] for p in r['pods']) for r in relevant],where='post',label='Ready Pod')
        ax.step([r['epoch']-start for r in relevant],[sum(bool(e['conditions'].get('ready')) for e in r.get('endpoints',[])) for r in relevant],where='post',label='Ready EndpointSlice',linestyle='--')
        premature=[r for r in runs[label] if r.get('warmup_finished_at_accept') is False]
        if premature:ax.scatter([r['sent_epoch']-start for r in premature],[-.15]*len(premature),c='red',marker='x',label='Запрос принят до прогрева')
        if label=='A-rollout':
            long=read(RESULTS/'rolling-long-stream.json');r=long['request']
            ax.axvline(long['rollout_start_epoch']-start,color='black',ls=':',label='Начало обновления')
            ax.plot([r['sent_epoch']-start,r['sent_epoch']+r['duration_seconds']-start],[-.35,-.35],lw=5,color='green',label='Длинный поток: все 64 части')
        ax.set(title=title,xlabel='Время от начала фазы, с',ylabel='Число Ready');ax.set_ylim(-.6,3.5);ax.grid(alpha=.25);ax.legend(fontsize=8,loc='upper right')
    save_figure(fig,'01-warmup-rollout')


def figure_pods(runs):
    fig,axes=plt.subplots(2,2,figsize=(13,8),sharex=True)
    for col,label in enumerate(['B-normal-hot-1','B-affinity-hot-1']):
        rows=runs[label]
        for pod in sorted({r.get('pod') for r in rows if r.get('pod')}):
            points=[r for r in rows if r.get('pod')==pod and r['outcome']=='completed']
            axes[0,col].scatter([r['actual_offset'] for r in points],[r['ttfc_seconds'] for r in points],s=9,label=pod)
            axes[1,col].scatter([r['actual_offset'] for r in points],[r.get('queue_seconds',0) for r in points],s=9,label=pod)
        rejected=[r for r in rows if r['outcome']!='completed']
        if rejected:axes[0,col].scatter([r['actual_offset'] for r in rejected],[0]*len(rejected),marker='x',c='red',s=12,label=f'Отказы: {len(rejected)}')
        axes[0,col].set_title('Без affinity' if col==0 else 'ClientIP affinity')
        axes[0,col].set_ylabel('TTFC успешного ответа, с');axes[1,col].set_ylabel('Ожидание в очереди, с')
        axes[1,col].set_xlabel('Фактическое время отправки от старта, с')
        for ax in axes[:,col]:ax.grid(alpha=.25);ax.legend(fontsize=7)
    fig.suptitle('80% трафика через одного клиента; первый из трёх 120-секундных прогонов',fontsize=12)
    save_figure(fig,'02-pod-latency-queue')


def figure_policies(summaries):
    fig,axes=plt.subplots(2,2,figsize=(12,8))
    policies=['normal','affinity','fixed']
    for col,traffic in enumerate(['uniform','hot']):
        for row,(metric,label,scale) in enumerate([('ttfc_p95','p95 TTFC успешных ответов, с',1),('fail_fraction','Неуспешных попыток, %',100)]):
            ax=axes[row,col]
            for i,policy in enumerate(policies):
                values=[summaries[f'B-{policy}-{traffic}-{rep}'][metric]*scale for rep in range(1,4)]
                ax.bar(i,statistics.mean(values),color=['#377eb8','#e41a1c','#4daf4a'][i],alpha=.5)
                ax.scatter([i-.12,i,i+.12],values,color='black',s=25,zorder=3)
            ax.set_xticks(range(3),['None','ClientIP','Исправление: None']);ax.set_ylabel(label);ax.grid(axis='y',alpha=.3)
            if row==0:ax.set_title('Равномерный трафик' if traffic=='uniform' else '80% через одного клиента')
    fig.suptitle('Каждая точка — самостоятельный прогон 120 с; столбец — среднее трёх значений',fontsize=11)
    save_figure(fig,'03-three-repeats-policies')


def figure_hpa(runs,meta,timeline):
    start=read(RESULTS/'hpa-evidence.json')['initial']['epoch']
    selected=[r for r in timeline if r.get('phase','').startswith('C-') and r.get('hpa') and r['epoch']>=start]
    if not selected:raise RuntimeError('No real HPA observations; do not fabricate a scaling plot')
    origin=min(r['epoch'] for r in selected);x=[r['epoch']-origin for r in selected]
    fig,axes=plt.subplots(3,1,figsize=(12,10),sharex=True)
    axes[0].step(x,[sum(not p['deleting'] for p in r['pods']) for r in selected],where='post',label='Существующие Pod без удаления')
    axes[0].step(x,[r['hpa'].get('desiredReplicas',0) for r in selected],where='post',label='HPA desired',ls='--')
    axes[0].step(x,[sum(p['ready'] and not p['deleting'] for p in r['pods']) for r in selected],where='post',label='Ready')
    axes[0].set_ylabel('Реплики');axes[0].set_yticks([2,3]);axes[0].legend()
    cpu=[]
    for r in selected:
        values=[v.get('resource',{}).get('current',{}).get('averageUtilization') for v in r['hpa'].get('currentMetrics',[]) if v.get('resource',{}).get('name')=='cpu']
        cpu.append(next((v for v in values if v is not None),float('nan')))
    axes[1].plot(x,cpu,label='Средняя CPU / requests');axes[1].axhline(70,color='red',ls='--',label='Цель 70%');axes[1].set_ylabel('CPU utilisation, %');axes[1].legend()
    for label in ['C-cpu-pressure','C-hot-affinity']:
        rows=runs[label];buckets=collections.Counter(int((r['sent_epoch']-origin)//5) for r in rows)
        grid=range(0,int(max(x)//5)+2)
        axes[2].step([i*5 for i in grid],[buckets.get(i,0)/5 for i in grid],where='post',label=label)
    axes[2].set(ylabel='Фактически отправлено, запросов/с',xlabel='Время от начала опыта C, с');axes[2].legend()
    for ax in axes:ax.grid(alpha=.3)
    save_figure(fig,'04-hpa-load')


def html_table(headers,rows):
    def cell(value):
        if value is None:return '—'
        if isinstance(value,float):return f'{value:.3f}'
        return html.escape(str(value))
    return '<table><thead><tr>'+''.join('<th>'+cell(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+cell(v)+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table>'


def main():
    FIGURES.mkdir(parents=True,exist_ok=True)
    paths=sorted((RESULTS/'runs').glob('*.jsonl'))
    runs={p.stem:lines(p) for p in paths}
    meta={p.name.removesuffix('-meta.json'):read(p) for p in (RESULTS/'runs').glob('*-meta.json')}
    for label,filename,key in [('A-long-stream','rolling-long-stream.json','request'),('A-long-stream-before-fix','rolling-long-stream-before-fix.json','request'),('A-forced-termination','forced-termination-request.json',None)]:
        value=read(RESULTS/filename);row=value[key] if key else value;runs[label]=[row]
    if (RESULTS/'forced-termination-before-handshake.json').exists():runs['A-force-invalid-precheck']=[read(RESULTS/'forced-termination-before-handshake.json')]
    if (RESULTS/'forced-recovery-attempts.jsonl').exists():runs['A-force-recovery']=lines(RESULTS/'forced-recovery-attempts.jsonl')
    forced=runs['A-forced-termination'][0]
    assert forced['parts']>0 and not forced['complete']
    long=read(RESULTS/'rolling-long-stream.json')
    assert long['request']['sent_epoch'] < long['rollout_start_epoch'] < long['request']['sent_epoch']+long['request']['duration_seconds']
    required=[f'B-{p}-{t}-{r}' for p in ['normal','affinity','fixed'] for t in ['uniform','hot'] for r in range(1,4)]
    if not all(label in runs for label in required):raise RuntimeError('The 18 required real runs are not all present')
    if not (RESULTS/'hpa-evidence.json').exists():raise RuntimeError('HPA experiment is not finished')
    if not (RESULTS/'warmup-matched-comparison.json').exists():raise RuntimeError('Final matched warmup comparison is not finished')
    for label in required:
        assert meta[label]['duration_seconds']>=120
        assert len(runs[label])==meta[label]['planned']
    for traffic in ['uniform','hot']:
        assert len({meta[label]['schedule_sha256'] for label in required if '-'+traffic+'-' in label})==1
    summaries={name:summarize(name,rows,meta.get(name)) for name,rows in runs.items()}
    (RESULTS/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    fields=['evidence_run','attempt_id','request_id','client','scheduled_epoch','sent_epoch','send_monotonic','first_monotonic','finish_monotonic',
            'scheduled_offset','actual_offset','send_lag_seconds','status','outcome','original_outcome','pod','model_id','backend_mode','prompt_chars',
            'requested_chunks','parts','ttfc_seconds','duration_seconds','queue_seconds','cache_hit','complete','error','inter_chunk_seconds']
    with (RESULTS/'requests.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader()
        for name,rows in runs.items():
            for original in rows:
                row=normalized(original);out={key:row.get(key) for key in fields}
                out.update(evidence_run=name,attempt_id=name+':'+row['request_id'],original_outcome=original['outcome'],inter_chunk_seconds=json.dumps(row.get('inter_chunk_seconds',[])))
                writer.writerow(out)
    flat_fields=['run_id','batch_seconds','completed_requests_per_second','planned','sent','completed','rejected','aborted','deadline','unsent','http_5xx','fail_fraction','ttfc_p50','ttfc_p95','full_p50','full_p95','max_send_lag_seconds','worst_pod_share']
    with (RESULTS/'run-summary.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=flat_fields,extrasaction='ignore',lineterminator='\n');writer.writeheader();writer.writerows(summaries.values())
    timeline=lines(RESULTS/'timeline.jsonl')
    c_start=read(RESULTS/'hpa-evidence.json')['initial']['epoch']
    c_rows=[r for r in timeline if r.get('phase','').startswith('C-') and 'pods' in r and r['epoch']>=c_start]
    events={}
    if c_rows:
        origin=min(r['epoch'] for r in c_rows)
        for r in c_rows:
            for pod in r['pods']:
                name=pod['name'];created=datetime.fromisoformat(pod['created'].replace('Z','+00:00')).timestamp()
                event=events.setdefault(name,{'pod':name,'created_epoch':created,'first_seen_epoch':r['epoch'],'first_ready_epoch':None,'new_during_C':created>=origin})
                if pod['ready'] and not pod['deleting'] and event['first_ready_epoch'] is None:event['first_ready_epoch']=r['epoch']
        for event in events.values():event['creation_to_ready_seconds']=(event['first_ready_epoch']-event['created_epoch']) if event['new_during_C'] and event['first_ready_epoch'] else None
    with (RESULTS/'scaling-events.csv').open('w',newline='') as stream:
        fields=['pod','created_epoch','first_seen_epoch','first_ready_epoch','new_during_C','creation_to_ready_seconds']
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(events.values())
    figure_rollout(runs,meta,timeline);figure_pods(runs);figure_policies(summaries);figure_hpa(runs,meta,timeline)
    comparison=[]
    for label in required:
        source=RESULTS/'runs'/(label+'-prometheus.json')
        if not source.exists():continue
        result=read(source)
        for metric,client_metric in [('hw11_ttfc_seconds','ttfc_p95'),('hw11_duration_seconds','full_p95')]:
            for sample in result[metric].get('data',{}).get('result',[]):
                pod=sample['metric'].get('pod');value=float(sample['value'][1])
                subset=[r for r in runs[label] if r.get('pod')==pod and r['outcome']=='completed']
                actual=percentile([r.get('ttfc_seconds' if 'ttfc' in metric else 'duration_seconds') for r in subset])
                comparison.append({'run':label,'pod':pod,'metric':metric,'client_n':len(subset),'client_p95_seconds':actual,
                                   'prometheus_p95_seconds':value if math.isfinite(value) else None})
    with (RESULTS/'prometheus-client-comparison.csv').open('w',newline='') as stream:
        fields=list(comparison[0]) if comparison else ['run','pod','metric','client_n','client_p95_seconds','prometheus_p95_seconds']
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(comparison)
    hpa=read(RESULTS/'hpa-evidence.json')
    alerts=lines(RESULTS/'alert-states.jsonl')
    alert_states={name:sorted({row.get('states',{}).get(name,{}).get('state') for row in alerts if row.get('states',{}).get(name,{}).get('state')}) for name in ['HighFirstChunkLatency','HighFailureFraction']}
    summary_rows=[[name,summaries[name]['completed'],summaries[name]['rejected'],summaries[name]['deadline'],summaries[name]['ttfc_p50'],summaries[name]['ttfc_p95'],summaries[name]['full_p95'],summaries[name]['completed_requests_per_second'],summaries[name]['fail_fraction']*100] for name in required]
    table=html_table(['Прогон','Успехи','Отказы','Deadline','TTFC p50, с','TTFC p95, с','Полный p95, с','Успехов/с','Ошибок, %'],summary_rows)
    cohort_counts=sum(len(runs[label]) for label in required)
    warm=read(RESULTS/'warmup-matched-comparison.json') if (RESULTS/'warmup-matched-comparison.json').exists() else None
    placeholders={'TABLE':table,'B_ATTEMPTS':str(cohort_counts),'HPA_DOWN_1':f"{hpa['first_scale_down']['wait_seconds']:.1f}",
       'HPA_DOWN_2':f"{hpa['final_scale_down']['wait_seconds']:.1f}",'ALERTS':html.escape(json.dumps(alert_states,ensure_ascii=False)),
       'WARM_BAD':str(warm['broken']['premature'] if warm else read(RESULTS/'warmup-regression-before.json')['premature_responses']),
       'WARM_GOOD':str(warm['fixed']['premature'] if warm else 0)}
    footprint=read(RESULTS/'footprint.json')
    gib=1024**3
    own_volumes=sum(v['apparent_bytes'] for v in footprint['own_node_volumes'])
    placeholders['FOOTPRINT']=(f"Фактически: каталог работы вместе с игнорируемыми средами и архивами — {footprint['task_directory_apparent_bytes']/gib:.2f} GiB; "
        f"собственный том узла kind (/var, включая внутренний containerd) — {own_volumes/gib:.2f} GiB apparent size; "
        f"изменение свободного места на общем диске — {(footprint['disk_free_bytes_before']-footprint['disk_free_bytes_after'])/gib:.2f} GiB. "
        "Последнее число включает общие кеши и фоновую активность хоста; виртуальные размеры образов не складываются с ним.")
    document=(ROOT/'docs/report-template.html').read_text()
    for key,value in placeholders.items():document=document.replace('{{'+key+'}}',value)
    (ROOT/'report.html').write_text(document)
    print('Four figures, raw CSV, per-run summaries, Prometheus comparison and HTML report generated.',flush=True)


if __name__=='__main__':main()
