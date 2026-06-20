"""In-memory sliding-window rate limiter for login brute-force protection.

Follows the repo's plain-class-wrapper style (cf. SessionManager, UserStore).
State is per-process and in memory: it resets on restart and is NOT shared across
multiple worker processes. That is adequate for the single-process deployment
this project targets; put a shared store (e.g. Redis) behind it if you scale out.

`time.monotonic()` is used (not wall-clock) so the window is immune to system
clock adjustments.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class RateLimiter:
    """Tracks recent events per key within a rolling time window."""

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float):
        """Drop timestamps that have fallen out of the window."""
        events = self._events[key]
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()

    def is_blocked(self, key: str) -> bool:
        """True if `key` has reached the event limit within the window."""
        now = time.monotonic()
        self._prune(key, now)
        return len(self._events[key]) >= self.max_events

    def record(self, key: str):
        """Record one event for `key` (e.g. a failed login)."""
        now = time.monotonic()
        self._events[key].append(now)
        self._prune(key, now)

    def reset(self, key: str):
        """Clear all events for `key` (e.g. after a successful login)."""
        self._events.pop(key, None)
