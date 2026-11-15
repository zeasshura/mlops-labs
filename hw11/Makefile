PYTHON ?= .venv/bin/python
.PHONY: setup check status matrix plots
setup:
	uv sync --locked --extra analysis
check:
	$(PYTHON) -m compileall -q app.py client.py lab.py scripts tests
	.tools/helm lint chart
	HW11_K8S_TESTS=1 $(PYTHON) -m unittest discover -s tests -v
status:
	.tools/kubectl --kubeconfig .runtime/kubeconfig -n hw11 get pods,svc,hpa
matrix:
	$(PYTHON) scripts/run_matrix.py
plots:
	$(PYTHON) scripts/report.py
