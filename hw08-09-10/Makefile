PYTHON ?= .venv/bin/python
.PHONY: check setup evidence real serve load
setup:
	uv sync --locked
check:
	$(PYTHON) -m compileall -q release.py lab.py service.py backend.py flow.py integrate_hw67.py flow_experiments.py benchmark.py evidence.py tests tests_integration
	$(PYTHON) -m unittest discover -s tests -v
	HW8910_HTTP_ENGINE=stdlib $(PYTHON) -m unittest discover -s tests_integration -v
	HW8910_HTTP_ENGINE=fastapi $(PYTHON) -m unittest discover -s tests_integration -v
evidence:
	$(PYTHON) evidence.py
real:
	$(PYTHON) integrate_hw67.py
serve:
	$(PYTHON) service.py --engine fastapi --backend real --workspace .runtime/real --warmup-seconds 0 --debug
load:
	$(PYTHON) benchmark.py --workspace .runtime/real --count 4
