.PHONY: format lint type typescript test coverage unit integration adversarial secret-scan demo verify evolution-image evolution-verify container-acceptance upstream-acceptance acceptance

PYTHON ?= python3
PYTHONPATH := src:.

format:
	$(PYTHON) tools/quality.py format

lint:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) tools/quality.py lint

type:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) tools/quality.py type

typescript:
	npm --prefix adapters run check

unit:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest tests/unit

integration:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest tests/integration

adversarial:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest tests/adversarial

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest

coverage:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=json:artifacts/coverage.json

secret-scan:
	$(PYTHON) tools/secret_scan.py

demo:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m rosetta.cli demo --output artifacts/demo

verify:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m rosetta.cli verify artifacts/demo/bundle

evolution-image:
	docker build -f deploy/Dockerfile.evolution-evaluator -t rosetta/evolution-evaluator:local .

evolution-verify:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m rosetta.evolution_cli verify artifacts/evolution-demo-v1

container-acceptance:
	test -n "$(IMAGE)"
	test -n "$(NODE_IMAGE)"
	$(PYTHON) tools/container_acceptance.py --image "$(IMAGE)" --node-image "$(NODE_IMAGE)" --output artifacts/container-acceptance.json

upstream-acceptance:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) tools/upstream_acceptance.py --output artifacts/upstream-acceptance --soak-iterations 20

acceptance: lint type typescript coverage secret-scan demo verify
