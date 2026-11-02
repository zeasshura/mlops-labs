"""Publish measured evidence and package the hand-in without model weights."""
import csv
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
read=lambda p:json.loads(Path(p).read_text())
from mlflow import MlflowClient
from src.common import connect,load_params
p=load_params();connect(p);client=MlflowClient()
a,b=[read(f'metrics/{role}-eval.json') for role in ('baseline','candidate')]
gate=read('metrics/quality-gate.json');negative=read('metrics/negative-gate.json');storage=read('metrics/storage-check.json')
candidate=read('metrics/candidate-model.json');sweep=read('metrics/sweep.json')
rows=list(csv.DictReader(Path('docs/comparison.csv').open()))
def run_url(run_id):
    run=client.get_run(run_id)
    return f"{p['tracking']['uri']}/#/experiments/{run.info.experiment_id}/runs/{run_id}"
# A fresh isolated process has neither project cwd nor access to local params.yaml.
expected=client.download_artifacts(candidate['run_id'],'samples.json')
sample=read(expected)['data'][0]
if '--reuse-proof' in sys.argv:
    proof=read('metrics/reload-proof.json')
    assert proof['passed'] and proof['isolated'] and proof['offline_base']
    assert proof['uri']==candidate['uri'] and proof['prompt']==sample[0]
    assert proof['expected']==proof['actual']==sample[1]
    output=[proof['actual']]
