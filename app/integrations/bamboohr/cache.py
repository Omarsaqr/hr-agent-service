import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Tiny in-process TTL cache. Deliberately not shared across instances --
    each adapter instance owns its own, so cache lifetime matches app lifetime.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, _Entry[T]] = {}

    def get(self, key: str) -> tuple[bool, T | None]:
        entry = self._entries.get(key)
        if entry is None or entry.expires_at < time.monotonic():
            return False, None
        return True, entry.value

    def set(self, key: str, value: T) -> None:
        self._entries[key] = _Entry(value=value, expires_at=time.monotonic() + self._ttl_seconds)
