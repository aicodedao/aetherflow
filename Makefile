.PHONY: local-test pypi-test reqs push-develop release-dry-rc release-rc release-dry-final release-final

local-test:
	python -m venv .venv
	. .venv/bin/activate && python -m pip install -U pip
	. .venv/bin/activate && pip install -r requirements-dev.txt
	. .venv/bin/activate && pip install -e packages/aetherflow-core
	. .venv/bin/activate && pip install -e packages/aetherflow-scheduler
	. .venv/bin/activate && pip install -e packages/aetherflow
	. .venv/bin/activate && pytest -q -vv -m "not slow"

pypi-test:
	. .venv/bin/activate && pip install aetherflow-core[all,dev]
	. .venv/bin/activate && pip install aetherflow-scheduler[dev]
	. .venv/bin/activate && pytest -q -vv -m "not slow"

# install only what release.py needs (optional)
reqs:
	python -m venv .venv
	. .venv/bin/activate && python -m pip install -U pip
	. .venv/bin/activate && pip install -r requirements-release.txt

# usage:
#   make push-develop COMMIT_MSG="fix: update docs"
push-develop:
	@if [ -z "$(COMMIT_MSG)" ]; then echo "Specify COMMIT_MSG=\"...\""; exit 1; fi
	git checkout develop
	git pull --rebase origin develop
	git add -A
	git commit -m "$(COMMIT_MSG)" || echo "no changes to commit"
	git push origin develop

# DRY RUN (RC on test)
release-dry-rc:
	python release.py --mode rc --dry-run --allow-dirty

# REAL RC release (must run on test, creates *rc* tags, pushes tags)
# requires env: GITHUB_TOKEN
release-rc:
	git checkout test
	git pull --rebase origin test
	python release.py --mode rc --push

# DRY RUN (final on master)
release-dry-final:
	python release.py --mode final --dry-run --allow-dirty

# REAL final release (must run on master, creates final tags, pushes tags)
# requires env: GITHUB_TOKEN
release-final:
	git checkout master
	git pull --rebase origin master
	python release.py --mode final --push
