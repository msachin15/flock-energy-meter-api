"""Process-local TTL cache.

Expired entries are refreshed. A failed load leaves the previous entry expired
and does not store the failure. One refresh runs at a time; other callers wait
and then reuse the value if the refresh succeeded.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
_MISSING = object()


class TtlCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] | None = None) -> None:
        """Keep one value until the TTL passes. `clock` is injectable so tests can expire it."""

        if ttl_seconds < 0:
            raise ValueError("ttl_seconds cannot be negative")
        self.ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._refresh = threading.Lock()
        self._value: T | object = _MISSING
        self._expires_at = 0.0

    def get_or_load(self, loader: Callable[[], T]) -> T:
        """Return the cached value, or load it. An exception from `loader` is not stored."""

        if self._fresh():
            return self._stored()
        with self._refresh:
            if self._fresh():
                return self._stored()
            loaded = loader()
            with self._lock:
                self._value = loaded
                self._expires_at = self._clock() + self.ttl_seconds
            return loaded

    def _fresh(self) -> bool:
        """True only when a value is stored and the clock is still before expiry."""

        with self._lock:
            return self._value is not _MISSING and self._clock() < self._expires_at

    def _stored(self) -> T:
        """Return the stored value. Call this only after `_fresh` was true."""

        with self._lock:
            value = self._value
        if value is _MISSING:
            raise RuntimeError("Cache was empty after a freshness check")
        return value  # type: ignore[return-value]
