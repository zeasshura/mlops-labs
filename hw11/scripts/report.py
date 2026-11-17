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

REPORT_TEMPLATE = r'''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ДЗ 11: Kubernetes под нагрузкой</title>
<style>
body{font:16px/1.6 system-ui,sans-serif;max-width:1160px;margin:36px auto;padding:0 24px;color:#172033;background:#fff}h1{font-size:34px;line-height:1.2}h2{margin-top:36px;border-top:1px solid #d5dde6;padding-top:20px}h3{margin-top:24px}code,pre{font-family:ui-monospace,monospace;font-size:13px}pre{background:#f0f4f8;padding:16px;overflow:auto}table{border-collapse:collapse;font-size:12px;width:100%;margin:16px 0}th,td{border:1px solid #cdd6e0;padding:7px;text-align:left}th{background:#edf3f9}figure{margin:24px 0}figure img{width:100%;height:auto}figcaption{font-size:13px;color:#46566a}.note{background:#fff6d8;border-left:4px solid #cc9700;padding:12px 16px}.ok{background:#eaf6ed;padding:12px 16px}a{color:#1259a3}li{margin:4px 0}@media print{body{font-size:10pt;margin:0}h2{break-after:avoid}figure,table{break-inside:avoid}pre{white-space:pre-wrap}a{color:inherit}}
</style>
<h1>ДЗ 11. Сервис работает, пользователи ждут</h1>
<p>Локальный Kubernetes, управляемый CPU-backend, потоковый HTTP и воспроизводимые эксплуатационные опыты.</p>
<p class="ok"><strong>Режим: backend_mode=simulated.</strong> Настоящая модель в этой работе не запускалась. Измерены TTFC и inter-chunk latency, а не TTFT, TPOT или tokens/s. Контейнеры, HTTP, Service, probes, HPA, Prometheus и Grafana — настоящие.</p>
<h2>1. Основа, версии и границы стенда</h2>
<p>Проект продолжает контракт сервиса ДЗ 8–10: FastAPI lifecycle, health/ready, идентичность фактически загруженного backend, request ID, ограничение обработки и очередь. В новой работе добавлены проверяемый файл имитатора, история в запросе, NDJSON-стрим, метрики, drain и Kubernetes.</p>
<p>Репозиторий: <a href="https://github.com/zeasshura/mlops-labs/tree/main/hw11">zeasshura/mlops-labs/hw11</a>.</p>
<p>kind 0.30.0, Kubernetes 1.34.0, Helm 3.18.6, rootless Podman 5.8.7, cgroup v2. Один узел ограничен 4 CPU, 4 GiB RAM и 4096 PID. Приложение: Python 3.12.12, FastAPI 0.118.3, Uvicorn 0.54.0, prometheus-client 0.23.1. Прямые и транзитивные зависимости закреплены в <a href="requirements-service.txt">requirements-service.txt</a> и <a href="uv.lock">uv.lock</a>. Образы: Prometheus 3.5.0, Grafana 12.1.1, kube-state-metrics 2.17.0, metrics-server 0.8.0. Фактические image ID и resource limits сохранены в results/versions.json.</p>
<p>До создания стенда зафиксированы свободный диск и план ресурсов: <a href="results/preflight.json">preflight.json</a>. На диске было около 197 GiB свободного места; доступной RAM по первоначальному free -h — около 7,9 GiB. План дополнительного места — до 10 GiB. Фактические размеры перечислены в results/footprint.json: отдельно каталог работы, контейнеры и общий image cache, а не сумма виртуальных размеров слоёв.</p>
<p>На каждую API-реплику: requests 100m CPU / 64Mi RAM, limits 400m / 128Mi. Две реплики, при HPA максимум три. Prometheus ограничен 2h / 128MB retention и emptyDir 256Mi; Grafana — emptyDir 128Mi. Веса, kubeconfig, архивы образов, инструменты и venv не включены в Git.</p>
<p>{{FOOTPRINT}}</p>
<h2>2. Артефакт, stateless-сервис и наблюдаемость</h2>
<p>Файлы <code>artifacts/model-A.json</code> и <code>model-B.json</code> включены в образ. SHA-256 A: <code>2cbfcc2c2599d0df8999f8f80d015c710b6e96ce153936833f8c511cfc5fa4ca</code>; B: <code>555a4dd71e4b461730fd594f867bc838d45cc7e87ebf524cedce1a01b7f7378c</code>. ConfigMap задаёт ожидаемый хеш; при несовпадении процесс не готов к трафику. Все реплики получают одинаковые байты из одного образа. Проверка после замены Pod подтверждает идентичность версии и хеша.</p>
<p>Каждая часть ответа содержит request_id, pod, model_id, runtime_sha256 и backend_mode. В журнале есть те же идентификаторы и client IP. История диалога передаётся в запросе; локальный префиксный кеш хранит только учебные признаки попадания, а не источник истины диалога. Потеря кеша влияет на стоимость вычисления, но не меняет историю. Две контрольные строки проверены раздельными диалогами.</p>
<p>Startup проверяет загрузку и окончание прогрева; readiness исключает непрогретый или draining Pod из нового трафика; liveness проверяет жизнь HTTP-процесса. Startup допускает до 90 неудачных проверок с периодом 1 с при прогреве 20 с. Liveness запускается после успешного startup. Разделение следует <a href="https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/">официальному контракту Kubernetes probes</a>.</p>
<p>Prometheus обнаруживает каждый помеченный Pod через Kubernetes discovery, включая ещё не Ready процессы с работающим HTTP. CPU/RAM получаются из kubelet cAdvisor через API proxy, Ready-реплики — из kube-state-metrics. Grafana развёрнута и проверена через API, экспорт реального дашборда: <a href="results/grafana-dashboard-export.json">JSON</a>. Восемь панелей: TTFC, полная длительность, running/waiting, завершённые req/s, ошибки, CPU, RAM, Ready. Конфигурация и PromQL находятся в chart/files. Request/session ID не используются как metric labels.</p>
<h2>3. Опыт A: прогрев, штатное обновление, откат и отказ</h2>
<h3>Гипотеза и исходный сбой</h3>
<p>Готовность HTTP-процесса не означает готовность backend. В исходном профиле startup/readiness направлены на /health, а демонстрационный brokenReadiness допускает выполнение до warmup. Под нагрузкой непрогретые процессы оказались в Ready EndpointSlice и приняли рабочие запросы. В финальной парной проверке — {{WARM_BAD}} таких ответов; после исправления — {{WARM_GOOD}}.</p>
<p>Финальная пара A-matched-broken / A-matched-fixed использует одинаковый образ 1.0.1, два прогретых исходных Pod, warmup 20 с, один слот, одинаковое расписание 80 запросов за 40 с и одно и то же действие rollout restart. Сравнивается только путь probes и допуск до прогрева. SHA расписания совпадает.</p>
<h3>Исправление и доказательства</h3>
<p>Startup/readiness проверяют реальное состояние backend. Клиентские журналы и <a href="results/timeline.jsonl">линия Ready/EndpointSlice</a> показывают отсутствие раннего рабочего трафика. Прямая проверка HTTP на IP холодного Pod возвращает 503; через обычный Service запросы продолжают обслуживать прогретые реплики.</p>
<p>Для rollout A→B заранее начат поток из 64 частей с интервалом 0,7 с. Он пересекает начало обновления и завершается полностью. В успешном фоновом прогоне <strong>32 из 32</strong> запросов завершились, HTTP 5xx и незавершённых ответов нет. Raw: <a href="results/runs/A-rollout.jsonl">A-rollout.jsonl</a>; длинный запрос: <a href="results/rolling-long-stream.json">rolling-long-stream.json</a>.</p>
<p>Первый вариант с одним слотом дал восемь queue deadline: долгий поток занимал единственный слот обработки. Он сохранён как A-rollout-before-fix. Для отдельного опыта длительного rollout разрешены два слота; размеры CPU/RAM и границы очереди не убраны. Во всех основных сравнениях B снова один слот.</p>
<p>При штатном завершении /drain сначала меняет readiness, затем preStop ждёт 6 с для распространения EndpointSlice; уже принятые потоки продолжаются. terminationGracePeriodSeconds=45, Uvicorn graceful timeout=30. Длинный поток заканчивается в этом бюджете. Гарантия относится к измеренной нагрузке и выбранному сроку, не к бесконечному потоку.</p>
<p>Неготовая B (neverReady=true) остаётся вне активных endpoints. В исправленном опыте 17/17 запросов обслужены A. Управляемый Helm rollback возвращает A, версия проверена настоящими ответами. Дополнительно устранена гонка сценария: одного helm --wait оказалось недостаточно для утверждения «все ответы уже A»; теперь перед следующим опытом явно проверяется kubectl rollout status. В исходном прогоне получены шесть ответов ещё работающей B.</p>
<p>Отдельно Pod принудительно удалён с grace-period=0 во время потока. Обрыв сохранён в <a href="results/forced-termination-request.json">forced-termination-request.json</a>; восстановление — в forced-termination-recovery.json и временной линии. Повторы клиента учитываются отдельными попытками.</p>
<figure><img src="results/figures/01-warmup-rollout.svg"><figcaption>График 1. Ready и Ready EndpointSlice по времени; ранние запросы и длинный поток при штатном rollout. У каждого окна собственная ось времени в секундах.</figcaption></figure>
<h2>4. Опыт B: четыре клиентских IP, кеш и горячая реплика</h2>
<p>Сравниваются обычный Service None и ClientIP над одними двумя репликами. Исправление — убрать ClientIP у рабочего Service api; контрольный обычный Service остаётся ориентиром. Ни кеш, ни стоимость CPU, ни concurrency, ни число реплик в ходе сравнения не меняются. Финальное переключение affinity не вызывает перезапуск Pod: checksum ConfigMap содержит только параметры backend, а не Service/HPA.</p>
<p>Четыре клиентских Pod имеют разные IP. Фактические адреса, kube-proxy config, Service spec и resource limits: <a href="results/matrix-config.json">matrix-config.json</a>. Один клиент отправляет 80% запросов в hot-профиле; остальные делят остаток. HTTP keep-alive отключён: каждый запрос использует отдельное TCP-соединение. IP, который видит backend, проверяется по серверному журналу. Семантика affinity определяется <a href="https://kubernetes.io/docs/concepts/services-networking/service/#session-affinity">Service ClientIP</a>, а не session_id приложения.</p>
<p>Каждая из шести комбинаций policy × traffic выполнена трижды. На каждую: 120 с подачи, 3 запланированных запроса/с, 360 попыток; всего <strong>{{B_ATTEMPTS}}</strong>. Список входов, длины 128/512 символов, четыре части ответа, интервал 0,06 с и расписание одинаковы между сравниваемыми политиками. SHA-256 расписаний проверяется генератором отчёта. Backend уже прогрет; кеш перед каждым прогоном подтверждённо сбрасывается.</p>
<p>Имитация префиксного кеша обозначена явно: LRU на восемь записей, hit 0,15 CPU-с, miss 0,6 CPU-с; computation выполняется PBKDF2 до нужного thread CPU time, а не одним sleep. При quota 400m wall time отличается от CPU time. Один активный запрос занимает слот до завершения потока; очередь до восьми, ожидание до 20 с. Результаты описывают эту модель нагрузки, не настоящую стоимость prefill или KV-cache.</p>
<p>Без affinity даже hot-клиент распределяется по новым соединениям между репликами. Это сохранённый отрицательный результат для предположения «80% одного клиента обязательно означают горячий Pod». При ClientIP трасса показывает устойчивую привязку и дисбаланс. Уже при uniform три из четырёх клиентов закрепились за одним Pod: доля 75%. Кеш локален, но выгода не компенсирует переполнение очереди. Точные значения всех повторов ниже; p95 относится только к успешным ответам, отказы учтены отдельно. Успехов/с — завершённые ответы на фактическую длительность пакета до последнего завершения, включая drain, а не на сумму задержек.</p>
{{TABLE}}
<p>Статистика не очищена от 429, deadline, обрывов и тайм-аутов. Полный журнал: <a href="results/requests.csv">requests.csv</a>, исходные строки — results/runs/*.jsonl, сводка — run-summary.csv. Идентификатор evidence_run вместе с request_id отделяет попытки разных опытов; в старых отладочных повторах одинаковый логический номер не объединяет две попытки. Исправленный клиент не теряет Pod/model_id на error-части потока и не считает ошибку очереди первой содержательной частью.</p>
<figure><img src="results/figures/02-pod-latency-queue.svg"><figcaption>График 2. TTFC и ожидание в очереди по каждой реплике для одинакового hot-профиля. Отказы отмечены отдельно, а не исключены из количества попыток.</figcaption></figure>
<figure><img src="results/figures/03-three-repeats-policies.svg"><figcaption>График 3. По три отдельных прогона каждой политики и профиля. Точки — отдельные p95/доли ошибок; столбец — среднее трёх значений, а не p95 от их среднего.</figcaption></figure>
<p>Выбор исправления защищается распределением, отказами и задержками из этих данных. None ценой дополнительных miss позволяет использовать обе реплики; постоянный ClientIP сохраняет локальность, но не учитывает текущую очередь. На настоящем inference engine отдельно нужны измерения стоимости пересчёта префикса, KV-memory pressure, batching, длительности decode и работа cache-aware router. По CPU-имитатору нельзя объявить победителя среди vLLM/SGLang/llm-d.</p>
<h2>5. Опыт C: настоящий HPA и два алерта</h2>
<p>HPA autoscaling/v2, minReplicas=2, maxReplicas=3, target CPU=70% от requests; requests есть у каждого участвующего API-контейнера. metrics.k8s.io доступен, что проверено перед опытом. Управляемая вычислительная нагрузка — 12 запросов/с на 120 с. Наблюдаются desired/current/Ready и момент создания каждой новой реплики. До включения HPA был минутный idle, чтобы предыдущая нагрузка не запускала масштабирование заранее.</p>
<p>После снижения нагрузки ожидание полного возврата к двум Ready репликам составило {{HPA_DOWN_1}} с после завершения пакета; для повторного hot-affinity опыта — {{HPA_DOWN_2}} с. Окно scaleDown задано 30 с, а фактическое ожидание также включает окно resource metrics, цикл HPA и завершение Pod. Эти числа не объявляются равными параметру stabilizationWindowSeconds. Появление каждого Pod и первое наблюдение Ready отдельно выписаны в <a href="results/scaling-events.csv">scaling-events.csv</a>; точность Ready ограничена шагом наблюдения около 1 с. Поле HPA status.currentReplicas обновляется с задержкой своего цикла; на графике текущее число считается по реально наблюдаемым Pod без deletionTimestamp, отдельно от desired и Ready. Точные времена и условия: <a href="results/hpa-evidence.json">hpa-evidence.json</a>, конфигурация — hpa-config.yaml, линия — timeline.jsonl.</p>
<p>Горячая реплика проверяется повторно при включённом HPA. При requests 100m на Pod даже 400m у одной и около нуля у другой дают примерно 200% от суммарных requests: порог 70% превышен. При условных requests 500m те же 400m суммарно дали бы около 40%, и средняя метрика могла бы скрыть очередь. Последний расчёт — объяснение, а не дополнительный измеренный прогон.</p>
<p>Новая Ready-реплика не обязана получить уже привязанных ClientIP-клиентов. Их связность с имеющимися endpoints сохраняется; средняя CPU-метрика создаёт ёмкость, но сама не меняет маршрутизацию. Подробная трасса C-hot-affinity и состав Pod в hpa-evidence.json позволяют увидеть малоиспользуемую новую реплику. Нагрузка, очередь и CPU по Pod сохранены отдельно от общей средней.</p>
<p>Алерты: p95 TTFC &gt; 1 с и доля rejected/aborted/deadline &gt; 10%. Для обоих минимум 10 наблюдений за 30 с, hold 15 с, evaluation 5 с. Управляемая перегрузка переводит оба правила из inactive через pending в firing; после снижения нагрузки они возвращаются в inactive. Фактически наблюдённые состояния: <code>{{ALERTS}}</code>. Источник — <a href="results/alert-states.jsonl">alert-states.jsonl</a>; это состояния Prometheus rules, внешние уведомления не настраивались.</p>
<figure><img src="results/figures/04-hpa-load.svg"><figcaption>График 4. Фактическое масштабирование 2→3→2, средняя CPU относительно requests и отправленная нагрузка. Вторая фаза показывает повтор горячей привязки.</figcaption></figure>
<h2>6. Учёт запросов и проверка histogram</h2>
<p>Клиент использует монотонные часы. TTFC = t первой содержательной части − t отправки; full latency = t завершения − t отправки; inter-chunk = t[i+1] − t[i]. Для одной части нет межчастного интервала. Ошибка очереди не считается содержательной частью. В случае настоящих токенов TPOT считался бы по N−1 интервалам после первого токена; таких измерений в этой работе нет.</p>
<p>В requests.csv есть scheduled/actual время отправки, send lag, первый фрагмент, завершение, HTTP status, outcome, Pod, версия, число частей и ошибка. Запланированные, отправленные, завершённые, отклонённые, оборванные и deadline перечислены отдельно. Данные генератора не превращают просроченную отправку в быстро обслуженный запланированный запрос. Полные сырые строки содержат все межчастные интервалы.</p>
<pre>histogram_quantile(0.95,
  sum by (le, pod) (increase(hw11_ttfc_seconds_bucket[WINDOW])))

histogram_quantile(0.95,
  sum by (le) (rate(hw11_duration_seconds_bucket[2m])))</pre>
<p>le сохраняется при суммировании classic histogram. TTFC histogram учитывает ответы с первой содержательной частью; duration — только завершённые. Для сравнений выбираются соответствующие строки клиента, тот же Pod и тот же измерительный интервал до завершения всех ответов с дополнительным scrape. Для каждого прогона окно и реальный результат запроса сохранены в *-prometheus.json; сопоставление — <a href="results/prometheus-client-comparison.csv">prometheus-client-comparison.csv</a>.</p>
<p>Клиентский p95 вычислен линейной интерполяцией отсортированных наблюдений в позиции (n−1)×0,95. Prometheus интерполирует по bucket, а increase экстраполирует по дискретным scrapes: значения и восстановленное количество могут отличаться от точного журнала. Границы bucket: 0,05; 0,1; 0,2; 0,4; 0,8; 1,6; 3,2; 6,4; 12,8; 25,6; 60; +Inf секунд. Широкий bucket ограничивает точность; для промышленного SLO около 1 с нужна дополнительная граница 1 с. Источник: <a href="https://prometheus.io/docs/practices/histograms/">документация Prometheus</a>.</p>
<h2>7. Собственные проверки и исправленные ошибки</h2>
<p>Пять проверок обращаются к настоящему сервису в Kubernetes: 1) непрогретый Pod отсутствует в Ready endpoints и отвечает 503; 2) после rollback загружена A с ожидаемым хешем; 3) после удаления Pod новая реплика восстанавливает ту же версию и продолжает диалог с переданной историей; 4) отказ и оборванный поток увеличивают соответствующие counters; 5) CONTROL_ALPHA и CONTROL_BETA не смешиваются. Дополнительно два локальных HTTP-теста проверяют readiness и валидацию до вычисления.</p>
<p>Логи проверок: <a href="results/kubernetes-tests.txt">пять Kubernetes-тестов</a>, <a href="results/local-tests.txt">два локальных</a>; фактические ответы — results/checks. Ошибки, причины, исправления и доказательства перечислены в <a href="docs/defects.md">docs/defects.md</a>.</p>
<h2>8. Ревью: кеш не должен быть постоянной привязкой диалога</h2>
<p>Для нового запроса выбираю B: пересчёт 0,8 с дешевле ожидания A на 3 с. Решение должно учитывать кеш, оценку оставшейся очереди, running/waiting и доступную память, а не только совпадение session/IP. Если свободной ёмкости нет, нужна ограниченная очередь и явный отказ; повтор — отдельная попытка. Утверждать выигрыш без проверки распределений hit/miss, TTFC/full p95 и доли отказов нельзя.</p>
<p>История живёт в запросе или внешнем хранилище. После потери A другая реплика восстанавливает проверенную версию, даже если её локальный кеш холодный. Уже начатый поток не перенаправляю: A завершает его в grace period. При force kill клиент получает явный обрыв; для безопасного продолжения нужен отдельный протокол offset/idempotency, а не склейка двух независимых ответов.</p>
<p>Кейс Google Cloud / Vertex AI. В <a href="https://cloud.google.com/blog/products/containers-kubernetes/how-gke-inference-gateway-improved-latency-for-vertex-ai">первичном источнике Google Cloud</a> описано изменение весов prefix:queue:kv-utilization с 3:3:2 на 3:5:2: более высокий вес очереди позволяет обходить горячую реплику даже при попадании в кеш. Это поддерживает выбор B при заданных 3 с очереди у A и 0,8 с пересчёта у B. Промышленные результаты Google не перенесены на наш CPU-имитатор.</p>
<h2>9. Запуск и удаление стенда</h2>
<p>Требуются Linux, rootless Podman и cgroup v2. Команды выполняются из <code>hw11</code>; Kubernetes использует <code>.runtime/kubeconfig</code>.</p>
<pre>uv sync --locked --extra analysis
.venv/bin/python scripts/bootstrap.py tools
.venv/bin/python scripts/bootstrap.py create
.venv/bin/python scripts/bootstrap.py preload
.venv/bin/python scripts/bootstrap.py deploy
make status
make check</pre>
<p>Для просмотра мониторинга запустить в отдельных терминалах:</p>
<pre>.tools/kubectl --kubeconfig .runtime/kubeconfig -n hw11 port-forward --address 127.0.0.1 service/prometheus 19090:9090
.tools/kubectl --kubeconfig .runtime/kubeconfig -n hw11 port-forward --address 127.0.0.1 service/grafana 13000:3000</pre>
<p><a href="http://127.0.0.1:13000/d/hw11">Grafana</a>, <a href="http://127.0.0.1:19090">Prometheus</a>. Для проверки API:</p>
<pre>.tools/kubectl --kubeconfig .runtime/kubeconfig -n hw11 port-forward --address 127.0.0.1 service/api 18091:8091
curl -i http://127.0.0.1:18091/ready
curl -N http://127.0.0.1:18091/generate -H 'Content-Type: application/json' \
  -d '{"prompt":"demo","max_new_tokens":4,"history":[{"role":"user","content":"CONTROL_DEMO"}]}'</pre>
<p>Повтор опытов записывает результаты в <code>results/</code>. Перед новым измерением сохранить предыдущие результаты отдельно. Матрица B занимает минимум 36 минут подачи нагрузки; скрипт пропускает уже завершённые прогоны.</p>
<pre>.tools/helm upgrade --install hw11 chart --kubeconfig .runtime/kubeconfig -n hw11 --set brokenReadiness=true --set warmupSeconds=20
.venv/bin/python scripts/experiment_a.py
.venv/bin/python scripts/run_matrix.py
.venv/bin/python scripts/experiment_c.py
.venv/bin/python scripts/report.py</pre>
<p>Пробросы портов останавливаются через Ctrl+C. Временная остановка и повторный запуск:</p>
<pre>podman stop mlops-hw11-control-plane
podman start mlops-hw11-control-plane</pre>
<p>Удаление кластера HW11:</p>
<pre>.venv/bin/python scripts/bootstrap.py delete</pre>
<p>Порты мониторинга доступны только на 127.0.0.1. metrics-server использует kubelet-insecure-tls для self-signed сертификатов локального kind.</p>
<h2>10. Ограничения результатов</h2>
<p>Один локальный узел, общий хост с мониторингом, ограниченные CPU и учебный LRU. Три повтора характеризуют этот стенд и это расписание, не все реальные диалоги. Cache hit/miss заданы искусственно, batching/KV-memory/GPU/настоящие токены не измерялись. Принудительный обрыв учтён; штатный rollout проверен в конкретном бюджете потока. HPA CPU не устраняет плохую маршрутизацию. После TTL 2h старые live-метрики исчезают, поэтому запросы Prometheus, сырые журналы, экспорт дашборда и четыре графика сохранены в репозитории.</p>
</html>
'''



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
    document=REPORT_TEMPLATE
    for key,value in placeholders.items():document=document.replace('{{'+key+'}}',value)
    (ROOT/'report.html').write_text(document)
    print('Four figures, raw CSV, per-run summaries, Prometheus comparison and HTML report generated.',flush=True)


if __name__=='__main__':main()
