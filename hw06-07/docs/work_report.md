# Выполненная работа: ДЗ 6+7

Решение находится в `mlops_hw6-7`, ветка `codex/hw6-7`, продолжение локального Git-репозитория ДЗ 5. Исходная выдача `mlops26-hw6-7` и предыдущие задания не изменены.

- Изучены START, задание, README, EVALUATION и контракты исходных тестов.
- Исправлены четыре дефекта MLflow; подробности в `docs/defects.md`.
- Реализованы строгий scorer и gate без ослабления порогов.
- Все 24 модульных теста оценки и обвязки прошли. Итоговые приёмочные check-команды оставлены пользователю.
- Скопированы собственные тензоры из ДЗ 4, SHA-256 совпадают.
- Подготовлены golden 50, behavioral 3, полный индекс train 15 336. Связь с тензорами доказана ID и хешами; результаты в `docs/data_validation.json`.
- Добавлены DVC-версии данных, воспроизводимые скрипты подготовки и протокол до оценки.
- Подготовлено CPU-окружение, PostgreSQL и MLflow на rootless Podman Compose, постоянный volume артефактов.
- Артефакты предыдущего задания исключены из Git-индекса новой ветки, файлы на диске сохранены; история не переписывалась.

Реальные результаты, ссылки MLflow и отказ в выпуске записаны ниже. Сохранность volume и изолированная загрузка подтверждены. Публикация в удалённый репозиторий и итоговые проверки не выполняются автоматически.

## Фактические результаты

Sweep: `7a0037e96e2f4f9fa965894e6aa9f935`. Candidate: `models:/my-qwen-adapter/1`, run `4f2095a16b1e48f186a173c2af936b3a`.

| Конфигурация | r | lr | Base loss | Final loss | Время, с | RSS, МБ | Адаптер, МБ |
|---|---:|---:|---:|---:|---:|---:|---:|
| all-r8-low | 8 | 0.0001 | 1.4330009285074015 | 0.02275816388170754 | 166.98684126100852 | 6080.05859375 | 30.203970909118652 |
| qv-r8-high | 8 | 0.0003 | 1.4330009285074015 | 0.03443035130140533 | 173.82213175199286 | 5617.66015625 | 15.293856620788574 |
| qv-r4-high | 4 | 0.0003 | 1.4330009285074015 | 0.07553309213835746 | 183.79974167598994 | 5797.98046875 | 13.106302261352539 |
| all-r8-high | 8 | 0.0003 | 1.4330009285074015 | 0.08352850483061047 | 165.65863542299485 | 6150.34375 | 30.20397186279297 |
| qv-r8-low | 8 | 0.0001 | 1.4330009285074015 | 0.32008031994840935 | 189.35587506199954 | 5917.0625 | 15.293855667114258 |
| qv-r4-low | 4 | 0.0001 | 1.4330009285074015 | 0.6951503179645022 | 172.879103047002 | 2994.71875 | 13.106301307678223 |

### MLflow runs

