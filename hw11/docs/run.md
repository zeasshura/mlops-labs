# Запуск и удаление собственного стенда

Рабочая папка: `mlops-labs/hw11`. Все команды Kubernetes используют
`.runtime/kubeconfig`; общий kubeconfig пользователя не изменяется.

## Уже подготовленная машина

```bash
make status
make check
```

Итоговый `make check` запускает автор работы. При реализации собственные проверки
уже выполнены напрямую, журналы сохранены в `results/`.

Для просмотра мониторинга, если port-forward ещё не запущен:

```bash
.tools/kubectl --kubeconfig .runtime/kubeconfig -n hw11 port-forward --address 127.0.0.1 service/prometheus 19090:9090
.tools/kubectl --kubeconfig .runtime/kubeconfig -n hw11 port-forward --address 127.0.0.1 service/grafana 13000:3000
```

Каждая команда работает в своём терминале. Prometheus: http://127.0.0.1:19090,
Grafana: http://127.0.0.1:13000/d/hw11 (локальный просмотр без входа).
Для API в ещё одном терминале:

```bash
.tools/kubectl --kubeconfig .runtime/kubeconfig -n hw11 port-forward --address 127.0.0.1 service/api 18091:8091
curl -i http://127.0.0.1:18091/ready
curl -N http://127.0.0.1:18091/generate -H 'Content-Type: application/json' \
  -d '{"prompt":"demo","max_new_tokens":4,"history":[{"role":"user","content":"CONTROL_DEMO"}]}'
```

Это явно `backend_mode=simulated`: поле `max_new_tokens` сохранено для совместимости
с ДЗ 8–10, но здесь ограничивает число частей ответа. Веса модели не загружаются.

## Создание с нуля

Требуется Linux с rootless Podman, cgroup v2 и делегированными CPU/memory controllers.
Исходный стенд: Fedora, Podman 5.8.7; версии остальных компонентов закреплены в коде.

```bash
uv sync --locked --extra analysis
.venv/bin/python scripts/bootstrap.py tools
.venv/bin/python scripts/bootstrap.py create
.venv/bin/python scripts/bootstrap.py preload
.venv/bin/python scripts/bootstrap.py deploy
```

`preload` загружает образы на хосте и импортирует в kind. Это также обход случая,
когда унаследованный localhost proxy недоступен внутри контейнера-узла.
Никакие учётные данные registry не копируются в кластер или Git.

Ограничения: один узел, 4 CPU / 4 GiB / 4096 PID; приложения по 100m request и
400m CPU limit, 64Mi request / 128Mi RAM limit. В обычном опыте две реплики, HPA 2–3.
Во время опыта длинного rollout разрешены два слота обработки на реплику;
во всех основных сравнениях балансировки — один слот. Кеш LRU: 8 записей,
hit 0.15 CPU-с, miss 0.6 CPU-с. Очередь до 8 ожидающих, ожидание до 20 секунд.
Prometheus хранит 2h / 128MB; том emptyDir ограничен 256Mi, Grafana emptyDir 128Mi.
Предварительная оценка диска — 10 GiB; фактический размер и версии — в `results/` и отчёте.
Секретный kubeconfig, инструменты, архивы образов и venv исключены из Git.

## Повтор опытов

Сначала запустить port-forward Prometheus. Воспроизведение исходного дефекта:

```bash
.tools/helm upgrade --install hw11 chart --kubeconfig .runtime/kubeconfig -n hw11 \
  --create-namespace --set brokenReadiness=true --set warmupSeconds=20
.venv/bin/python scripts/experiment_a.py
HW11_K8S_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/run_matrix.py
.venv/bin/python scripts/experiment_c.py
.venv/bin/python scripts/report.py
```

18 прогонов матрицы требуют минимум 36 минут подачи нагрузки плюс ожидание завершения.
`run_matrix.py` пропускает уже существующие завершённые прогоны. Для полностью нового
повтора сохранить предыдущий `results/` отдельно и начать новый каталог результатов.
Не выдавать чужие или старые результаты за повторный прогон.

## Остановка и удаление

Остановить port-forward: Ctrl+C в соответствующих терминалах.
Временно остановить только узел этой работы, сохранив его данные:

```bash
podman stop mlops-hw11-control-plane
# Позднее:
podman start mlops-hw11-control-plane
```

Полностью удалить только собственный Kubernetes-стенд после сохранения результатов:

```bash
.venv/bin/python scripts/bootstrap.py delete
```

Эта команда удаляет кластер `mlops-hw11`; старые MLflow/Postgres-контейнеры и их
volumes не затрагиваются. Общие image caches автоматически не удаляются.
Для экономии диска можно отдельно убрать скачанные этой работой архивы из `.runtime`
после успешного импорта. Общие `podman system prune` и удаление чужих volumes не нужны.
