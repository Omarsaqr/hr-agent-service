.PHONY: dev test lint demo

dev:
	uvicorn app.main:app --reload

test:
	pytest

lint:
	ruff check .
	mypy .

demo:
	python scripts/seed_demo.py
