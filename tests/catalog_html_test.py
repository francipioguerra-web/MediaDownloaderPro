import unittest
from src.catalog_html import parse_home_catalog, parse_archive_catalog, parse_title_details
class CatalogTests(unittest.TestCase):
    def test_new_home_maps_sections_and_metadata(self):
        card='<a href="/titles/42-film-streaming" data-id="42" data-title="Titolo &amp; altro" data-kind="series" data-year="2026" data-preview="/cover.jpg"><img class="img-mobile" src="/poster.jpg"></a>'
        markup='<div class="slider-title"><div class="label">I titoli del momento</div>'+card+card+'</div><div class="slider-title"><div class="label">Top 10 titoli di oggi</div>'+card.replace('42','43')+'</div>'
        result=parse_home_catalog(markup,'https://source.test')
        self.assertTrue(result['success']);self.assertEqual(len(result['sliders']),2)
        row=result['sliders'][0];self.assertEqual(row['name'],'I titoli del momento');self.assertEqual(len(row['titles']),1)
        item=row['titles'][0];self.assertEqual(item['type'],'tv');self.assertEqual(item['name'],'Titolo & altro');self.assertEqual(item['poster'],'https://source.test/poster.jpg');self.assertEqual(item['watch_url'],'https://source.test/titles/42-film-streaming/watching')
    def test_portrait_has_priority_over_first_landscape_image(self):
        markup='<div class="slider-title">Top 10<a data-title="Film" data-id="1" href="/titles/1-film"><img class="img-desktop" src="/landscape.jpg"><img class="img-mobile" src="/portrait.jpg"></a></div>'
        item=parse_home_catalog(markup,'https://source.test')['sliders'][0]['titles'][0]
        self.assertEqual(item['poster'],'https://source.test/portrait.jpg')
        self.assertEqual(item['source_format'],'html')
    def test_archive_results_are_scoped_and_empty_is_valid(self):
        card='<a data-title="Fargo" data-id="1" href="/titles/1-fargo"><img src="/poster.jpg"></a>'
        result=parse_archive_catalog('<div class="archive-page"><div class="arch-grid">'+card+card+'</div></div>'+card.replace('1-fargo','2-other').replace('data-id="1"','data-id="2"'),'https://source.test')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['source'],'StreamingCommunity')
        self.assertEqual(parse_archive_catalog('<div class="archive-page"></div>','https://source.test'),[])
        self.assertIsNone(parse_archive_catalog('Not found','https://source.test'))
    def test_title_and_episode_data_from_split_flight_chunks(self):
        import json
        payload='0:'+json.dumps({'item':{'id':42,'title':'Serie test','kind':'series','slug':'serie','posterUrl':'/p.jpg'},'seasons':[{'number':2,'episodes':[{'number':3,'title':'Terzo','still':'/ep.jpg'}]}]})
        middle=len(payload)//2
        document=''.join('<script>self.__next_f.push('+json.dumps([1,part])+')</script>' for part in [payload[:middle],payload[middle:]])
        item=parse_title_details(document,'https://source.test','42')
        self.assertEqual(item['name'],'Serie test');self.assertEqual(item['seasons'][0]['episodes_count'],1)
        ep=item['seasons'][0]['episodes'][0]
        self.assertEqual(ep['name'],'Terzo');self.assertTrue(ep['watch_url'].endswith('/watching?s=2&e=3'))
        self.assertIsNone(parse_title_details(document,'https://source.test','99'))
    def test_empty_home_category_keeps_its_source_link(self):
        row=parse_home_catalog('<div class="slider-title"><div class="row-header"><a href="/animazione"><div class="label">Animazione</div></a></div></div>','https://source.test')['sliders'][0]
        self.assertEqual(row['name'],'Animazione');self.assertEqual(row['category_path'],'/animazione')
    def test_cover_alias_follows_current_canonical_domain(self):
        doc='<link rel="canonical" href="https://streaming-community.farm/animazione"><div class="archive-page"><div class="arch-grid"><a data-title="Animation" data-id="1" href="/titles/1-animation"><img class="img-mobile" src="https://img.streaming-community.coffee/t/p/w500/cover.jpg"></a></div></div>'
        result=parse_archive_catalog(doc,'https://streaming-community.coffee')
        self.assertEqual(result[0]['poster'],'https://image.tmdb.org/t/p/w500/cover.jpg')
        self.assertTrue(result[0]['watch_url'].startswith('https://streaming-community.farm/'))
    def test_error_page_is_not_a_catalog(self):
        self.assertIsNone(parse_home_catalog('<h1>Unavailable</h1>','https://source.test'))
if __name__=='__main__':unittest.main()
