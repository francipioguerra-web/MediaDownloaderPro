import unittest
from unittest.mock import Mock
from src.download_options import matching_episode, download_options, quality_choices

class DownloadOptionsTests(unittest.TestCase):
    def setUp(self):
        self.item = dict(name='Una Serie', type='tv', current_season_number=2,
            current_episode_number=3, current_watch_url='https://streaming-community.farm/titles/1/watching?s=2&e=3')
        self.catalog = Mock()
        self.catalog.search.return_value = [dict(id='gs-one', name='Una Serie', type='tv')]
        self.catalog.details.return_value = {'seasons':[{'number':2,'episodes':[{'number':3,'watch_url':'https://guardoseries.click/episodio/una-serie-stagione-2-episodio-3/'}]}]}
        self.engine = Mock()
        self.engine.get_stream_qualities.return_value = {'qualities':[{'height':1080},{'height':720},{'height':720}]}

    def test_offers_same_episode_with_only_real_deduplicated_qualities(self):
        sources=download_options(self.engine,self.catalog,self.item)
        self.assertEqual(len(sources),2)
        self.assertIn('stagione-2-episodio-3',sources[1]['url'])
        self.assertEqual([q['value'] for q in sources[1]['qualities']],['1080p','720p'])

    def test_does_not_substitute_different_episode_or_ambiguous_series(self):
        self.item['current_episode_number']=4
        self.assertIsNone(matching_episode(self.catalog,self.item))
        self.item['current_episode_number']=3
        self.catalog.search.return_value.append(dict(id='gs-remake',name='Una Serie',type='tv'))
        self.assertIsNone(matching_episode(self.catalog,self.item))

    def test_unavailable_other_source_does_not_block_original_download(self):
        self.engine.get_stream_qualities.side_effect=lambda url: {'error':'No direct stream'} if 'guardoseries' in url else {'qualities':[{'height':1080}]}
        sources=download_options(self.engine,self.catalog,self.item)
        self.assertEqual(len(sources),1)
        self.assertEqual(sources[0]['provider'],'streamingcommunity')

    def test_unknown_height_is_original_quality_not_invented_1080p(self):
        self.assertEqual(quality_choices({'qualities':[{'height':0}]}),[{'value':'best','label':'Qualità originale'}])

    def test_existing_guardaserie_item_does_not_search_again(self):
        self.item['current_watch_url']='https://guardoseries.click/episodio/one/'
        sources=download_options(self.engine,self.catalog,self.item)
        self.assertEqual(len(sources),1)
        self.catalog.search.assert_not_called()

    def test_network_failure_keeps_original_source_available(self):
        self.engine.get_stream_qualities.side_effect=RuntimeError('offline')
        self.catalog.search.side_effect=RuntimeError('offline')
        sources=download_options(self.engine,self.catalog,self.item)
        self.assertEqual(sources[0]['qualities'][0]['value'],'best')

if __name__=='__main__':unittest.main()
