import ast
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock

source=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text())
engine=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Engine')
method=next(n for n in engine.body if isinstance(n,ast.FunctionDef) and n.name=='get_active_sc_domain')
namespace={'time':time}
exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'domain','exec'),namespace)

class DomainTests(unittest.TestCase):
    def peer(self):
        class Peer: get_active_sc_domain=namespace['get_active_sc_domain']
        p=Peer();p._cached_active_domain='https://old.test';p._domain_verified_at=time.monotonic()-600;p._domain_attempted_at=0;p._domain_lock=threading.Lock();p.candidate_sc_domains=['https://streaming-community.coffee'];p._verify_single_url=Mock(side_effect=lambda url:url if 'coffee' in url else None);p.perform_online_domain_search=Mock(return_value='https://discovered.test');return p
    def test_idle_replaces_failed_cached_domain(self):
        p=self.peer();self.assertEqual(p.get_active_sc_domain(refresh=True),'https://streaming-community.coffee')
        self.assertEqual(p._verify_single_url.call_count,2)
    def test_saved_old_link_does_not_override_cache(self):
        p=self.peer();self.assertEqual(p.get_active_sc_domain('https://obsolete.test'),'https://old.test');p._verify_single_url.assert_not_called()
    def test_recent_check_and_concurrent_check_are_deduplicated(self):
        p=self.peer();p._domain_verified_at=time.monotonic();p.get_active_sc_domain(refresh=True);p._verify_single_url.assert_not_called()
        p._domain_verified_at=0;p._domain_lock.acquire()
        try:self.assertEqual(p.get_active_sc_domain(refresh=True),'https://old.test')
        finally:p._domain_lock.release()
        p._verify_single_url.assert_not_called()
    def test_online_search_and_total_outage(self):
        p=self.peer();p._verify_single_url=Mock(return_value=None);self.assertEqual(p.get_active_sc_domain(refresh=True),'https://old.test');p.perform_online_domain_search.assert_not_called()
        p=self.peer();p._verify_single_url=Mock(return_value=None);p.perform_online_domain_search.return_value=None;self.assertEqual(p.get_active_sc_domain(refresh=True),'https://old.test')

if __name__=='__main__':unittest.main()
