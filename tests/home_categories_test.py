import json
import unittest
from src.home_categories import GENRES, home_rows, parse_archive_state

class HomeCategoryTests(unittest.TestCase):
    def test_all_genres_replace_old_duplicate_rows_without_changing_featured_rows(self):
        source={'success':True,'source_format':'html','sliders':[{'name':'I titoli del momento','titles':[{'id':'42'}]},{'name':'Animazione','titles':[{'id':'bad-duplicate'}]},{'name':'Azione','titles':[{'id':'bad-duplicate'}]}]}
        result=home_rows(source)
        self.assertEqual(result['sliders'][0]['titles'],[{'id':'42'}])
        genres=[r for r in result['sliders'] if r.get('genre')]
        self.assertEqual([r['name'] for r in genres],GENRES)
        self.assertTrue(all(not r['titles'] for r in genres))
        self.assertTrue(all(r['browse']['genre']==r['name'] for r in genres))
        self.assertEqual(source['sliders'][1]['titles'][0]['id'],'bad-duplicate')

    def test_archive_fallback_keeps_correct_filter_total_and_official_items(self):
        state={'initial':[{'id':42,'title':'Crime series','slug':'crime-series','kind':'series','genres':['Crime']}],'count':1234,'initialFilters':{'Genere':['Crime']},'opts':{'genere':['Crime']}}
        payload='0:'+json.dumps(state)
        markup='<script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
        result=parse_archive_state(markup,'https://source.test')
        self.assertEqual(result['filters']['Genere'],['Crime'])
        self.assertEqual(result['totalCount'],1234)
        self.assertEqual(result['titles'][0]['name'],'Crime series')
        self.assertIsNone(parse_archive_state('<html>Unavailable</html>','https://source.test'))

class GenreFallbackTests(unittest.TestCase):
    def test_missing_source_api_uses_the_right_genre_page_and_does_not_repeat_page_one(self):
        import ast
        import urllib.parse
        from pathlib import Path
        from types import SimpleNamespace
        from src.home_categories import canonical_genre
        tree=ast.parse(Path('app.py').read_text())
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='get_archive_catalog')
        scope={'urllib':__import__('urllib'),'json':json,'canonical_genre':canonical_genre,'parse_archive_state':parse_archive_state}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'app.py','exec'),scope)
        state={'initial':[{'id':42,'title':'Crime series','slug':'crime','kind':'series'}],'count':100,'initialFilters':{'Genere':['Crime']}}
        markup='<script>self.__next_f.push('+json.dumps([1,'0:'+json.dumps(state)])+')</script>'
        urls=[]
        def get(url,timeout):
            urls.append(url)
            return SimpleNamespace(status_code=404 if '/api/' in url else 200,text='Not found' if '/api/' in url else markup)
        engine=SimpleNamespace(get_active_sc_domain=lambda:'https://source.test',safe_get=get,_modern_catalog=True,_modern_titles={})
        result=scope['get_archive_catalog'](engine,genres=['Crime'],sort='updated_at')
        self.assertTrue(result['success']);self.assertEqual(urls[-1],'https://source.test/crime')
        self.assertEqual(result['totalCount'],100);self.assertTrue(result['hasMore'])
        result=scope['get_archive_catalog'](engine,genres=['Crime'],page=2)
        self.assertFalse(result['success']);self.assertEqual(result['titles'],[])

if __name__ == '__main__':unittest.main()
