import os

# setdefault, not set: a developer's exported ENVIRONMENT (e.g. from a real
# .env) should still win; this only fills the gap so imports don't fail
# during collection.
os.environ.setdefault("ENVIRONMENT", "test")
