"""Share concurrent catalog requests without retaining failed responses."""
import copy
import threading
import time


class CatalogRequestCache:
    def __init__(self, ttl=300, limit=256):
        self.ttl, self.limit = ttl, limit
        self.values = {}
        self.running = set()
        self.condition = threading.Condition()

    def get(self, key, loader):
        with self.condition:
            while key in self.running:
                self.condition.wait()
            cached = self.values.get(key)
            if cached and time.monotonic() - cached[0] < self.ttl:
                return copy.deepcopy(cached[1])
            self.running.add(key)
        try:
            result = loader()
            if isinstance(result, dict) and not result.get('error'):
                with self.condition:
                    if len(self.values) >= self.limit:
                        self.values.pop(next(iter(self.values)))
                    self.values[key] = (time.monotonic(), copy.deepcopy(result))
            return result
        finally:
            with self.condition:
                self.running.discard(key)
                self.condition.notify_all()
