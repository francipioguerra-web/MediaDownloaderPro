import unittest
from unittest.mock import Mock
from src.online_subtitles import OnlineSubtitles, to_vtt

class SubtitleTests(unittest.TestCase):
    def test_srt_conversion_preserves_accents_multiline_and_timings(self):
        vtt=to_vtt('1\r\n00:00:26,736 --> 00:00:28,070\r\nCiao, perché?\r\n<i>Seconda riga</i>\r\n'.encode())
        self.assertTrue(vtt.startswith('WEBVTT\n'))
        self.assertIn('00:00:26.736 --> 00:00:28.070',vtt)
        self.assertIn('Ciao, perché?\nSeconda riga',vtt)
    def test_error_pages_and_oversized_files_are_rejected(self):
        for data in (b'<html>Denied</html>',b'x'*(3*1024*1024+1)):
            with self.assertRaises(ValueError):to_vtt(data)
    def test_existing_webvtt_is_not_double_converted(self):
        self.assertEqual(to_vtt(b'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n'),'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n')
    def test_series_identity_requires_exact_episode(self):
        svc=OnlineSubtitles(Mock())
        self.assertEqual(svc.identity({'imdb_id':'tt1190634','type':'tv','current_season_number':2,'current_episode_number':3}),('series','tt1190634:2:3'))
        with self.assertRaises(ValueError):svc.identity({'imdb_id':'tt1190634','type':'tv'})
    def test_search_returns_local_file_ids_deduplicates_and_caches(self):
        response=Mock();response.json.return_value={'subtitles':[
            {'url':'https://subs5.strem.io/en/file/1','lang':'eng'},
            {'url':'https://subs5.strem.io/en/file/2','lang':'ita'},
            {'url':'https://subs5.strem.io/en/file/2','lang':'ita'},
            {'url':'http://127.0.0.1/private','lang':'ita'}]}
        get=Mock(return_value=response);svc=OnlineSubtitles(Mock(),get=get)
        item={'imdb_id':'tt1234567','type':'movie'}
        tracks=svc.search(item);self.assertEqual([t['lang'] for t in tracks],['ita','eng'])
        self.assertTrue(all(t['uri'].startswith('/api/subtitles/file/') for t in tracks))
        self.assertEqual(tracks,svc.search(item));self.assertEqual(get.call_count,1)
    def test_ambiguous_metadata_is_not_replaced_with_first_search_result(self):
        response=Mock();response.json.return_value={'results':[{'id':1,'title':'Dune'},{'id':2,'title':'Dune'}]}
        svc=OnlineSubtitles(Mock(),'key',Mock(return_value=response))
        with self.assertRaisesRegex(ValueError,'certezza'):svc.identity({'name':'Dune','type':'movie'})
    def test_subtitle_download_rejects_redirect_to_private_host(self):
        response=Mock();response.status_code=302;response.headers={'Location':'http://127.0.0.1/secret'}
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        svc=OnlineSubtitles(Mock(),get=Mock(return_value=response));svc.files['test']={'url':'https://subs5.strem.io/file/1','vtt':None}
        with self.assertRaises(ValueError):svc.load('test')
        self.assertEqual(svc.get.call_count,1)
    def test_download_converts_and_caches_valid_file(self):
        response=Mock();response.status_code=200;response.iter_content.return_value=[b'1\n00:00:01,000 --> 00:00:02,000\nHello\n']
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        svc=OnlineSubtitles(Mock(),get=Mock(return_value=response));svc.files['test']={'url':'https://subs5.strem.io/file/1','vtt':None}
        self.assertTrue(svc.load('test').startswith('WEBVTT'));svc.load('test');self.assertEqual(svc.get.call_count,1)
    def test_amateur_credits_purged_completely(self):
        raw = (
            '1\r\n00:00:01,000 --> 00:00:04,000\r\n::Italian Subs Addicted::\r\n[www.italiansubs.net]\r\n\r\n'
            '2\r\n00:00:05,000 --> 00:00:08,000\r\nTraduzione a cura di Mario\r\nCalma, bello.\r\n\r\n'
            '3\r\n00:00:10,000 --> 00:00:12,000\r\nQuante cose si fanno per amore...\r\n\r\n'
            '4\r\n00:00:15,000 --> 00:00:20,000\r\nTranscript: swsub.com\r\n'
        )
        vtt = to_vtt(raw.encode())
        self.assertNotIn('Italian Subs Addicted', vtt)
        self.assertNotIn('italiansubs.net', vtt)
        self.assertNotIn('Traduzione a cura di', vtt)
        self.assertNotIn('swsub.com', vtt)
        self.assertIn('Calma, bello.', vtt)
        self.assertIn('Quante cose si fanno per amore...', vtt)
    def test_search_prioritizes_official_retail_over_fansub(self):
        response = Mock()
        response.json.return_value = {'subtitles': [
            {'url': 'https://subs5.strem.io/en/file/1', 'lang': 'ita', 'movieReleaseName': 'stranger.things.s01e01.sub.ita.subsfactory'},
            {'url': 'https://subs5.strem.io/en/file/2', 'lang': 'ita', 'movieReleaseName': 'Stranger.Things.S01E01.1080p.NF.WEBRip.x264-NTb'},
            {'url': 'https://subs5.strem.io/en/file/3', 'lang': 'ita', 'movieReleaseName': 'Stranger.Things.s01e01.720p.italiansubs'},
            {'url': 'https://subs5.strem.io/en/file/4', 'lang': 'eng', 'movieReleaseName': 'Stranger.Things.S01E01.WEBRip.x264-TURBO'}
        ]}
        svc = OnlineSubtitles(Mock(), get=Mock(return_value=response))
        item = {'imdb_id': 'tt4574334', 'type': 'tv', 'current_season_number': 1, 'current_episode_number': 1}
        tracks = svc.search(item)
        ita_tracks = [t for t in tracks if t['lang'] == 'ita']
        self.assertEqual(len(ita_tracks), 1)
        self.assertIn('(Originale)', ita_tracks[0]['name'])
        self.assertNotIn('subsfactory', ita_tracks[0]['name'])
        self.assertNotIn('italiansubs', ita_tracks[0]['name'])

if __name__=='__main__':unittest.main()
