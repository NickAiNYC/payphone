# payphone Development & Operational Commands
.PHONY: dev build-all stop clean test test-cognitive logs help

# Default help
help:
	@echo "payphone Developer Tooling"
	@echo "=========================="
	@echo "make dev             - Boot the entire local development stack in the foreground"
	@echo "make build-all       - Force build all containers"
	@echo "make stop            - Stop and tear down all running services"
	@echo "make clean           - Stop containers and purge all local volumes / database files"
	@echo "make test            - Run all backend integration and unit tests"
	@echo "make logs            - Stream logs from all running containers"

# Boot full local stack
dev:
	@if [ ! -f .env ]; then \
		echo "Warning: .env file not found. Copying .env.example to .env..."; \
		cp .env.example .env; \
	fi
	docker compose up --build

# Rebuild all containers
build-all:
	docker compose build --no-cache

# Tear down services
stop:
	docker compose down

# Full system cleaning
clean:
	docker compose down --volumes --remove-orphans
	rm -rf hermes-agent/__pycache__
	rm -rf hermes-agent/skills/voice_avatar/__pycache__

# Run integration tests
test:
	docker compose run --rm hermes-agent python3 test_cognitive_loop.py
	docker compose run --rm hermes-agent pytest tests/

# Run performance budgets verification
test-perf:
	docker compose run --rm hermes-agent pytest -v tests/test_performance.py
