import unittest
from unittest.mock import MagicMock, patch
from src.media_network import media_get

class MediaNetworkTests(unittest.TestCase):
    def test_success_uses_existing_session(self):
        session=MagicMock()
        self.assertIs(media_get(session,'https://player.test/',timeout=8),session.get.return_value)
        session.get.assert_called_once_with('https://player.test/',timeout=8)
    def test_only_dns_failure_retries(self):
        class DNSError(Exception):
            code=6
        session=MagicMock();session.get.side_effect=DNSError('DNS failure')
        with patch('curl_cffi.requests.Session') as constructor:
            fallback=constructor.return_value.__enter__.return_value
            self.assertIs(media_get(session,'https://player.test/',timeout=8),fallback.get.return_value)
            fallback.get.assert_called_once_with('https://player.test/',timeout=8)
            options=constructor.call_args.kwargs
            self.assertNotIn('verify', options)
            self.assertIn(b'https://cloudflare-dns.com/dns-query',options['curl_options'].values())
    def test_dns_stream_fallback_lives_until_response_close(self):
        class DNSError(Exception):code=6
        session=MagicMock();session.get.side_effect=DNSError('DNS failure')
        with patch('curl_cffi.requests.Session') as constructor:
            fallback=constructor.return_value
            response=fallback.get.return_value
            original_close=response.close
            result=media_get(session,'https://cdn.test/segment',stream=True)
            self.assertIs(result,response)
            fallback.close.assert_not_called()
            result.close();result.close()
            original_close.assert_called_once()
            fallback.close.assert_called_once()

    def test_tls_and_other_errors_are_not_bypassed(self):
        session=MagicMock();session.get.side_effect=RuntimeError('TLS failure')
        with patch('curl_cffi.requests.Session') as constructor:
            with self.assertRaisesRegex(RuntimeError,'TLS failure'):
                media_get(session,'https://player.test/')
            constructor.assert_not_called()

if __name__=='__main__':unittest.main()
