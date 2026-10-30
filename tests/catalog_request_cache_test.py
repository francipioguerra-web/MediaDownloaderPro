import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from src.catalog_request_cache import CatalogRequestCache


class CatalogRequestCacheTests(unittest.TestCase):
    def test_concurrent_details_share_one_fetch_and_results_are_independent(self):
        cache = CatalogRequestCache()
        started, release = threading.Event(), threading.Event()
        calls = []
        def load():
            calls.append(1)
            started.set()
            release.wait(2)
            return {'episodes': [{'id': 42}]}
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(cache.get, ('title', '70'), load)
            self.assertTrue(started.wait(1))
            second = pool.submit(cache.get, ('title', '70'), load)
            release.set()
            one, two = first.result(), second.result()
        self.assertEqual(len(calls), 1)
        one['episodes'].clear()
        self.assertEqual(two['episodes'], [{'id': 42}])
        self.assertEqual(cache.get(('title', '70'), load)['episodes'], [{'id': 42}])

    def test_temporary_error_does_not_poison_future_requests(self):
        cache = CatalogRequestCache()
        self.assertIn('error', cache.get('season', lambda: {'error': 'timeout'}))
        self.assertEqual(cache.get('season', lambda: {'episodes': [1]}), {'episodes': [1]})

    def test_seasons_have_separate_cache_entries(self):
        cache = CatalogRequestCache()
        self.assertEqual(cache.get(('season', '70', 1), lambda: {'episodes': [1]})['episodes'], [1])
        self.assertEqual(cache.get(('season', '70', 2), lambda: {'episodes': [2]})['episodes'], [2])
