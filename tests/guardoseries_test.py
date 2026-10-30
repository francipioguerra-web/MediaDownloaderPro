import unittest
from unittest.mock import patch
from src.guardoseries import Guardaserie
from src.guardoseries import parse_search, parse_details, parse_players, title_id, title_url, source_url

class GuardaserieTests(unittest.TestCase):
    def test_search_keeps_provider_identity_and_lazy_poster(self):
        card = '<a class="ml-mask" href="/serie/a/"><img data-original="https://image.tmdb.org/p.jpg"><h2>A &amp; B</h2></a>'
        items = parse_search(card + card)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['provider'], 'guardoseries')
        self.assertEqual(items[0]['name'], 'A & B')
        self.assertEqual(items[0]['type'], 'tv')
        self.assertEqual(title_url(items[0]['id']), items[0]['watch_url'])
        self.assertEqual(items[0]['poster'], 'https://image.tmdb.org/p.jpg')

    def test_episodes_group_and_sort_without_duplicates(self):
        markup = '<div class="mvic-desc"><h3>A</h3><p class="f-desc">Plot</p></div>'
        for season, episode in [(2, 3), (1, 2), (1, 1), (1, 1)]:
            markup += f'<a href="/episodio/a-stagione-{season}-episodio-{episode}">Episodio {episode}</a>'
        details = parse_details(markup, 'https://guardoseries.click/serie/a/')
        self.assertEqual([s['number'] for s in details['seasons']], [1, 2])
        self.assertEqual([e['number'] for e in details['seasons'][0]['episodes']], [1, 2])
        self.assertEqual(details['seasons'][0]['episodes_count'], 2)

    def test_player_ignores_ads_and_preserves_lazy_embed(self):
        markup = '<iframe src="https://advert.test"></iframe><div class="movieplay"><iframe data-src="https://mload.cam/?v=test" src="data:placeholder"></iframe></div>'
        self.assertEqual(parse_players(markup, 'https://guardoseries.click/a/'), [{'url': 'https://mload.cam/?v=test', 'name': 'Server 1 · mload.cam'}])

    def test_source_failure_is_reported_without_losing_primary_search(self):
        provider = Guardaserie(None)
        with patch.object(provider, 'get', side_effect=ValueError('HTTP 403')):
            self.assertEqual(provider.search('unavailable-test'), [])
        self.assertIn('non disponibile', provider.search_error('unavailable-test'))
        with patch.object(provider, 'get', return_value='<div>Nessun risultato</div>'):
            self.assertEqual(provider.search('unavailable-test'), [])
        self.assertIsNone(provider.search_error('unavailable-test'))

    def test_urls_cannot_escape_source(self):
        for url in ['https://evil.test/a', '//evil.test/a', 'http://guardoseries.click/a', 'https://guardoseries.click:8080/a']:
            with self.assertRaises(ValueError): source_url(url)
        with self.assertRaises(ValueError): title_url('gs-' + b'//evil.test/a'.hex())
        self.assertEqual(title_url(title_id('/serie/a/')), 'https://guardoseries.click/serie/a/')

if __name__ == '__main__': unittest.main()
