"""Exercise the actual proxy route without initializing the catalog engine."""
import ast
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from flask import Flask, Response, jsonify, request


class ProgressiveSCTests(unittest.TestCase):
    def test_range_and_first_bytes_arrive_without_buffering_and_abort_closes_origin(self):
        state = {'reads': 0, 'closed': False}
        class Upstream:
            status_code = 206
            headers = {'Content-Length': '6', 'Content-Range': 'bytes 0-5/100'}
            @property
            def content(self):
                raise AssertionError('Proxy must not download the whole video segment')
            def iter_content(self, chunk_size):
                for chunk in [b'abc', b'def']:
                    state['reads'] += 1
                    yield chunk
            def close(self): state['closed'] = True
        session = SimpleNamespace(close=lambda: None)
        def fetch(client, url, **options):
            self.assertIs(client, session)
            self.assertTrue(options['stream'])
            self.assertEqual(options['headers']['Range'], 'bytes=0-5')
            return Upstream()
        node = next(n for n in ast.parse(Path('app.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'stream_proxy_segment')
        node.decorator_list = []
        env = dict(Response=Response, jsonify=jsonify, request=request, urllib=urllib,
                   media_get=fetch, cffi_requests=SimpleNamespace(Session=lambda **options: session),
                   engine=SimpleNamespace(sc_stream_tokens=SimpleNamespace(sign=lambda url,ref,**kwargs:url)))
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), env)
        app = Flask(__name__)
        app.add_url_rule('/segment', view_func=env['stream_proxy_segment'])
        with app.test_client() as client:
            result = client.get('/segment?url=https://cdn.test/segment.ts',
                                headers={'Range': 'bytes=0-5'}, buffered=False)
            self.assertEqual(result.status_code, 206)
            self.assertEqual(result.headers['Content-Range'], 'bytes 0-5/100')
            self.assertEqual(next(result.response), b'abc')
            self.assertEqual(state['reads'], 1)
            result.close()
            self.assertTrue(state['closed'])

if __name__ == '__main__': unittest.main()