else:
    with tempfile.TemporaryDirectory(prefix='hw67-isolated-') as cwd:
        env=dict(os.environ,OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',HF_HUB_OFFLINE='1')
        proc=subprocess.run([sys.executable,'-I',str(ROOT/'src/predict.py'),'--tracking-uri',p['tracking']['uri'],
                             '--uri',candidate['uri'],'--prompt',sample[0]],cwd=cwd,env=env,capture_output=True,text=True,timeout=240)
        if proc.returncode:
            raise RuntimeError('Изолированная загрузка не прошла: '+proc.stderr[-1500:])
        output=json.loads(proc.stdout.strip().splitlines()[-1]);assert output==[sample[1]]
    proof=dict(passed=True,uri=candidate['uri'],isolated=True,offline_base=True,prompt=sample[0],expected=sample[1],actual=output[0])
Path('metrics/reload-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
from evaluation.contract import fingerprint, write_json
from evaluation.solution import score, quality_gate
golden_rows=[json.loads(x) for x in Path('data/eval/golden.jsonl').read_text().splitlines()]
original=fingerprint(read('metrics/candidate-outputs.json'))
corrupted=[dict(id=r['id'],raw=json.dumps({'answer':next(c for c in r['choices'] if c!=r['expected'])}),error=None)
           for r in golden_rows]
broken=copy.deepcopy(b)
broken.update(score(golden_rows,corrupted))
try:
    quality_gate(a,broken,read('evaluation/params.json')['critical_slices'])
except ValueError as exc:
    consistent_negative=dict(rejected=True,reason=str(exc),overall=broken['overall'],
                             original_outputs_unchanged=original==fingerprint(read('metrics/candidate-outputs.json')),
                             note='Only a copy was corrupted; valid JSON labels deliberately changed to wrong labels. Counts remain consistent. No model generation or alias mutation.')
else:
    raise RuntimeError('Согласованная отрицательная копия неожиданно прошла gate')
assert consistent_negative['original_outputs_unchanged']
write_json('metrics/negative-consistent-gate.json',consistent_negative)
write_json('metrics/negative-copy-outputs.json',corrupted)
lines=['\n## Фактические результаты','',f"Sweep: `{sweep['parent_id']}`. Candidate: `{candidate['uri']}`, run `{candidate['run_id']}`.",'',
       '| Конфигурация | r | lr | Base loss | Final loss | Время, с | RSS, МБ | Адаптер, МБ |',
       '|---|---:|---:|---:|---:|---:|---:|---:|']
for r in rows:
    lines.append('| '+' | '.join(str(r[k]) for k in ('name','r','lr','base_val_loss','final_val_loss','seconds','peak_memory_mb','adapter_mb'))+' |')
lines += ['', '### MLflow runs', '']
for row in rows:
    lines.append(f"- [{row['name']}]({run_url(row['run_id'])})")
lines += [f"- [Оценка baseline/candidate]({run_url(b['evaluation_run_id'])})"]
lines+=['',f"Baseline: `{json.dumps(a['model'],ensure_ascii=False)}`.",f"Evaluation run: `{b['evaluation_run_id']}`.",'',
        '| Версия / срез | n | correct | valid | errors | accuracy | format_rate |','|---|---:|---:|---:|---:|---:|---:|']
for role,report in [('baseline',a),('candidate',b)]:
    for name,m in [('overall',report['overall']),*sorted(report['slices'].items())]:
        lines.append('| '+role+'/'+name+' | '+' | '.join(str(m[k]) for k in ('n','correct','valid','errors','accuracy','format_rate'))+' |')
diff=read('metrics/eval-diff.json')
lines+=['',f"Исправленные ID: {diff['improved']}.",f"Потерянные ID: {diff['regressed']}.",'','### Behavioral','']
for x,y in zip(a['behavioral']['per_item'],b['behavioral']['per_item']):
    lines.append(f"- `{x['id']}`: baseline correct={x['correct']}, candidate correct={y['correct']}; raw baseline={x['raw']!r}, candidate={y['raw']!r}.")
lines+=['','### Разбор пяти пар ответов','']
by_a={x['id']:x for x in a['per_item']};by_b={x['id']:x for x in b['per_item']}
golden={json.loads(x)['id']:json.loads(x) for x in Path('data/eval/golden.jsonl').read_text().splitlines()}
representatives=[next(x['id'] for x in a['per_item'] if name in x['slices']) for name in sorted(a['slices'])]
ids=list(dict.fromkeys(representatives+diff['regressed']+diff['improved']+[x['id'] for x in a['per_item']]))[:5]
for key in ids:
    x,y=by_a[key],by_b[key];task=golden[key]
    lines += [f"**{key}**. Вопрос: {task['input'].split('Question:',1)[1].split('Choices:',1)[0].strip()}",
              f"Эталон: `{task['expected']}` ({task['source']['answer_text']}). База: `{x['raw']}`; кандидат: `{y['raw']}`.",
              f"Формат база/кандидат: {x['valid']}/{y['valid']}; правильность: {x['correct']}/{y['correct']}. "+
              ('Ответ кандидата не соблюдает контракт JSON-объекта answer. Даже верная отдельная буква не засчитывается: формат является частью задачи.' if not y['valid'] else
               'Кандидат потерял правильный ответ; валидная JSON-метка не совпала с эталоном.' if x['correct'] and not y['correct'] else
               'Кандидат исправил ответ; это подтверждено эталоном из исходного пассажа.' if not x['correct'] and y['correct'] else
               'Обе версии проверены по одному эталону; совпадение ответов само по себе не заменяет проверку правильности.'),'']
lines+=['### Решение','',f"Gate: `{json.dumps(gate,ensure_ascii=False)}`.",
        'Кандидат принят в champion.' if gate['passed'] else 'Кандидат НЕ принят в champion. Alias candidate сохранён; baseline не изменён. Следующий шаг — изучить проваленные ответы и формат, подготовить новый эксперимент без ослабления текущего gate.',
        f"Отрицательный опыт: rejected={negative['rejected']}, причина: {negative['reason']}.",
        f"Дополнительная испорченная копия с согласованными counts и валидным JSON: rejected={consistent_negative['rejected']}, причина: {consistent_negative['reason']}. Исходные ответы не изменены.",
        f"Probe пережил пересоздание контейнера: run `{storage['run_id']}`, SHA256 `{storage['sha256']}`.",
        'Загрузка candidate в новом изолированном процессе без локального конфига и с offline-базой подтверждена: ответ совпал дословно.',
        'Итоговые make check / make check-all не запускались: пользователь выполняет их сам и записывает видео.','']
text='\n'.join(lines)
for name in ('conclusion.md','work_report.md'):
    f=Path('docs')/name;f.write_text(f.read_text().split('\n## Фактические результаты')[0]+text)
f=Path('docs/defects.md');s=f.read_text().split('\n## Фактические доказательства')[0]
s+='\n## Фактические доказательства\n\n'
s+=f"Шесть разных законченных runs: {', '.join(r['run_id'] for r in rows)}. Для каждого сохранены хеши train/val и кода; selector успешно проверил их перед регистрацией `{candidate['uri']}`.\n\n"
tags=client.get_run(candidate['run_id']).data.tags
s+='Версии выбранного run:\n\n'+'\n'.join(f'- `{k}`: `{tags[k]}`' for k in ('git_sha','git_dirty','code_sha256','config_sha256','data_train_sha256','data_val_sha256','base_revision'))+'\n\n'
s+=f"Probe SHA256 `{storage['sha256']}` совпал после force-recreate MLflow. Изолированная загрузка вернула `{output[0]}` в точности как samples.json.\n\n"
s+=f"Quality gate: passed={gate['passed']}; отрицательная копия отклонена: {negative['reason']}.\n"
f.write_text(s)
# Preserve small reports separately: metrics/ intentionally remains ignored by Git.
Path('submission/reports').mkdir(parents=True,exist_ok=True)
for source in Path('metrics').glob('*.json'):
    if source.name != 'pipeline-status.json':
        (Path('submission/reports')/source.name).write_bytes(source.read_bytes())
links=dict(tracking_uri=p['tracking']['uri'],sweep=sweep['parent_id'],evaluation=b['evaluation_run_id'],candidate=candidate,
           runs={r['name']:dict(run_id=r['run_id'],url=run_url(r['run_id'])) for r in rows})
Path('docs/mlflow_links.json').write_text(json.dumps(links,ensure_ascii=False,indent=2)+'\n')
with zipfile.ZipFile('submission/eval-data.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in sorted(Path('data/eval').glob('*.jsonl')):z.write(f,str(f))
# Log all decision/proof reports alongside the actual evaluation run.
for name in ('quality-gate.json','negative-gate.json','negative-consistent-gate.json','negative-copy-outputs.json','storage-check.json','reload-proof.json'):
    client.log_artifact(b['evaluation_run_id'],f'metrics/{name}','evaluation')
client.log_artifact(b['evaluation_run_id'],'docs/conclusion.md','evaluation')
Path('submission/README.txt').write_text('Дополнение к Git-репозиторию: reports/ содержит реальные метрики и raw-ответы; eval-data.zip содержит набор оценки и полный train-index. Веса и тензоры обучения отсутствуют. Разархивируйте eval-data.zip в корень проекта, затем uv run dvc add data/eval для локального восстановления кэша. Итоговые проверки и видео выполняет студент.\n')
with zipfile.ZipFile('submission/hw67-submission.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for folder in ('docs','submission/reports'):
        for file in sorted(Path(folder).rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and 'hw5-history' not in file.parts:
                archive.write(file, str(file.relative_to("submission")) if folder == "submission/reports" else str(file))
    archive.write('submission/eval-data.zip','eval-data.zip')
    archive.write('submission/README.txt','README.txt')
print('Отчёты дополнены; приложение submission/hw67-submission.zip готово без весов и тензоров.')
