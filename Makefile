.PHONY: install lint format test coverage demo browser-demo browser-test build clean

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

browser-demo:
	python scripts/run_browser_demo.py

browser-test:
	RENDERWITNESS_BROWSER_TESTS=1 pytest tests/test_capture.py tests/test_report_browser.py

build:
	python -m build

clean:
	rm -rf build dist htmlcov reports .coverage .mypy_cache .pytest_cache .ruff_cache
