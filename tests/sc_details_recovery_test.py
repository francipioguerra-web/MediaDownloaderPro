import ast
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

class DetailsRecoveryTests(unittest.TestCase):
    def method(self):
        tree = ast.parse(Path('app.py').read_text())
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'get_modern_title_details')
        scope = {'time': time, 'parse_title_details': lambda text, domain, identifier: {'id': identifier, 'seasons': [{'number': 1, 'episodes': [{'number': 1}]}]} if text == 'valid' else None}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'app.py', 'exec'), scope)
        return scope['get_modern_title_details']

    def test_transient_details_failure_retries_and_returns_episodes(self):
        calls = []
        def get(url, timeout):
            calls.append(timeout)
            return SimpleNamespace(status_code=200, text='valid' if len(calls) == 2 else 'temporary error')
        engine = SimpleNamespace(get_active_sc_domain=lambda:'https://source.test', _modern_titles={}, _modern_details={}, safe_get=get)
        result = self.method()(engine, '42', '42-serie-streaming')
        self.assertEqual(calls, [8, 15])
        self.assertEqual(result['seasons'][0]['episodes'][0]['number'], 1)

    def test_previously_loaded_episodes_survive_temporary_source_outage(self):
        cached = {'id':'42', 'seasons':[{'number':2, 'episodes':[{'number':3}]}]}
        engine = SimpleNamespace(get_active_sc_domain=lambda:'https://source.test', _modern_titles={}, _modern_details={('https://source.test','42'):(0,cached)}, safe_get=lambda *a,**k:SimpleNamespace(status_code=502,text='unavailable'))
        self.assertIs(self.method()(engine, '42', '42-serie-streaming'), cached)

if __name__ == '__main__': unittest.main()
