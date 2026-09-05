from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_INDEX_PATH = Path(__file__).parent.parent / "web" / "index.html"


@router.get("/", response_class=HTMLResponse)
def serve_portal() -> str:
    # Read on every request, not cached at import time: this is a
    # single static file with no templating and no build step, so a
    # developer editing it should see the change on refresh without
    # restarting the process.
    return _INDEX_PATH.read_text(encoding="utf-8")
