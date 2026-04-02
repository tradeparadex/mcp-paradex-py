.PHONY: format lint typecheck install-dev pre-commit clean test test-cov build publish

# Install development dependencies
install-dev:
	pip install -e ".[dev]"
	pre-commit install

PYTHON ?= .venv/bin/python

# Format code with black
format:
	$(PYTHON) -m black src tests

# Lint code with ruff
lint:
	$(PYTHON) -m ruff check src tests --fix

# Type check with mypy
typecheck:
	$(PYTHON) -m mypy src

# Run tests
test:
	$(PYTHON) -m pytest

# Run tests with coverage
test-cov:
	$(PYTHON) -m pytest --cov=mcp_paradex --cov-report=html

# Run all checks including tests
check: format lint typecheck test

# Run pre-commit on all files
pre-commit:
	pre-commit run --all-files

# Build the package
build:
	uv build

# Publish to PyPI using trusted publishing (requires PYPI_TOKEN or trusted publisher config)
publish: build
	uv publish

# Clean up cache files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
