import ast
import json
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from src.catalog_html import normalize_archive_items


class ArchiveBrowseTests(unittest.TestCase):
    def test_categories_and_pagination_use_current_api(self):
        tree = ast.parse(Path('app.py').read_text())
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'get_archive_catalog')
        scope = {'urllib': __import__('urllib'), 'normalize_archive_items': normalize_archive_items, 'json': json}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'app.py', 'exec'), scope)
        for media_type, label in [('movie', 'Film'), ('tv', 'Serie TV'), ('all', None)]:
            with self.subTest(media_type=media_type):
                urls = []
                payload = {'ok': True, 'count': 91, 'items': [{'id': 42, 'title': 'Titolo', 'slug': 'titolo', 'kind': 'series' if media_type == 'tv' else 'movie', 'posterUrl': '/poster.jpg'}]}
                def get(url, timeout):
                    urls.append(url)
                    return SimpleNamespace(status_code=200, text=json.dumps(payload))
                engine = SimpleNamespace(get_active_sc_domain=lambda: 'https://source.test', safe_get=get, _modern_titles={}, _modern_catalog=True)
                result = scope['get_archive_catalog'](engine, media_type=media_type, page=2)
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(urls[0]).query)
                self.assertEqual(query.get('tipo'), [label] if label else None)
                self.assertEqual(query['offset'], ['30'])
                self.assertEqual(result['totalCount'], 91)
                self.assertTrue(result['hasMore'])
                self.assertEqual(result['titles'][0]['type'], 'tv' if media_type == 'tv' else 'movie')
                self.assertTrue(result['titles'][0]['watch_url'].endswith('/titles/42-titolo-streaming/watching'))
                self.assertIn('42', engine._modern_titles)


if __name__ == '__main__':
    unittest.main()
