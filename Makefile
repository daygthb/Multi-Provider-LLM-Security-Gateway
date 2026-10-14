.PHONY: install lint typecheck test audit verify demo seed mock serve compose linux-verify recovery-test
install:
	python -m pip install --constraint requirements.lock --upgrade pip
	python -m pip install --constraint requirements.lock -e '.[dev]'
lint:
	python -m ruff check .
	python -m ruff format --check .
typecheck:
	python -m mypy gateway
test:
	python -m pytest --cov=gateway --cov-report=term-missing
audit:
	python -m pip_audit --skip-editable
verify: lint typecheck test audit
	python scripts/verify_manifests.py
demo:
	python scripts/smoke_demo.py
seed:
	llm-gateway --database data/keys.db seed-demo
mock:
	llm-gateway mock
serve:
	llm-gateway serve --demo
compose:
	docker compose up -d --wait
linux-verify:
	docker run --rm --mount "type=bind,source=$(CURDIR),target=/workspace,readonly" --tmpfs /tmp:exec,mode=1777 -e PYTHONDONTWRITEBYTECODE=1 llm-security-gateway-api:latest sh /workspace/scripts/verify_linux.sh
recovery-test:
	python scripts/verify_redis_recovery.py
operations-test:
	python -m scripts.verify_operations
