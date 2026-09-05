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

## Integration verification

`BambooHRAdapter` (`app/integrations/bamboohr/`) is verified against recorded response fixtures
via `respx`, not a live BambooHR account. A BambooHR sandbox requires an interactive trial signup
and email verification with no self-serve API-only path, which wasn't pursued further within this
project's time budget. Field mappings and the retry policy are covered by
`tests/contract/test_bamboohr_adapter.py` and `test_bamboohr_retry.py` against fixtures in
`app/integrations/bamboohr/fixtures/`, built from BambooHR's published API documentation. The
in-memory adapter (`InMemoryHRISAdapter`) is what tools and tests are wired against today, so
everything continues to run with zero external credentials; the `HRIS_DRIVER` environment-variable
switch that selects between the two adapters lands with the tool layer that first consumes it,
rather than being built ahead of anything that uses it.
