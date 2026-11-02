# ДЗ 5: LoRA на собственных данных ДЗ 4

Решение исходного `mlops26-hw5/hw5-broken`. Данные: Wikipedia QA из прошлого задания; SHA-256 и источники указаны в `docs/data_provenance.json`.

```bash
uv sync
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 make train
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 make compare
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 make check
```

Текущий конфиг рассчитан на CPU: float32, эффективный batch 8, лимит 20 шагов и фиксированная validation-выборка из 200 примеров (seed 42). `data.val_limit: null` включает весь validation. `max_steps: null` включает полную эпоху. Все настройки модели, LoRA, данных и сравнения находятся в `params.yaml`.

- `docs/work_report.md` — выполненная работа и фактический статус проверки.
- `docs/defects.md` — пять дефектов и дополнительные исправления.
- `docs/curves.png` — графики обоих вариантов после `make train`.
- `docs/compare.md` — база и адаптер на пяти фиксированных вопросах после `make compare`.
- `models/adapter_*` — адаптер и локальный токенизатор с шаблоном чата.
- `metrics/train_*.json` — loss, параметры, время, память, размер адаптера, отпечаток входов.

Данные, веса и JSON-метрики исключены из Git. `tests/check.sh` не изменён, отпечаток `06a02208c1f0`. После изменения кода обучения или его параметров требуется новый прогон. Для офлайн-загрузки передаваемого адаптера базовая модель должна быть в кэше получателя.

В `dvc.yaml` описаны `train_all`, `train_freeze`, `compare`, `plot`. Чтобы использовать DVC, установите его отдельно; для запуска через Makefile он не требуется. Репозиторий локальный, публикация и видео сдачи пока не выполнены.
