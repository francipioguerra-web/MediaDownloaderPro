"""Keep the provider's short-lived HLS signature current across media requests."""
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


class StreamTokens:
    def __init__(self, load_source, clock=time.time):
        self.load_source = load_source
        self.clock = clock
        self.entries = OrderedDict()
        self.condition = threading.Condition()
        self.refreshing = set()
        self.failed_at = {}

    @staticmethod
    def signature(url):
        parsed = urlsplit(url)
        query = dict(parse_qsl(parsed.query))
        try:
            expires = float(query['e'])
            if expires > 1e11:
                expires /= 1000
            if not query.get('t'):
                return None
            return parsed, query, expires
        except (KeyError, ValueError):
            return None

    @staticmethod
    def accepts(url, ref):
        target, player = urlsplit(url), urlsplit(ref)
        return (target.scheme == 'https' and (target.hostname or '').endswith('.d2b.you')
                and ('/hls/' in target.path or target.path.startswith('/hls/')) and player.scheme == 'https'
                and player.hostname == 'v.vidxgo.co')

    def register(self, source, ref):
        signature = self.signature(source)
        if not signature or not self.accepts(source, ref):
            return
        with self.condition:
            current = self.entries.get(ref)
            if not current or signature[2] >= current[2]:
                self.entries[ref] = signature
                self.entries.move_to_end(ref)
            while len(self.entries) > 128:
                expired, _ = self.entries.popitem(last=False)
                self.failed_at.pop(expired, None)

    def sign(self, url, ref, force=False):
        original = self.signature(url)
        if not original or not self.accepts(url, ref):
            return url
        with self.condition:
            while ref in self.refreshing:
                self.condition.wait()
            current = self.entries.get(ref, original)
            changed = any(current[1].get(k) != original[1].get(k) for k in ('t', 'e'))
            needs_refresh = current[2] <= self.clock() + 30 or (force and not changed)
            if needs_refresh and self.clock() - self.failed_at.get(ref, -100) >= 10:
                self.refreshing.add(ref)
            else:
                needs_refresh = False
        if needs_refresh:
            try:
                source = self.load_source(ref)
                refreshed = self.signature(source or '')
                # Never move another episode's resources onto this signature.
                if not refreshed or not self.accepts(source, ref) or refreshed[2] <= self.clock():
                    raise ValueError('Firma video non disponibile')
                if refreshed[0].path.rsplit('/', 1)[0] != original[0].path.rsplit('/', 1)[0]:
                    raise ValueError('Firma video per un episodio diverso')
                self.register(source, ref)
            except Exception:
                with self.condition:
                    self.failed_at[ref] = self.clock()
            finally:
                with self.condition:
                    self.refreshing.discard(ref)
                    self.condition.notify_all()
        with self.condition:
            current = self.entries.get(ref, original)
        if current[0].path.rsplit('/', 1)[0] != original[0].path.rsplit('/', 1)[0]:
            return url
        params = dict(parse_qsl(original[0].query))
        for name in ('t', 'e'):
            params[name] = current[1][name]
        return urlunsplit(original[0]._replace(netloc=current[0].netloc, query=urlencode(params)))
