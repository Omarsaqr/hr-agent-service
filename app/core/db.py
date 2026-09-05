import sqlite3
from pathlib import Path

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "var" / "app.db"


def connect(db_path: Path | str = _DEFAULT_DB_PATH) -> sqlite3.Connection:
    # check_same_thread=False on both branches: NonceStore/IdempotencyStore/
    # AuditLog/GapLog are process-lifetime singletons (app/deps.py), each
    # holding one connection opened on whichever thread first calls the
    # relevant get_*() function. A real ASGI server -- and FastAPI's own
    # TestClient, which bridges sync test code into the async app through
    # a background-thread portal -- can dispatch a *later* request on a
    # *different* thread, and sqlite3 refuses by default to let that
    # thread touch a connection it didn't create. This was caught by
    # tests/e2e/test_leave_workflow.py raising
    # "SQLite objects created in a thread can only be used in that same
    # thread" the first time two separate TestClient instances exercised
    # the same singleton store across two threads. Safe here because
    # every access is already sequential (one request completes before
    # the next starts) -- this only disables Python's same-thread check,
    # not SQLite's own locking.
    if db_path == ":memory:":
        # ":memory:" is a special sqlite3 token, not a real path -- routing
        # it through Path() risks Windows rejecting the colon as a bad
        # filename.
        return sqlite3.connect(":memory:", check_same_thread=False)

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    # WAL: readers (a status query) don't block on a writer (a submit),
    # which matters once more than one tool call touches this file.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
