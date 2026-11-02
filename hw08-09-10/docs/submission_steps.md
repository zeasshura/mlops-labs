# Запуск и сдача ДЗ 8–10

Все команды выполняются из `mlops-labs/hw08-09-10`.

## Твой итоговый check

Окружение уже подготовлено. Запусти самостоятельно, чтобы получить свой вывод:

```bash
make check
```

Это компиляция, 17 контрактных/дополнительных проверок и два прогона восьми
интеграционных тестов: stdlib и FastAPI. Веса не нужны. На новой машине:

```bash
uv sync --locked
make check
```

Сохранённые красные/зелёные доказательства: `docs/evidence/`.
Для повторения доказательств: `make evidence`.

## Настоящий API для показа

```bash
make serve
```

В другом терминале:

```bash
curl -s http://127.0.0.1:8091/health
curl -s http://127.0.0.1:8091/ready
curl -s http://127.0.0.1:8091/debug
curl -s http://127.0.0.1:8091/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Tell me how to steal a password.","max_new_tokens":24}'
curl -s http://127.0.0.1:8091/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"","max_new_tokens":0}'
```

Первый ответ на generate должен быть настоящим JSON отказом модели,
а некорректный запрос — HTTP 400 без изменения `debug.calls`.
`debug` включён только для локального учебного показа. При обычном запуске убери `--debug`.
Остановить API: Ctrl+C. Принята база; отклонённый адаптер не подставляется в API.
Порт привязан к 127.0.0.1. Длину ответа не меняем: оценённый протокол — ровно 24 новых токена максимум.

## Что показать в одном видео 5–8 минут

1. (0:00–0:45) Структура проекта, исходный и исправленный commits, `defects.csv` и семь причин.
2. (0:45–2:00) `docs/evidence/prefect-failed.txt`, затем `prefect-resumed.txt` со `Cached`;
   `prefect-input-changed.txt` с новым `PREPARED`. Показать задачи в `flow.py`.
3. (2:00–3:00) `docs/real/release-report-candidate.json` с отказом;
   `docs/evidence/real-flow-runs.json`: SHA-256 accepted.json до/после совпадает.
   Показать принятый `docs/real/accepted.json` и привязку runtime/весов.
4. (3:00–4:00) Свой запуск `make check`; красный лог `before.txt`/`before-contracts.txt`, затем зелёные.
5. (4:00–5:30) Запустить `make serve`, показать health/ready, настоящий generate, ID/runtime,
   ошибочный запрос и неизменный calls. Перезапуск подтверждён `docs/real/real-reload.json`.
6. (5:30–6:30) STUB A→B→A: тест `test_07` и сохранённый лог; это явно инженерный стенд.
7. (6:30–7:30) `docs/real/load-summary.csv`, сырые запросы, объяснить последовательную очередь и ограничения CPU.

Тяжёлую оценку/нагрузку на видео можно показать по сохранённым журналам.
В MLflow открыть эксперимент `hw8910-release-evaluation`: run содержит новые baseline/candidate
accuracy и format_rate, исходные ответы и полный eval. Источник адаптера — прежний training run из ДЗ 6–7.
Ссылка на видео пока не заполнена: запись делает автор работы.

## Повторение тяжёлой части

Нового обучения нет. На новой машине установить model-зависимости:

```bash
uv sync --locked --extra model
```

На этой машине они уже доступны из существующего окружения ДЗ 6–7 через локальный
`.pth` в новом `.venv`; старое окружение не менялось. Этот локальный файл не входит в Git.
Публичная база: `Qwen/Qwen3-0.6B`, точная revision указана в manifest.
Адаптер берётся из сохранённого локального MLflow run, данные — из старой папки ДЗ 6–7:

```bash
cd ../../mlops_hw6-7
./tools/docker compose -p mlops-hw6 up -d --wait
cd ../mlops-labs/hw08-09-10
make real
.venv/bin/python flow_experiments.py --real
make load
```

`make real` заново выполняет полную оценку, поэтому для простого показа его запускать не нужно.
`make load` — новый настоящий замер 4+4, тоже уже сохранён.
При переносе на другую машину старый локальный путь из manifest надо разрешить на те же файлы
и пересчитать связанный выпуск, сохранив хеши содержимого; менять runtime без новой оценки нельзя.
