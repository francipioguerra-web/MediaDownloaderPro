import tempfile
import threading
import time
import unittest
from pathlib import Path
from src.home_catalog_cache import HomeCatalogCache

CATALOG = {'success': True, 'sliders': [{'titles': [{'id':'42'}]}]}

class HomeCatalogCacheTests(unittest.TestCase):
    def test_initial_titles_are_returned_before_category_enrichment_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = HomeCatalogCache(str(Path(folder)/'home.json'))
            release = threading.Event()
            def load():
                cache.publish(CATALOG)
                release.wait(2)
                return CATALOG
            try:
                start = time.monotonic()
                self.assertEqual(cache.get(load), CATALOG)
                self.assertLess(time.monotonic()-start, .5)
            finally:
                release.set()
                with cache.condition: cache.condition.wait_for(lambda: not cache.running, timeout=3)

    def test_saved_catalog_survives_restart_and_outage(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'home.json')
            HomeCatalogCache(path).publish(CATALOG)
            cache = HomeCatalogCache(path, ttl=0)
            self.assertEqual(cache.get(lambda: {'success':False}), CATALOG)
            self.assertEqual(cache.value, CATALOG)
            with cache.condition: cache.condition.wait_for(lambda: not cache.running, timeout=3)

    def test_concurrent_requests_share_a_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = HomeCatalogCache(str(Path(folder)/'home.json'))
            cache.publish(CATALOG);cache.updated=0
            calls=[];release=threading.Event()
            def load():
                calls.append(1);release.wait(2);return CATALOG
            try:
                for _ in range(10):self.assertEqual(cache.get(load),CATALOG)
                self.assertEqual(len(calls),1)
            finally:
                release.set()
                with cache.condition: cache.condition.wait_for(lambda: not cache.running, timeout=3)

if __name__ == '__main__': unittest.main()
