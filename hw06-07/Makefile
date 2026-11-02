export PATH := $(CURDIR)/tools:$(PATH)
export NO_PROXY := 127.0.0.1,localhost,$(NO_PROXY)
export no_proxy := $(NO_PROXY)
export OMP_NUM_THREADS := 4
export MKL_NUM_THREADS := 4

.PHONY: install up down sweep promote predict check check-storage
install:
	uv sync --frozen
runtime:
	uv run python scripts/bootstrap_runtime.py

up: runtime
	docker compose -p mlops-hw6 up --build -d --wait
down:
	docker compose -p mlops-hw6 down
sweep:
	uv run python -m src.sweep
promote:
	uv run python -m evaluation.cli promote
predict:
	uv run python -m src.predict --uri models:/my-qwen-adapter@champion --prompt "Passage: Tucson is the second-largest city in Arizona behind Phoenix. Question: What is the largest city in Arizona?"
check:
	bash tests/check.sh
check-storage:
	uv run python tests/check_storage.py

.PHONY: report candidate baseline-init evaluate eval check-eval check-negative check-all baseline-update predict-candidate
report:
	uv run python -m src.report
candidate:
	uv run python -m evaluation.cli candidate
baseline-init:
	uv run python -m evaluation.cli baseline-init
evaluate:
	uv run python -m evaluation.cli evaluate
eval:
	uv run python -m evaluation.cli gate
check-eval:
	uv run python -m unittest discover -s tests -p 'test_*.py' -v
check-negative:
	uv run python -m evaluation.cli negative
check-all: check check-eval
baseline-update:
	uv run python -m evaluation.cli baseline-update
predict-candidate:
	uv run python -m src.predict --uri models:/my-qwen-adapter@candidate --prompt "Passage: Tucson is the second-largest city in Arizona behind Phoenix. Question: What is the largest city in Arizona?"

.PHONY: runtime run-assignment
run-assignment:
	uv run python scripts/run_assignment.py
