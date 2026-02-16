.PHONY: dev test

dev:
	python -m venv .venv
	. .venv/bin/activate && pip install -e packages/aetherflow-core
	. .venv/bin/activate && pip install -e packages/aetherflow-scheduler
	. .venv/bin/activate && pip install pytest

test:
	. .venv/bin/activate && pytest
