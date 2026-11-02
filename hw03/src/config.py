"""Чтение params.yaml — единственная точка правды о конфигурации."""

from pathlib import Path

import yaml


def load_params(path: str = "params.yaml") -> dict:
    """Загрузить параметры запуска."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def source_files(params: dict) -> list[Path]:
    """Файлы-источники для текущей версии датасета.

    Версия живёт в params, а не в аргументах командной строки: иначе
    dvc.lock не запомнит, из чего собран артефакт.
    """
    version = params["collect"]["version"]
    sources = params["collect"]["sources"]
    if version not in sources:
        raise SystemExit(
            f"collect.version = {version!r}, но в collect.sources "
            f"есть только {sorted(sources)}"
        )
    files = [Path(p) for p in sources[version]]
    missing = [f for f in files if not f.exists()]
    if missing:
        raise SystemExit(
            "стадия collect не нашла источник:\n  "
            + "\n  ".join(str(f) for f in missing)
            + "\nВосстановите файлы командой `uv run dvc pull` либо "
              "запустите `make source` и повторите `make repro`."
        )
    return files