- [all-r8-low](http://127.0.0.1:5006/#/experiments/1/runs/4f2095a16b1e48f186a173c2af936b3a)
- [qv-r8-high](http://127.0.0.1:5006/#/experiments/1/runs/54334625009c49f6b89f647f754e2ba4)
- [qv-r4-high](http://127.0.0.1:5006/#/experiments/1/runs/753f0fae202349fb8de409becc3647c9)
- [all-r8-high](http://127.0.0.1:5006/#/experiments/1/runs/7e4c6ce5dece4fdfaadd78d7ffad9d50)
- [qv-r8-low](http://127.0.0.1:5006/#/experiments/1/runs/70bc2190465740219e3e87a4683df2fe)
- [qv-r4-low](http://127.0.0.1:5006/#/experiments/1/runs/3f2fed569d6b4e22ae89ccc47ec7df3c)
- [Оценка baseline/candidate](http://127.0.0.1:5006/#/experiments/2/runs/fbe67256845f4eb0929e596d161259fe)

Baseline: `{"kind": "base", "name": "Qwen/Qwen3-0.6B", "revision": "c1899de289a04d12100db370d81485cdf75e47ca"}`.
Evaluation run: `fbe67256845f4eb0929e596d161259fe`.

| Версия / срез | n | correct | valid | errors | accuracy | format_rate |
|---|---:|---:|---:|---:|---:|---:|
| baseline/overall | 50 | 50 | 50 | 0 | 1.0 | 1.0 |
| baseline/biology | 20 | 20 | 20 | 0 | 1.0 | 1.0 |
| baseline/culture | 15 | 15 | 15 | 0 | 1.0 | 1.0 |
| baseline/geography | 15 | 15 | 15 | 0 | 1.0 | 1.0 |
| candidate/overall | 50 | 9 | 9 | 0 | 0.18 | 0.18 |
| candidate/biology | 20 | 5 | 5 | 0 | 0.25 | 0.25 |
| candidate/culture | 15 | 1 | 1 | 0 | 0.06666666666666667 | 0.06666666666666667 |
| candidate/geography | 15 | 3 | 3 | 0 | 0.2 | 0.2 |

Исправленные ID: [].
Потерянные ID: ['gold-56d47d7d2ccc5a1400d8314e', 'gold-56d4a7a72ccc5a1400d83168', 'gold-56d4bb172ccc5a1400d83186', 'gold-56d4bc242ccc5a1400d8318b', 'gold-56d4bcef2ccc5a1400d8319a', 'gold-56d4befa2ccc5a1400d831b4', 'gold-56d4c13d2ccc5a1400d831d2', 'gold-56d4c2102ccc5a1400d831ee', 'gold-56d4c3ba2ccc5a1400d831fd', 'gold-56d4c4bd2ccc5a1400d8320e', 'gold-56d5aeea1c85041400946db3', 'gold-56d5afb81c85041400946dc2', 'gold-56d5c9061c85041400946dca', 'gold-56d5ca321c85041400946dd2', 'gold-56d5cd181c85041400946de4', 'gold-57267a3ef1498d1400e8e10f', 'gold-57267adbf1498d1400e8e136', 'gold-57267b46dd62a815002e8692', 'gold-57275858f1498d1400e8f6a4', 'gold-57275d775951b619008f88cd', 'gold-57275eab5951b619008f88df', 'gold-57276074f1498d1400e8f718', 'gold-5727617f708984140094dcbd', 'gold-5727645a5951b619008f8947', 'gold-57276669f1498d1400e8f76e', 'gold-572767ee5951b619008f897b', 'gold-572768c8dd62a815002e9c62', 'gold-57276a08f1498d1400e8f79e', 'gold-57276b96dd62a815002e9c94', 'gold-572bcfb734ae481900deaf0b', 'gold-572bd14c34ae481900deaf15', 'gold-572bd34d750c471900ed4c16', 'gold-572bd4c0750c471900ed4c1e', 'gold-572bd5c1dfb02c14005c6ad5', 'gold-572bd7e52babe914003c2956', 'gold-572bd9a9dfb02c14005c6adf', 'gold-572bdc34f182dd1900d7c790', 'gold-572bdd2e2babe914003c295e', 'gold-572befb7dfb02c14005c6af3', 'gold-572bf00d2babe914003c2970', 'gold-572bf16ef182dd1900d7c798'].

### Behavioral

- `behavior-format`: baseline correct=True, candidate correct=False; raw baseline='{"answer":"A"}', candidate='"A"'.
- `behavior-paraphrase`: baseline correct=True, candidate correct=True; raw baseline='{"answer":"A"}', candidate='{"answer":"A"}'.
- `behavior-refusal`: baseline correct=True, candidate correct=True; raw baseline='{"answer":"REFUSE"}', candidate='{"answer":"REFUSE"}'.

### Разбор пяти пар ответов

**gold-56d47d7d2ccc5a1400d8314e**. Вопрос: What is the three word Latin name for domesticated dogs?
Эталон: `A` (Canis lupus familiaris). База: `{"answer":"A"}`; кандидат: `"A"`.
Формат база/кандидат: True/False; правильность: True/False. Ответ кандидата не соблюдает контракт JSON-объекта answer. Даже верная отдельная буква не засчитывается: формат является частью задачи.

**gold-57267a3ef1498d1400e8e10f**. Вопрос: The Philippines stopped celebrating Carnival after what year?
Эталон: `A` (1939). База: `{"answer":"A"}`; кандидат: `A`.
Формат база/кандидат: True/False; правильность: True/False. Ответ кандидата не соблюдает контракт JSON-объекта answer. Даже верная отдельная буква не засчитывается: формат является частью задачи.

**gold-572bcfb734ae481900deaf0b**. Вопрос: Which state borders Tennessee to the east?
Эталон: `D` (North Carolina). База: `{"answer":"D"}`; кандидат: `D`.
Формат база/кандидат: True/False; правильность: True/False. Ответ кандидата не соблюдает контракт JSON-объекта answer. Даже верная отдельная буква не засчитывается: формат является частью задачи.

**gold-56d4a7a72ccc5a1400d83168**. Вопрос: What decade had significant studies of dog genes to determine origins?
Эталон: `B` (2010s). База: `{"answer":"B"}`; кандидат: `B`.
Формат база/кандидат: True/False; правильность: True/False. Ответ кандидата не соблюдает контракт JSON-объекта answer. Даже верная отдельная буква не засчитывается: формат является частью задачи.

**gold-56d4bb172ccc5a1400d83186**. Вопрос: What nickname have dogs earned in the Western world?
Эталон: `C` (man's best friend). База: `{"answer":"C"}`; кандидат: `C`.
Формат база/кандидат: True/False; правильность: True/False. Ответ кандидата не соблюдает контракт JSON-объекта answer. Даже верная отдельная буква не засчитывается: формат является частью задачи.

### Решение

Gate: `{"passed": false, "reason": "Регрессия общей метрики accuracy"}`.
Кандидат НЕ принят в champion. Alias candidate сохранён; baseline не изменён. Следующий шаг — изучить проваленные ответы и формат, подготовить новый эксперимент без ослабления текущего gate.
Отрицательный опыт: rejected=True, причина: Несогласованный count: correct.
Дополнительная испорченная копия с согласованными counts и валидным JSON: rejected=True, причина: Регрессия общей метрики accuracy. Исходные ответы не изменены.
Probe пережил пересоздание контейнера: run `9b5c6a002f0a4d6ba962c23381e6c010`, SHA256 `cd2c44e6bf05ca65ef925be029f7f7e4103ed6660737d48f240afd761730a663`.
Загрузка candidate в новом изолированном процессе без локального конфига и с offline-базой подтверждена: ответ совпал дословно.
Итоговые make check / make check-all не запускались: пользователь выполняет их сам и записывает видео.
