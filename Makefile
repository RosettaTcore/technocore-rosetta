.PHONY: format lint type typescript test coverage unit integration adversarial secret-scan demo verify evolution-image evolution-verify container-acceptance upstream-acceptance upgrade-canary acceptance install-hooks lock lock-check site-package site-check site-preview

PYTHON ?= python3
PYTHONPATH := src:.
UPGRADE_CANARY_OUTPUT ?= artifacts/upgrade-canary

install-hooks:
	git config --local core.hooksPath .githooks
	test "$$(git config --local core.hooksPath)" = ".githooks"
	test -x .githooks/pre-push

lock:
	UV=$(UV) tools/lock_requirements.sh

lock-check:
	UV=$(UV) tools/check_requirements_lock.sh

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
	$(PYTHON) -m coverage erase
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage json -o artifacts/coverage.json
	$(PYTHON) -m coverage report

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

upgrade-canary:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) tools/upgrade_canary.py --output $(UPGRADE_CANARY_OUTPUT)

site-package:
	$(PYTHON) tools/package_launch_evidence.py

site-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) tools/check_launch_site.py
	$(PYTHON) tools/package_launch_evidence.py --check
	node --check site/app.js
	node --check site/verifier.mjs
	node --test tests/site/verifier.test.mjs

site-preview:
	$(PYTHON) -m http.server 4173 --directory site

acceptance: lint type typescript coverage secret-scan demo verify site-check
