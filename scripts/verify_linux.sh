#!/bin/sh
# Run inside the built API image with the source mounted read-only at /workspace.
set -eu
cd /workspace
export PYTHONPATH=/tmp/gateway-quality:/workspace
export COVERAGE_FILE=/tmp/gateway.coverage
export RUFF_CACHE_DIR=/tmp/gateway-ruff
export MYPY_CACHE_DIR=/tmp/gateway-mypy
export PIP_NO_CACHE_DIR=1
python -c 'import subprocess, sys, tomllib; data = tomllib.load(open("pyproject.toml", "rb")); subprocess.check_call([sys.executable, "-m", "pip", "install", "--target", "/tmp/gateway-quality", "--constraint", "requirements.lock", *data["project"]["optional-dependencies"]["dev"]])'
python -m ruff check .
python -m ruff format --check .
python -m mypy gateway
python -m pytest -o cache_dir=/tmp/gateway-pytest --cov=gateway --cov-report=term-missing
python -m pip_audit --skip-editable --cache-dir /tmp/gateway-audit
python scripts/verify_manifests.py
python scripts/smoke_demo.py
