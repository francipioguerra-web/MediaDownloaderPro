import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from src.guardoseries_stream import parse_master, vixsrc_api, DirectStreams

DOCUMENT = """<script>window.masterPlaylist = {
params: {
 'token': 'public-token', 'expires': '1999999999', 'asn': ''
},
url: 'https://vixsrc.to/playlist/42',
}
</script>"""

class DirectStreamTests(unittest.TestCase):
    def test_master_uses_original_server_and_high_quality_parameters(self):
        url = parse_master(DOCUMENT)
        self.assertEqual(urlsplit(url).path, '/playlist/42')
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['ub'], ['1'])
        self.assertEqual(query['h'], ['1'])
        self.assertEqual(query['token'], ['public-token'])
        self.assertNotIn('asn', query)

    def test_rejects_arbitrary_fetch_destinations(self):
        for url in ['http://vixsrc.to/tv/1/1/1', 'https://evil.test/tv/1/1/1', 'https://vixsrc.to/admin', 'https://vixsrc.to:8443/movie/1']:
            with self.assertRaises(ValueError): vixsrc_api(url)
        self.assertIsNone(parse_master(DOCUMENT.replace('vixsrc.to', 'evil.test')))
        self.assertIsNone(parse_master(DOCUMENT.replace("'token': 'public-token',", '')))

    def test_resolves_refreshes_and_caches_public_player(self):
        def response(text='', data=None):
            return SimpleNamespace(text=text, json=lambda: data, raise_for_status=lambda: None)
        resolver = DirectStreams(object())
        with patch.object(resolver, 'read', side_effect=['{"src":"/embed/42?token=short"}', DOCUMENT] * 2) as fetch:
            result = resolver.extract('https://vixsrc.to/tv/1396/1/1/')
            self.assertEqual(result['provider'], 'guardoseries')
            self.assertEqual(result, resolver.extract('https://vixsrc.to/tv/1396/1/1/'))
            self.assertEqual(fetch.call_count, 2)
            resolver.extract('https://vixsrc.to/tv/1396/1/1/', force=True)
            self.assertEqual(fetch.call_count, 4)

    def test_rejects_external_embed_from_api(self):
        resolver=DirectStreams(object())
        response=SimpleNamespace(json=lambda:{'src':'https://evil.test/embed/42'},raise_for_status=lambda:None)
        with patch.object(resolver,'read',return_value='{"src":"https://evil.test/embed/42"}'):
            with self.assertRaises(ValueError):resolver.extract('https://vixsrc.to/movie/1')

if __name__ == '__main__': unittest.main()
