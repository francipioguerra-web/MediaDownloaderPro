"""Resolve public player configuration to a direct HLS stream without executing scripts."""
import json
import re
import time
import threading
import subprocess
import shutil
from urllib.parse import urlsplit, urljoin, urlencode, parse_qsl
from src.media_network import media_get
from src.vidxgo import media_headers, parse_player_source, parse_player_subtitles


def vixsrc_api(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'vixsrc.to' or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise ValueError('Server video non valido')
    match = re.fullmatch(r'/(tv/\d+/\d+/\d+|movie/\d+)/?', parsed.path)
    if not match:
        raise ValueError('Percorso video non valido')
    return 'https://vixsrc.to/api/' + match[1]


def parse_master(document):
    block = re.search(r'window\.masterPlaylist\s*=\s*\{([\s\S]*?)\n\s*\}(?!\s*,)', document)
    if not block:
        return parse_player_source(document)
    match = re.search(r'\burl\s*:\s*[\'\"]([^\'\"]+)', block[1])
    if not match:
        return None
    base = match[1]
    target = urlsplit(base)
    if target.scheme != 'https' or target.hostname != 'vixsrc.to' or not re.fullmatch(r'/playlist/\d+', target.path):
        return None
    params = dict(parse_qsl(target.query))
    for key in ('token', 'expires', 'asn'):
        value = re.search(r'[\'\"]' + key + r'[\'\"]\s*:\s*[\'\"]([^\'\"]*)', block[1])
        if value and value[1]:
            params[key] = value[1]
    if not all(params.get(k) for k in ('token', 'expires')):
        return None
    # These select the same server and quality exposed by the original player.
    params.update(ub='1', h='1')
    return base + '?' + urlencode(params)


class DirectStreams:
    def __init__(self, session):
        self.session = session
        self.cache = {}
        self.lock = threading.Lock()

    def read(self, url, referrer):
        if shutil.which('curl'):
            for attempt in range(2):
                try:
                    result = subprocess.run(['curl', '--silent', '--show-error', '--fail', '--location',
                        '--proto', '=https', '--proto-redir', '=https', '--max-time', '20',
                        '--referer', referrer, url], capture_output=True, check=True, timeout=23)
                    return result.stdout.decode('utf-8', errors='replace')
                except subprocess.CalledProcessError as error:
                    if attempt or error.returncode != 28:
                        raise
        response = media_get(self.session, url, headers=media_headers(referrer), timeout=20)
        response.raise_for_status()
        return response.text

    def extract(self, player, force=False):
        api = vixsrc_api(player)
        with self.lock:
            cached = self.cache.get(player)
        if cached and not force and time.monotonic() - cached[0] < 45:
            return cached[1]
        payload = json.loads(self.read(api + '?' + urlencode({'_': int(time.time())}), 'https://guardoseries.click/'))
        embed = urljoin('https://vixsrc.to', payload.get('src', ''))
        parsed = urlsplit(embed)
        if (parsed.scheme != 'https' or parsed.hostname != 'vixsrc.to' or parsed.port not in (None, 443)
                or parsed.username or parsed.password or not re.fullmatch(r'/embed/\d+', parsed.path)):
            raise ValueError('Il server non ha restituito un video valido')
        document = self.read(embed, player)
        master = parse_master(document)
        if not master:
            raise ValueError('Manifest video non disponibile sul server')
        result = {'master_m3u8': master, 'vix_url': player, 'headers': media_headers(player),
                  'subtitle_tracks': parse_player_subtitles(document, embed), 'provider': 'guardoseries'}
        with self.lock:
            if len(self.cache) > 100:
                self.cache.clear()
            self.cache[player] = (time.monotonic(), result)
        return result
