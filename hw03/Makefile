.PHONY: install source repro v1 v2 diff dag diversity contamination check

export UV_CACHE_DIR := $(CURDIR)/.uv-cache

install:
	uv sync

source:
	uv run python scripts/fetch_source.py
	uv run dvc add sources/train-v1.1.json sources/dev-v1.1.json

repro:
	uv run dvc repro

v1:
	uv run python scripts/set_version.py v1
	uv run dvc repro

v2:
	uv run python scripts/set_version.py v2
	uv run dvc repro

diff:
	uv run dvc metrics diff

dag:
	uv run dvc dag

diversity:
	uv run python -m src.diversity

contamination:
	uv run python scripts/check_contamination.py

check:
	bash tests/check.sh
