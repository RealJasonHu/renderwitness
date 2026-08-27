.PHONY: install lint format test coverage demo build clean

install:
	python -m pip install -e '.[dev]'

lint:
	ruff check .
	ruff format --check .
	mypy src

format:
	ruff check --fix .
	ruff format .

test:
	pytest

coverage:
	pytest --cov=renderwitness --cov-report=term-missing --cov-report=html

demo:
	renderwitness demo --output reports/demo

build:
	python -m build

clean:
	rm -rf build dist htmlcov reports .coverage .mypy_cache .pytest_cache .ruff_cache
