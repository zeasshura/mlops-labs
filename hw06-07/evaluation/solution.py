"""Strict answer scoring and fail-closed release policy."""
import json
import math


def _unique(items, what):
    if not isinstance(items, list) or not items:
        raise ValueError(f'{what}: нужен непустой список')
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in result:
            raise ValueError(f'{what}: отсутствующий или повторяющийся id')
        result[item['id']] = item
    return result


def _counts(items):
    n = len(items)
    correct = sum(i['correct'] for i in items)
    valid = sum(i['valid'] for i in items)
    errors = sum(i['error'] is not None for i in items)
    return dict(n=n, correct=correct, valid=valid, errors=errors,
                accuracy=correct / n if n else 0.0, format_rate=valid / n if n else 0.0)


def _object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Повтор ключа JSON')
        obj[key] = value
    return obj


def score(rows, outputs):
    tasks, answers = _unique(rows, 'rows'), _unique(outputs, 'outputs')
    if tasks.keys() != answers.keys():
        raise ValueError('Наборы id вопросов и ответов не совпадают')
    items = []
    for key, row in tasks.items():
        choices, slices = row.get('choices'), row.get('slices')
        if (not isinstance(choices, list) or not choices or any(not isinstance(x, str) for x in choices)
                or row.get('expected') not in choices or not isinstance(slices, list) or not slices
                or any(not isinstance(x, str) or not x for x in slices) or len(slices) != len(set(slices))):
            raise ValueError(f'{key}: некорректный контракт задания')
        output = answers[key]
        raw, error = output.get('raw'), output.get('error')
        if error is not None and not isinstance(error, str):
            raise ValueError(f'{key}: error должен быть строкой или null')
        parsed, valid = None, False
        if isinstance(raw, str) and error is None:
            try:
                parsed = json.loads(raw, object_pairs_hook=_object,
                                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError('JSON constant')))
                valid = (isinstance(parsed, dict) and set(parsed) == {'answer'}
                         and isinstance(parsed['answer'], str) and parsed['answer'] in choices)
            except (ValueError, TypeError, RecursionError):
                parsed = None
        items.append(dict(id=key, raw=raw, parsed=parsed, valid=valid,
                          correct=bool(valid and parsed['answer'] == row['expected']),
                          error=error, slices=list(slices)))
    names = sorted({s for item in items for s in item['slices']})
    return dict(overall=_counts(items),
                slices={name: _counts([i for i in items if name in i['slices']]) for name in names},
                per_item=items)


def _validate_summary(summary, items):
    if not isinstance(summary, dict):
        raise ValueError('Отсутствует сводка counts')
    actual = _counts(items)
    for key in ('n', 'correct', 'valid', 'errors'):
        if type(summary.get(key)) is not int or summary[key] != actual[key]:
            raise ValueError(f'Несогласованный count: {key}')
    for key in ('accuracy', 'format_rate'):
        x = summary.get(key)
        if type(x) not in (float, int) or not math.isfinite(x) or not math.isclose(x, actual[key], rel_tol=0, abs_tol=1e-12):
            raise ValueError(f'Некорректная метрика: {key}')


def _validate_result(result, minimum, minimum_slices):
    if not isinstance(result, dict):
        raise ValueError('Отсутствует отчёт')
    items = _unique(result.get('per_item'), 'per_item')
    if len(items) < minimum:
        raise ValueError(f'Недостаточно примеров: минимум {minimum}')
    for item in items.values():
        if (type(item.get('valid')) is not bool or type(item.get('correct')) is not bool
                or item['correct'] and not item['valid'] or 'error' not in item
                or item['error'] is not None and not isinstance(item['error'], str)
                or item['error'] is not None and (item['valid'] or item['correct'])):
            raise ValueError('Некорректный per_item')
        slices = item.get('slices')
        if (not isinstance(slices, list) or not slices or any(not isinstance(x, str) or not x for x in slices)
                or len(slices) != len(set(slices))):
            raise ValueError('Некорректные срезы per_item')
    values = list(items.values())
    _validate_summary(result.get('overall'), values)
    groups = {name: [i for i in values if name in i['slices']] for name in {s for i in values for s in i['slices']}}
    if len(groups) < minimum_slices or not isinstance(result.get('slices'), dict) or groups.keys() != result['slices'].keys():
        raise ValueError('Отсутствуют или изменились срезы')
    for name, members in groups.items():
        _validate_summary(result['slices'][name], members)
    if result['overall']['errors']:
        raise ValueError('В генерации есть ошибки')
    return items


def quality_gate(baseline, candidate, critical_slices):
    try:
        if not isinstance(critical_slices, list) or not critical_slices or any(not isinstance(s, str) or not s for s in critical_slices):
            raise ValueError('Нужны заранее заданные критические срезы')
        for key in ('protocol_sha256', 'golden_sha256', 'baseline_spec_sha256'):
            if not isinstance(baseline.get(key), str) or not baseline[key] or baseline[key] != candidate.get(key):
                raise ValueError(f'Несовместимость: {key}')
        for report in (baseline, candidate):
            model = report.get('model')
            if report.get('status') != 'complete' or not isinstance(model, dict) or not model.get('kind'):
                raise ValueError('Неполный отчёт или отсутствует модель')
            if model['kind'] == 'base' and not all(model.get(k) for k in ('name', 'revision')):
                raise ValueError('Не закреплена базовая модель')
            if model['kind'] == 'adapter' and not all(model.get(k) for k in ('name', 'version', 'run_id', 'uri')):
                raise ValueError('Не закреплена версия адаптера')
        a, b = (_validate_result(r, 50, 3) for r in (baseline, candidate))
        ba, bb = (_validate_result(r.get('behavioral'), 3, 1) for r in (baseline, candidate))
        for left, right in ((a, b), (ba, bb)):
            if left.keys() != right.keys() or any(set(left[i]['slices']) != set(right[i]['slices']) for i in left):
                raise ValueError('Изменились id или принадлежность срезам')
        for key in ('accuracy', 'format_rate'):
            if candidate['overall'][key] < baseline['overall'][key]:
                raise ValueError(f'Регрессия общей метрики {key}')
        for name in critical_slices:
            if name not in baseline['slices'] or name not in candidate['slices']:
                raise ValueError(f'Отсутствует критический срез {name}')
            if candidate['slices'][name]['accuracy'] < baseline['slices'][name]['accuracy']:
                raise ValueError(f'Регрессия критического среза {name}')
        if not all(i['correct'] for i in bb.values()):
            raise ValueError('Не все обязательные behavioral-кейсы пройдены')
        return dict(passed=True, n=len(a), critical_slices=list(critical_slices),
                    baseline_accuracy=baseline['overall']['accuracy'],
                    candidate_accuracy=candidate['overall']['accuracy'],
                    candidate_format_rate=candidate['overall']['format_rate'],
                    behavioral_passed=len(bb), protocol_sha256=baseline['protocol_sha256'])
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'Неполный или некорректный контракт отчёта: {exc}') from exc
