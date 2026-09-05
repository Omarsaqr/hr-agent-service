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

`BambooHRAdapter` (`app/integrations/bamboohr/`) was verified against a live BambooHR trial
account -- every `HRISPort` method, reads and writes both -- then against recorded fixtures in
`app/integrations/bamboohr/fixtures/` that were corrected to match what the live account actually
returned. The test suite (`tests/contract/test_bamboohr_adapter.py`, `test_bamboohr_retry.py`) runs
against those fixtures via `respx`, not the live account, so `make test` and CI need zero external
credentials. What the live account revealed that fixtures alone could not is documented in
`docs/ROADMAP.md` under "BambooHR adapter: verified against a live trial account" -- notably that
the directory endpoint defaults to XML, that BambooHR exposes a manager only as a display name with
no id-based reference, and that time-off type names are per-tenant configuration, validated at
runtime rather than assumed.

The in-memory adapter (`InMemoryHRISAdapter`) is what tools and tests are wired against today, so
everything continues to run with zero external credentials; the `HRIS_DRIVER` environment-variable
switch that selects between the two adapters lands with the tool layer that first consumes it,
rather than being built ahead of anything that uses it.
