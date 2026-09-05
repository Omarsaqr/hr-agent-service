import sqlite3
from pathlib import Path

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "var" / "app.db"


def connect(db_path: Path | str = _DEFAULT_DB_PATH) -> sqlite3.Connection:
    # ":memory:" is a special sqlite3 token, not a real path -- routing it
    # through Path() risks Windows rejecting the colon as a bad filename.
    if db_path == ":memory:":
        return sqlite3.connect(":memory:")

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    # WAL: readers (a status query) don't block on a writer (a submit),
    # which matters once more than one tool call touches this file.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
