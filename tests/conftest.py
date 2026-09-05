import os

# setdefault, not set: a developer's exported ENVIRONMENT (e.g. from a real
# .env) should still win; this only fills the gap so imports don't fail
# during collection. Same reasoning for PREVIEW_TOKEN_SECRET -- it has no
# default in Settings on purpose, so CI (no .env file at all) needs this
# to import app.main successfully.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("PREVIEW_TOKEN_SECRET", "test-only-secret-do-not-use-in-production")
