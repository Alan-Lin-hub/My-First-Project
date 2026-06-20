"""Unit tests for the in-memory login RateLimiter."""
from rate_limit import RateLimiter


def test_blocks_after_max_events():
    rl = RateLimiter(max_events=3, window_seconds=60)
    key = "1.2.3.4"
    for _ in range(3):
        assert not rl.is_blocked(key)   # under the limit
        rl.record(key)
    assert rl.is_blocked(key)           # 3rd failure reaches the limit


def test_reset_clears_counter():
    rl = RateLimiter(max_events=2, window_seconds=60)
    rl.record("k")
    rl.record("k")
    assert rl.is_blocked("k")
    rl.reset("k")
    assert not rl.is_blocked("k")


def test_keys_are_independent():
    rl = RateLimiter(max_events=1, window_seconds=60)
    rl.record("a")
    assert rl.is_blocked("a")
    assert not rl.is_blocked("b")       # one key's failures don't block another


def test_window_rolls_off(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("rate_limit.time.monotonic", lambda: clock["now"])
    rl = RateLimiter(max_events=2, window_seconds=60)
    rl.record("k")
    rl.record("k")
    assert rl.is_blocked("k")
    clock["now"] += 61                  # both events fall outside the window
    assert not rl.is_blocked("k")
