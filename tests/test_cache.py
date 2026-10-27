"""TTL expiry, a failed load left uncached, and one refresh shared by two threads."""

import threading

import pytest

from app.cache import TtlCache


class Clock:
    def __init__(self) -> None:
        """A clock the cache tests can move forward."""

        self.now = 0.0

    def __call__(self) -> float:
        """Return the time the test last set."""

        return self.now


def test_expiry_refreshes_and_failed_load_is_not_cached():
    """A value is reused until the TTL, then a failed refresh is not stored."""

    clock = Clock()
    cache = TtlCache(10, clock=clock)
    calls = {"count": 0}

    def loader():
        """First call returns the original value. Later calls return the refreshed one."""

        calls["count"] += 1
        if calls["count"] == 1:
            return "first"
        return "second"

    assert cache.get_or_load(loader) == "first"
    clock.now = 9.9
    assert cache.get_or_load(loader) == "first"
    assert calls["count"] == 1

    clock.now = 10
    assert cache.get_or_load(loader) == "second"
    assert calls["count"] == 2

    def fail():
        """Simulate an upstream failure that must not be cached."""

        raise RuntimeError("upstream failed")

    clock.now = 30
    with pytest.raises(RuntimeError, match="upstream failed"):
        cache.get_or_load(fail)
    clock.now = 31
    assert cache.get_or_load(lambda: "recovered") == "recovered"


def test_concurrent_callers_share_one_refresh():
    """Two threads waiting on an empty cache cause one load."""

    cache = TtlCache(300)
    calls = {"count": 0}
    started = threading.Event()
    release = threading.Event()

    def loader():
        """Block until the test releases it, so the second thread has time to wait."""

        calls["count"] += 1
        started.set()
        assert release.wait(timeout=2)
        return ["ok"]

    results: list[list[str]] = []

    def read():
        """Read the cache from a background thread."""

        results.append(cache.get_or_load(loader))

    first = threading.Thread(target=read)
    first.start()
    assert started.wait(timeout=2)
    second = threading.Thread(target=read)
    second.start()
    threading.Event().wait(0.05)
    assert calls["count"] == 1
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert calls["count"] == 1
    assert results == [["ok"], ["ok"]]
