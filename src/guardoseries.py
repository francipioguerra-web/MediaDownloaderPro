"""Guardaserie catalogue adapter; preserve catalogue pages during temporary source outages."""
import re
import subprocess
import time
import threading
import shutil
import os
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit, quote_plus
from bs4 import BeautifulSoup

ORIGIN = 'https://guardoseries.click'
PREFIX = 'gs-'
PLAYER_HOSTS = {'mload.cam', 'mloadm.cam', 'vixsrc.to', 'abyss.to', 'uqload.vc', 'uqload.to', 'uqload.io', 'streamtape.com', 'voe.sx'}


def source_url(value):
    parsed = urlsplit(urljoin(ORIGIN + '/', value or ''))
    if parsed.scheme != 'https' or parsed.hostname != 'guardoseries.click' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('URL Guardaserie non valido')
    return parsed.geturl()


def title_id(url):
    return PREFIX + urlsplit(source_url(url)).path.encode().hex()


def title_url(identifier):
    if not str(identifier).startswith(PREFIX):
        raise ValueError('ID Guardaserie non valido')
    path = bytes.fromhex(str(identifier)[len(PREFIX):]).decode()
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('Percorso Guardaserie non valido')
    return source_url(path)


def image_url(image):
    if image is None:
        return ''
    return next((image.get(key) for key in ('data-original', 'data-src', 'src')
                 if (image.get(key) or '').startswith(('https://', 'http://'))), '')


def parse_search(html):
    soup = BeautifulSoup(html, 'html.parser')
    results, seen = [], set()
    for anchor in soup.select('a.ml-mask'):
        try:
            url = source_url(anchor.get('href'))
        except ValueError:
            continue
        heading = anchor.select_one('h2')
        if not heading or url in seen:
            continue
        seen.add(url)
        name = heading.get_text(' ', strip=True)
        results.append({'id': title_id(url), 'slug': '', 'name': name, 'title': name,
            'type': 'tv' if '/serie/' in urlsplit(url).path else 'movie',
            'poster': image_url(anchor.select_one('img')), 'cover': image_url(anchor.select_one('img')),
            'provider': 'guardoseries', 'source': 'Guardaserie', 'source_format': 'html',
            'watch_url': url, 'title_url': url, 'url': url})
    return results


def parse_details(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('.mvic-desc h3, h1')
    if not heading:
        return {'error': 'Scheda Guardaserie non disponibile'}
    plot = soup.select_one('.f-desc')
    seasons = {}
    for anchor in soup.select('a[href*="/episodio/"]'):
        match = re.search(r'-stagione-(\d+)-episodio-(\d+)', anchor.get('href', ''))
        if not match:
            continue
        try:
            episode_url = source_url(anchor['href'])
        except ValueError:
            continue
        season, number = map(int, match.groups())
        episodes = seasons.setdefault(season, {})
        episodes[number] = {'id': title_id(episode_url), 'number': number, 'season_number': season,
            'name': anchor.get_text(' ', strip=True), 'watch_url': episode_url}
    season_list = [{'number': n, 'name': f'Stagione {n}', 'episodes_count': len(eps),
                    'episodes': [eps[k] for k in sorted(eps)]} for n, eps in sorted(seasons.items())]
    name = heading.get_text(' ', strip=True)
    return {'id': title_id(url), 'name': name, 'title': name, 'provider': 'guardoseries',
        'source': 'Guardaserie', 'source_format': 'html', 'type': 'tv' if season_list or '/serie/' in url else 'movie',
        'plot': plot.get_text(' ', strip=True) if plot else '', 'poster': image_url(soup.select_one('.mvic-thumb img')),
        'cover': image_url(soup.select_one('.mvic-thumb img')), 'watch_url': url, 'title_url': url,
        'seasons': season_list, 'seasons_count': len(season_list)}


def parse_players(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    players = []
    for frame in soup.select('.movieplay iframe'):
        src = urljoin(url, frame.get('data-src') or frame.get('src') or '')
        host = urlsplit(src).hostname
        if urlsplit(src).scheme == 'https' and host in PLAYER_HOSTS and src not in [p['url'] for p in players]:
            players.append({'url': src, 'name': f'Server {len(players) + 1} · {host}'})
    return sorted(players, key=lambda p: urlsplit(p["url"]).hostname != "vixsrc.to")


class Guardaserie:
    _cache = {}
    _search_errors = {}
    _cache_lock = threading.Lock()

    def __init__(self, session):
        self.cached_read = False
        self.cache_file = Path(os.environ.get('DATA_DIR') or Path(__file__).resolve().parent.parent / 'data') / 'guardoseries_pages.json'

    def saved_page(self, url):
        try:
            pages = json.loads(self.cache_file.read_text())
            entry = pages.get(url)
            if entry and time.time() - entry['saved_at'] < 7 * 86400:
                return entry['html']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def save_page(self, url, html):
        with self._cache_lock:
            try:
                pages = json.loads(self.cache_file.read_text())
            except (OSError, ValueError):
                pages = {}
            pages[url] = {'saved_at': time.time(), 'html': html}
            pages = dict(sorted(pages.items(), key=lambda item: item[1]['saved_at'])[-100:])
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.cache_file.with_suffix('.tmp')
                temporary.write_text(json.dumps(pages, ensure_ascii=False))
                temporary.replace(self.cache_file)
            except OSError:
                pass

    def get(self, url):
        url = source_url(url)
        try:
            return self._get_online(url)
        except Exception:
            saved = self.saved_page(url)
            if saved:
                self.cached_read = True
                with self._cache_lock:
                    self._cache[url] = (time.monotonic(), saved)
                return saved
            raise

    def _get_online(self, url):
        url = source_url(url)
        with self._cache_lock:
            cached = self._cache.get(url)
        if cached and time.monotonic() - cached[0] < 120:
            return cached[1]
        # The site's edge rejects the impersonated session used by the primary source.
        if not shutil.which('curl'):
            import requests
            response = requests.get(url, timeout=25)
            response.raise_for_status()
            return response.text
        result = subprocess.run(['curl', '--silent', '--show-error', '--fail', '--location',
            '--proto', '=https', '--proto-redir', '=https', '--max-time', '25', url],
            capture_output=True, timeout=28, check=True)
        html = result.stdout.decode('utf-8', errors='replace')
        if re.search(r'cf-chl-|Just a moment|Ci siamo quasi', html, re.I):
            raise ValueError('Verifica Cloudflare richiesta')
        self.save_page(url, html)
        with self._cache_lock:
            if len(self._cache) > 100:
                self._cache.clear()
            self._cache[url] = (time.monotonic(), html)
        return html

    def search(self, query):
        try:
            results = parse_search(self.get(ORIGIN + '/?s=' + quote_plus(query, safe='')))
            with self._cache_lock:
                if self.cached_read:
                    self._search_errors[query] = 'Guardaserie: risultati salvati, sito temporaneamente non disponibile.'
                else:
                    self._search_errors.pop(query, None)
            return results
        except Exception:
            with self._cache_lock:
                if len(self._search_errors) > 100:
                    self._search_errors.clear()
                self._search_errors[query] = 'Guardaserie temporaneamente non disponibile: verifica o blocco del sito.'
            return []

    @classmethod
    def search_error(cls, query):
        with cls._cache_lock:
            return cls._search_errors.get(query)

    def details(self, identifier):
        try:
            url = title_url(identifier)
            return parse_details(self.get(url), url)
        except Exception:
            return {'error': 'Scheda Guardaserie temporaneamente non disponibile'}

    def players(self, url):
        return parse_players(self.get(url), url)
