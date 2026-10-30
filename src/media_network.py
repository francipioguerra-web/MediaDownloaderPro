"""Retry a media DNS failure with HTTPS DNS, preserving TLS verification."""
def media_get(session, url, **kwargs):
    try:
        return session.get(url, **kwargs)
    except Exception as error:
        if getattr(error, 'code', None) not in (6, 7) and '127.0.0.1' not in str(error):
            raise
        from curl_cffi import requests, CurlOpt
        options = dict(impersonate=getattr(session, 'impersonate', None) or 'chrome120',
                       curl_options={CurlOpt.DOH_URL: b'https://cloudflare-dns.com/dns-query'})
        if kwargs.get('stream'):
            # Streaming outlives get(): a context manager would close this session
            # before its response iterator has delivered the remaining bytes.
            fallback = requests.Session(**options)
            try:
                fallback.headers.update(session.headers)
                fallback.cookies.update(session.cookies)
                response = fallback.get(url, **kwargs)
            except Exception:
                fallback.close()
                raise
            response_close = response.close
            closed = False
            def close():
                nonlocal closed
                if closed:
                    return
                closed = True
                try:
                    response_close()
                finally:
                    fallback.close()
            response.close = close
            return response
        with requests.Session(**options) as fallback:
            fallback.headers.update(session.headers)
            fallback.cookies.update(session.cookies)
            return fallback.get(url, **kwargs)
