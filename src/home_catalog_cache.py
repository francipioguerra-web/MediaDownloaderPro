"""Serve the latest usable home immediately while refreshing it once in background."""
import json
import os
import threading
import time


class HomeCatalogCache:
    def __init__(self, path, ttl=300):
        self.path = path
        self.ttl = ttl
        self.condition = threading.Condition()
        self.value = None
        self.updated = 0
        self.running = False
        self.attempted = 0
        try:
            import re
            with open(path) as source:
                raw_text = source.read()
                raw_text = re.sub(r'https?://img\.streaming-community\.[a-z0-9.-]+/t/p/', 'https://image.tmdb.org/t/p/', raw_text)
                saved = json.loads(raw_text)
            if self.usable(saved.get('catalog')):
                self.value = saved['catalog']
                self.updated = saved.get('updated', 0)
        except (OSError, ValueError, TypeError):
            pass

    @staticmethod
    def usable(value):
        return isinstance(value, dict) and value.get('success') and any(row.get('titles') for row in value.get('sliders', []))

    def publish(self, value):
        if not self.usable(value):
            return
        # Detach from rows that the loader may still enrich.
        snapshot = json.loads(json.dumps(value))
        with self.condition:
            self.value = snapshot
            self.updated = time.time()
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                temporary = self.path + '.tmp'
                with open(temporary, 'w') as destination:
                    json.dump({'updated': self.updated, 'catalog': snapshot}, destination)
                os.replace(temporary, self.path)
            except OSError:
                pass
            self.condition.notify_all()

    def get(self, loader, wait=8):
        with self.condition:
            if not self.running and time.time() - self.updated >= self.ttl and time.monotonic() - self.attempted >= 10:
                self.running = True
                self.attempted = time.monotonic()
                def refresh():
                    try:
                        self.publish(loader())
                    except Exception:
                        pass  # Retain the last usable catalog on a source failure.
                    finally:
                        with self.condition:
                            self.running = False
                            self.condition.notify_all()
                threading.Thread(target=refresh, daemon=True).start()
            if self.value is None and self.running:
                self.condition.wait_for(lambda: self.value is not None or not self.running, timeout=wait)
            return self.value or {'success': False, 'sliders': []}
