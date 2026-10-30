import base64,json,unittest
from src.vidxgo import parse_player_source,parse_player_subtitles,media_headers
class PlayerConfigTests(unittest.TestCase):
    def test_plain_and_encoded_configuration(self):
        url='https://cdn.example/hls/movie/master.m3u8?t=temporary&e=123'
        script='let currentSrc = '+json.dumps(url)+';'
        self.assertEqual(parse_player_source('<script>'+script+'</script>'),url)
        key=b'1234abcd';encoded=base64.b64encode(bytes(v^key[i%len(key)] for i,v in enumerate(script.encode()))).decode()
        document="<script>var k='1234abcd',d=atob('"+encoded+"');</script>"
        self.assertEqual(parse_player_source(document),url)
    def test_no_execution_and_invalid_source_is_rejected(self):
        self.assertIsNone(parse_player_source('<script>throw Error("no execution"); let currentSrc="javascript:alert(1)";</script>'))
        self.assertIsNone(parse_player_source('<h1>Access denied</h1>'))
    def test_external_subtitles_use_media_origin_and_keep_provider_referrer(self):
        config={'lang':'ita','forced':False,'url':'/vtt/123/ita.vtt?t=temporary'}
        doc='<script>let currentSrc="https://cdn.example/master.m3u8"; window.__EXTERNAL_SUBS = '+json.dumps([config,{**config,'forced':True,'url':'/forced.vtt'}])+ ';</script>'
        tracks=parse_player_subtitles(doc,'https://v.vidxgo.co/123?info=0')
        self.assertEqual(len(tracks),2);self.assertEqual(tracks[0]['lang'],'ita')
        self.assertEqual(tracks[0]['uri'],'https://cdn.example/vtt/123/ita.vtt?t=temporary')
        self.assertFalse(tracks[0]['forced']);self.assertTrue(tracks[1]['forced'])
    def test_provider_headers_are_not_legacy_headers(self):
        h=media_headers('https://v.vidxgo.co/123?info=0')
        self.assertEqual(h['Origin'],'https://v.vidxgo.co');self.assertEqual(h['Sec-Fetch-Mode'],'cors')
if __name__=='__main__':unittest.main()

class SourceRequestTests(unittest.TestCase):
    def test_source_uses_canonical_domain_and_caches_only_briefly(self):
        import ast,time,threading,urllib.parse
        from pathlib import Path
        from unittest.mock import Mock
        source=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text())
        cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Engine')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='extract_modern_stream')
        page=Mock(status_code=200,text='<link rel="canonical" href="https://streaming-community.farm/titles/1-film"><div class="tc-player-frame"><iframe src="https://v.vidxgo.co/123"></iframe></div>')
        player=Mock(status_code=200,text='<script>let currentSrc="https://cdn.example/master.m3u8?t=temporary";</script>')
        fetch=Mock(side_effect=[page,player]);namespace={'time':time,'urllib':urllib,'media_get':fetch,'parse_player_source':parse_player_source,'parse_player_subtitles':parse_player_subtitles,'media_headers':media_headers}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'source','exec'),namespace)
        peer=Mock();peer._modern_streams={};peer._modern_stream_lock=threading.RLock()
        url='https://streaming-community.coffee/titles/1-film/watching'
        result=namespace['extract_modern_stream'](peer,url)
        self.assertEqual(fetch.call_args_list[1].kwargs['headers']['Referer'],'https://streaming-community.farm/')
        self.assertEqual(result['headers']['Origin'],'https://v.vidxgo.co')
        self.assertEqual(namespace['extract_modern_stream'](peer,url),result)
        self.assertEqual(fetch.call_count,2)

    def test_upstream_denial_is_reported_without_exposing_urls_or_tokens(self):
        import ast, time, threading, urllib.parse
        from pathlib import Path
        from unittest.mock import Mock
        source = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text())
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'Engine')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'extract_modern_stream')
        fetch = Mock(return_value=Mock(status_code=403, text='<h1>Forbidden</h1>'))
        namespace = {'time':time, 'urllib':urllib, 'media_get':fetch}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])), 'source', 'exec'), namespace)
        peer = Mock(); peer._modern_streams = {}; peer._modern_stream_lock = threading.RLock()
        diagnostics = {}
        result = namespace['extract_modern_stream'](peer, 'https://example.test/titles/1/watching', diagnostics=diagnostics)
        self.assertIsNone(result)
        self.assertEqual(diagnostics, {'stage':'watch_page', 'upstream_status':403, 'reason':'iframe_missing'})
