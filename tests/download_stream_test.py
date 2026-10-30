import unittest
from unittest.mock import Mock, patch
from app import engine

class DownloadExtractionTests(unittest.TestCase):
    def test_run_download_unwraps_proxy_and_extracts_modern_stream(self):
        proxy_url = '/api/stream/proxy?url=https%3A%2F%2Fstreamingcommunityz.build%2Fit%2Fwatch%2F42'
        mock_extracted = {
            'master_m3u8': 'https://cdn.example/hls/master.m3u8',
            'vix_url': 'https://vixcloud.cc/embed/42',
            'headers': {'Referer': 'https://vixcloud.cc/embed/42', 'Origin': 'https://vixcloud.cc'},
            'subtitle_tracks': []
        }
        with patch.object(engine, 'extract_sc_m3u8', return_value=mock_extracted) as mock_extract,              patch('yt_dlp.YoutubeDL') as mock_ydl,              patch('os.makedirs'):
            mock_ydl_inst = mock_ydl.return_value.__enter__.return_value
            mock_ydl_inst.extract_info.return_value = {'title': 'Test Movie'}
            mock_ydl_inst.prepare_filename.return_value = '/tmp/test.mp4'

            # Run download logic directly
            engine._run_download(
                download_id='test_dl_1',
                url=proxy_url,
                media_type='hls',
                format_choice='1080p',
                custom_title='Test Movie'
            )

            mock_extract.assert_called_once_with('https://streamingcommunityz.build/it/watch/42')
            opts = mock_ydl.call_args[0][0]
            self.assertEqual(opts['http_headers']['Origin'], 'https://vixcloud.cc')
            self.assertEqual(opts['http_headers']['Referer'], 'https://vixcloud.cc/embed/42')

    def test_download_uses_renewing_local_proxy_without_skipping_missing_fragments(self):
        from tempfile import TemporaryDirectory
        from urllib.parse import urlsplit, parse_qs
        extracted = {
            'master_m3u8': 'https://cdn.example/hls/master.m3u8?t=short-lived',
            'vix_url': 'https://v.vidxgo.co/42/1/1',
            'headers': {'Referer': 'https://v.vidxgo.co/42/1/1'}
        }
        with TemporaryDirectory() as folder, patch.object(engine, 'download_proxy_base', 'http://127.0.0.1:5555', create=True), patch.object(engine, 'extract_sc_m3u8', return_value=extracted), patch('yt_dlp.YoutubeDL') as ydl:
            instance = ydl.return_value.__enter__.return_value
            instance.extract_info.return_value = {'title': 'Fixture'}
            instance.prepare_filename.return_value = folder + '/fixture.mp4'
            engine._run_download('fixture', 'https://source.test/watch', 'hls', '1080p',
                dest_folder=folder, safe_title='fixture')
            url = instance.extract_info.call_args.args[0]
            self.assertEqual(urlsplit(url).netloc, '127.0.0.1:5555')
            self.assertEqual(urlsplit(url).path, '/api/stream/segment')
            self.assertEqual(parse_qs(urlsplit(url).query)['ref'], [extracted['vix_url']])
            self.assertEqual(parse_qs(urlsplit(url).query)['url'], [extracted['master_m3u8']])
            self.assertFalse(ydl.call_args.args[0]['skip_unavailable_fragments'])
            self.assertEqual(ydl.call_args.args[0]['concurrent_fragment_downloads'], 8)

if __name__ == '__main__':
    unittest.main()
