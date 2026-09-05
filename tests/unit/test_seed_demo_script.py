import subprocess
import sys
from pathlib import Path

# Run as a real subprocess, not imported in-process: app.main.app is a
# module-level singleton built from whatever Settings were active the
# *first* time anything in this pytest session imported app.main --
# potentially another test file, with different driver settings already
# locked in. The script's own env-var overrides only work if it's the
# first thing to import app.main in a fresh interpreter, which a
# subprocess guarantees and an in-process call cannot.
_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "seed_demo.py"


def test_seed_demo_runs_both_workflows_end_to_end_with_zero_credentials() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "Demo complete" in result.stdout
    assert "Workflow: Leave Management" in result.stdout
    assert "Workflow: Daily Check-in and Team Performance" in result.stdout
    assert "approved" in result.stdout.lower()
    assert "checked in" in result.stdout.lower()
