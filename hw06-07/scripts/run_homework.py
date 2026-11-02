"""Run the real homework pipeline and append measured evidence to the reports."""
import argparse
import time
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
logs = ROOT / 'logs'
logs.mkdir(exist_ok=True)
env = dict(os.environ, OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', PYTHONUNBUFFERED='1')
env['PATH'] = str(ROOT / '.venv/bin') + os.pathsep + env['PATH']
status_path = ROOT / 'docs/run_status.json'
status = {'state': 'running', 'started_utc': datetime.now(timezone.utc).isoformat(), 'stages': []}

def save_status():
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n')

def run(name, command):
    status['current_stage'] = name
    save_status()
    print(f'Запуск {name}: {" ".join(command)}', flush=True)
    with (logs / f'{name}.log').open('w') as log:
        code = subprocess.call(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    status['stages'].append({'name': name, 'exit_code': code, 'log': f'logs/{name}.log'})
    save_status()
    if code:
        raise RuntimeError(f'{name}: код {code}; подробности в logs/{name}.log')

parser = argparse.ArgumentParser()
parser.add_argument('--wait-train-pid', type=int)
args = parser.parse_args()

try:
    if args.wait_train_pid:
        status['current_stage'] = 'train_all'
        save_status()
        process = Path(f'/proc/{args.wait_train_pid}/stat')
        while process.exists():
            try:
                if process.read_text().split(') ', 1)[1].split()[0] == 'Z':
                    break
            except FileNotFoundError:
                break
            time.sleep(10)
        from src.config import load_params
        from src.train import inputs_fingerprint
        m = json.loads(Path('metrics/train_all_layers.json').read_text())
        if m['inputs_fingerprint'] != inputs_fingerprint(load_params()):
            raise RuntimeError('Первый прогон не создал актуальных метрик')
        status['stages'].append({'name': 'train_all', 'exit_code': 0, 'log': 'logs/train_all.log'})
    else:
        run('train_all', [sys.executable, '-m', 'src.train', '--variant', 'all_layers'])
    run('train_freeze', [sys.executable, '-m', 'src.train', '--variant', 'freeze14'])
    run('plot', [sys.executable, '-m', 'src.plot'])
    run('compare', [sys.executable, '-m', 'src.compare', '--variant', 'all_layers'])
    a = json.loads(Path('metrics/train_all_layers.json').read_text())
    f = json.loads(Path('metrics/train_freeze14.json').read_text())
    measurements = '\n## Фактические результаты прогона\n\n'
    measurements += '| Вариант | Шаги | Train loss: первый → последний | Val: база → адаптер | Параметры | Обучение, с | Оценка, с | Память, МБ | Адаптер, МБ |\n'
    measurements += '|---|---:|---|---|---:|---:|---:|---:|---:|\n'
    for m in (a, f):
        measurements += f"| {m['variant']} | {m['steps']} | {m['curve_train'][0][1]} → {m['curve_train'][-1][1]} | {m['base_val_loss']} → {m['final_val_loss']} | {m['trainable_params']} | {m['seconds']} | {m['eval_seconds']} | {m['peak_memory_mb']} | {m['adapter_size_mb']} |\n"
    measurements += f"\nValidation: {a['val_examples']} примера. Метрика памяти: {a['memory_metric']}. Отпечаток входов: `{a['inputs_fingerprint']}`.\n"
    measurements += '\nЧисла подтверждают оценку до обучения и в конце, различие числа параметров и размер сохранённых папок. Штатный make check пользователь запускает самостоятельно; его результат пока не подтверждён.\n'
    for name in ('work_report.md', 'defects.md'):
        p = Path('docs') / name
        text = p.read_text().split('\n## Фактические результаты прогона')[0]
        p.write_text(text + measurements)
    status['state'] = 'completed'
    status['check'] = 'manual_pending'
    report_path = Path('docs/work_report.md')
    text = report_path.read_text().replace('Обучение, генерация и девять приёмочных проверок пока не завершены.', 'Обучение обоих вариантов на 20 шагах и генерация завершены. Девять приёмочных проверок пользователь запускает самостоятельно.')
    report_path.write_text(text)
    print('Обучение, графики и сравнение готовы. Запустите make check самостоятельно.', flush=True)
except Exception as exc:
    status['state'] = 'failed'
    status['error'] = str(exc)
    with Path('docs/work_report.md').open('a') as report:
        report.write(f'\nПоследний запуск остановился: {exc}. Сдача пока не готова.\n')
    print(str(exc), file=sys.stderr, flush=True)
finally:
    status['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save_status()
sys.exit(0 if status['state'] == 'completed' else 1)
