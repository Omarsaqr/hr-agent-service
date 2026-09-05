# HR Agent Service

Tool layer for the Lua HR agent: leave management and daily performance workflows for a
multi-country HR deployment (KSA, UAE, Egypt, Jordan).

Architecture, design decisions, and the workflow write-up land in `docs/` as the service is
built out. This file grows into the full walkthrough as those pieces land.

## Setup

    python -m venv .venv
    .venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
    pip install -e ".[dev]"

## Commands

    make dev     # run the API with reload
    make test    # run the test suite
    make lint    # ruff + mypy
