from __future__ import annotations

import time
from collections import OrderedDict, deque
from threading import Lock


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        max_clients: int = 10000,
    ) -> None:
        self.limit = max(1, limit)
        self.window_seconds = window_seconds
        self.max_clients = max(1, max_clients)
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            events = self._events.pop(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                self._events[key] = events
                retry_after = max(1, int(self.window_seconds - (current - events[0]) + 0.999))
                return False, retry_after
            events.append(current)
            self._events[key] = events
            while len(self._events) > self.max_clients:
                self._events.popitem(last=False)
            return True, 0

    @property
    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._events)
