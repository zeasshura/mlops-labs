"""Стадия split: разбиение на train/val/test."""

import json
import random
import time
from pathlib import Path

from src.config import load_params
from src.contamination import is_clean, report
from src.schema import Example, dump, iter_examples
from src.textnorm import normalize_group


def group_split(examples: list[Example], ratios: dict[str, float], seed: int) -> dict[str, list[Example]]:
    """Раздать целые статьи Википедии, приближая заданные доли строк."""
    if any(value <= 0 for value in ratios.values()) or abs(sum(ratios.values()) - 1) > 1e-9:
        raise ValueError("split.ratios: нужны положительные доли с суммой 1")
    groups: dict[str, list[Example]] = {}
    for ex in examples:
        groups.setdefault(normalize_group(ex.topic), []).append(ex)
    keys = list(groups)
    random.Random(seed).shuffle(keys)
    buckets: dict[str, list[Example]] = {name: [] for name in ratios}
    target = {name: len(examples) * ratio for name, ratio in ratios.items()}
    for key in keys:
        destination = max(ratios, key=lambda name: (target[name] - len(buckets[name])) / target[name])
        buckets[destination].extend(groups[key])
    if any(not rows for rows in buckets.values()):
        raise ValueError("split: для одного из разбиений не хватило групп")
    return buckets


def main() -> None:
    params = load_params()
    paths = params["paths"]
    cfg = params["split"]
    started = time.perf_counter()

    examples: list[Example] = list(iter_examples(paths["clean"]))
    if cfg["group_key"] != "topic":
        raise SystemExit(f"неизвестный split.group_key: {cfg['group_key']!r}")

    sizes: dict[str, int] = {}
    for ex in examples:
        key = normalize_group(ex.topic)
        sizes[key] = sizes.get(key, 0) + 1

    buckets = group_split(examples, cfg["ratios"], cfg["seed"])

    for name, rows in buckets.items():
        out = Path(paths[name])
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for ex in rows:
                fh.write(dump(ex) + "\n")

    nd = params["clean"]["near_dup"]
    if nd["threshold"] != params["contamination"]["threshold"]:
        raise ValueError("пороги near-dup в clean и contamination должны совпадать")
    reports = {}
    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        rep = report(
            buckets[left], buckets[right],
            shingle_words=nd["shingle_words"],
            num_perm=nd["num_perm"],
            threshold=params["contamination"]["threshold"],
        )
        reports[f"{left}/{right}"] = rep
        if not is_clean(rep):
            raise ValueError(f"split: контаминация {left}/{right}: {rep}")

    metrics = {
        "version": params["collect"]["version"],
        "seed": cfg["seed"],
        "group_key": cfg["group_key"],
        "groups_total": len(sizes),
        "sizes": {name: len(rows) for name, rows in buckets.items()},
        "groups": {
            name: len({normalize_group(ex.topic) for ex in rows}) for name, rows in buckets.items()
        },
        "ratios_actual": {
            name: round(len(rows) / len(examples), 4) for name, rows in buckets.items()
        },
        "contamination": reports,
    }
    mpath = Path(paths["metrics_split"])
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    elapsed = round(time.perf_counter() - started, 2)
    print(
        "split: "
        + ", ".join(f"{name} {len(rows)}" for name, rows in buckets.items())
        + f" (групп {len(sizes)}, {elapsed} с)"
    )


if __name__ == "__main__":
    main()
