import os
import sys
import re
import json
import time
import shutil
import urllib.parse
import threading
import html as html_module
import subprocess
from concurrent.futures import ThreadPoolExecutor
import io
import random
from src.guardoseries_stream import DirectStreams
from src.guardoseries import Guardaserie
from src.home_catalog_cache import HomeCatalogCache
from src.catalog_request_cache import CatalogRequestCache
from src.home_categories import GENRES, canonical_genre, home_rows, parse_archive_state
import requests
try:
    from curl_cffi import requests as cffi_requests, curl
except (ImportError, Exception):
    import requests as _std_requests
    class MockCurl:
        pass
    curl = MockCurl()

    class CompatSession(_std_requests.Session):
        def __init__(self, impersonate=None, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7'
            })
    class CompatRequestsModule:
        Session = CompatSession
        get = _std_requests.get
        post = _std_requests.post
        put = _std_requests.put
        delete = _std_requests.delete
        head = _std_requests.head
        options = _std_requests.options
    cffi_requests = CompatRequestsModule()

from flask import Flask, render_template, request, jsonify, Response, redirect, make_response
from src.media_network import media_get
from src.catalog_html import match_title
from src.sc_stream_tokens import StreamTokens
from src.vidxgo import parse_player_source, parse_player_subtitles, media_headers, manifest_metadata
PRIMARY_DOMAIN = 'https://streaming-community.biz' 
from src.catalog_html import parse_home_catalog, parse_archive_catalog, parse_title_details, source_origin, normalize_archive_items

# -------------------------------------------------------------
# ENVIRONMENT & PATH FIX FOR FFMPEG ON MACOS
# -------------------------------------------------------------
extra_paths = ['/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin']
for p in extra_paths:
    if p not in os.environ.get('PATH', ''):
        os.environ['PATH'] = f"{p}:{os.environ.get('PATH', '')}"

def get_ffmpeg_executable():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, 'ffmpeg.exe'),
        os.path.join(base_dir, 'ffmpeg'),
        os.path.join(os.path.dirname(sys.executable), 'ffmpeg.exe'),
        '/opt/homebrew/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        '/usr/bin/ffmpeg'
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return shutil.which('ffmpeg.exe') or shutil.which('ffmpeg') or 'ffmpeg'

# -------------------------------------------------------------
# FLASK APP SETUP
# -------------------------------------------------------------
_base_dir = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    template_folder = os.path.join(_base_dir, 'templates')
    static_folder = os.path.join(_base_dir, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

try:
    from flask_socketio import SocketIO, emit, join_room, leave_room
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        ping_timeout=10,
        ping_interval=5,
        manage_session=False
    )
    SOCKETIO_AVAILABLE = True
except Exception:
    socketio = None
    SOCKETIO_AVAILABLE = False

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        res = make_response()
        res.headers['Access-Control-Allow-Origin'] = '*'
        res.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        res.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        return res

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    return response

DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR") or (os.path.join(os.environ["DATA_DIR"], "downloads") if os.environ.get("DATA_DIR") else os.path.expanduser("~/Downloads"))
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

if getattr(sys, 'frozen', False):
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_DIR = os.path.join(BASE_DIR, "user_data_seed")
RUNTIME_DATA_DIR = os.environ.get('DATA_DIR') or os.path.join(BASE_DIR, 'data')
os.makedirs(RUNTIME_DATA_DIR, exist_ok=True)
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')
if not TMDB_API_KEY:
    try:
        with open(os.path.join(BASE_DIR, '.tmdb_api_key')) as local_key:
            TMDB_API_KEY = local_key.read().strip()
    except OSError:
        pass


def user_data_file(filename, legacy_path):
    return os.path.join(RUNTIME_DATA_DIR, filename) if os.environ.get('DATA_DIR') else os.path.expanduser(legacy_path)


def ensure_seed_data(target_file, seed_filename):
    try:
        if not os.path.exists(target_file) or os.path.getsize(target_file) == 0:
            seed_path = os.path.join(SEED_DIR, seed_filename)
            if os.path.exists(seed_path):
                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                shutil.copyfile(seed_path, target_file)
                print(f"[DATA SEED] Inizializzato {target_file} dai dati di default: {seed_filename}")
    except Exception as e:
        print(f"[DATA SEED] Errore inizializzazione {seed_filename}:", e)
    return target_file

# -------------------------------------------------------------
# CORE ENGINE: HOME CATALOG & STREAMINGCOMMUNITY DOWNLOADER
# -------------------------------------------------------------
class Engine:
    def __init__(self):
        self.session = cffi_requests.Session(impersonate='chrome120')
        self.candidate_sc_domains = [PRIMARY_DOMAIN]
        self.primary_vixcloud = False
        self.sc_stream_tokens = StreamTokens(self.refresh_sc_stream_source)
        self._primary_search_cache = {}
        self.guardoserie_streams = DirectStreams(self.session)
        self._catalog_requests = CatalogRequestCache()
        self._cached_active_domain = PRIMARY_DOMAIN
        self._domain_verified_at = 0
        self._domain_attempted_at = 0
        self._domain_lock = threading.Lock()
        self._modern_catalog = True
        self._modern_titles = {}
        self._modern_details = {}
        self._home_genre_cache = {}
        self._home_genre_lock = threading.RLock()
        self._home_genre_file = os.path.join(RUNTIME_DATA_DIR, 'home_genres_cache.json')
        try:
            with open(self._home_genre_file) as source:self._home_genre_cache=json.load(source)
        except (OSError,ValueError):pass
        self._modern_streams = {}
        self._modern_stream_lock = threading.RLock()
        self._guardaserie_streams = {}
        self._guardaserie_stream_lock = threading.RLock()
        self.home_catalog_cache = HomeCatalogCache(os.path.join(RUNTIME_DATA_DIR, 'home_catalog_cache.json'))
        if self.home_catalog_cache.value:
            self._cached_active_domain = self.home_catalog_cache.value.get('domain')
            self._modern_catalog = self.home_catalog_cache.value.get('source_format') == 'html'
        self.downloads = {}
        self.processes = {}
        self.canceled_downloads = set()
        self.dates_cache_file = os.path.join(RUNTIME_DATA_DIR, 'dates_cache.json')
        self.dates_cache = self._load_dates_cache()
        self._cached_archive_genres = []
        self._cached_archive_countries = []

    def _load_dates_cache(self):
        try:
            if os.path.exists(self.dates_cache_file):
                with open(self.dates_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            print("Error loading dates cache:", e)
        return {}

    def _save_dates_cache(self):
        try:
            with open(self.dates_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.dates_cache, f, ensure_ascii=False)
        except Exception as e:
            print("Error saving dates cache:", e)

    def _resolve_doh_ips(self, hostname):
        ips = []
        try:
            r = self.session.get(f"https://1.1.1.1/dns-query?name={hostname}&type=A", headers={'accept': 'application/dns-json'}, timeout=3)
            if r.status_code == 200:
                data = r.json()
                ips.extend([a['data'] for a in data.get('Answer', []) if a.get('type') == 1])
        except Exception:
            pass
        if not ips:
            try:
                r = self.session.get(f"https://8.8.8.8/resolve?name={hostname}&type=A", timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    ips.extend([a['data'] for a in data.get('Answer', []) if a.get('type') == 1])
            except Exception:
                pass
        return list(set(ips))

    def _verify_single_url(self, url):
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.netloc
            if not hostname:
                return None
            ips = self._resolve_doh_ips(hostname)
            
            c = curl.Curl()
            c.impersonate('chrome120')
            c.setopt(curl.CurlOpt.URL, url)
            if ips:
                c.setopt(curl.CurlOpt.RESOLVE, [f'{hostname}:443:{ip}' for ip in ips] + [f'{hostname}:80:{ip}' for ip in ips])
            c.setopt(curl.CurlOpt.FOLLOWLOCATION, 1)
            c.setopt(curl.CurlOpt.ACCEPT_ENCODING, b'')
            c.setopt(curl.CurlOpt.TIMEOUT, 5)
            
            buf = io.BytesIO()
            c.setopt(curl.CurlOpt.WRITEDATA, buf)
            c.perform()
            st = c.getinfo(curl.CurlInfo.RESPONSE_CODE)
            eff = c.getinfo(curl.CurlInfo.EFFECTIVE_URL)
            body = buf.getvalue().decode('utf-8', errors='ignore')
            c.close()
            
            eff_str = eff.decode() if isinstance(eff, bytes) else eff
            is_valid = st == 200 and (re.search(r'streaming[- ]?community', body, re.I) or 'inertia' in body.lower() or 'data-page' in body.lower())
            if is_valid:
                from bs4 import BeautifulSoup
                p_eff = urllib.parse.urlparse(eff_str)
                return source_origin(BeautifulSoup(body, 'html.parser'), f"{p_eff.scheme}://{p_eff.netloc}")
        except Exception:
            pass
        return None

    def safe_get(self, url, headers=None, timeout=6):
        # DNS fallback is useful only for a DNS failure. Retrying every timeout
        # through two resolvers previously multiplied a single catalog wait.
        try:
            return media_get(self.session, url, headers=headers, timeout=timeout)
        except Exception:
            class UnavailableResponse:
                status_code = 503
                text = ''
                def json(self): return {}
            return UnavailableResponse()

    def perform_online_domain_search(self):
        discovered = []
        try:
            r = self.session.get('https://html.duckduckgo.com/html/?q=streamingcommunity+nuovo+dominio', timeout=4)
            if r.status_code == 200:
                found = re.findall(r'https?://[a-zA-Z0-9\.-]*streaming[a-zA-Z0-9\.-]*\.[a-z]{2,}', r.text)
                discovered.extend(found)
        except Exception:
            pass

        entrypoints = [
            "https://streaming-community.coffee",
            "https://streamingcommunityz.luxe",
            "https://streaming-communityz.art",
            "https://streamingcommunityz.art",
            "https://streamingcommunity.cx",
            "https://streamingcommunityz.systems",
            "https://streamingcommunityz.support",
            "https://streamingcommunity.computer",
            "https://streamingcommunityz.cloud",
            "https://streamingcommunity.tech",
            "https://streamingcommunity.paris",
            "https://streamingcommunity.co"
        ]
        discovered.extend(entrypoints)

        candidates = []
        seen = set()
        for u in discovered:
            try:
                p = urllib.parse.urlparse(u)
                if 'streaming' in p.netloc.lower():
                    base = f"{p.scheme}://{p.netloc}"
                    if base not in seen:
                        seen.add(base)
                        candidates.append(base)
            except Exception:
                pass

        for cand in candidates:
            verified = self._verify_single_url(cand)
            if verified:
                return verified

        return None

    def get_active_sc_domain(self, target_url=None, refresh=False):
        # Normal requests keep using the current authority. Only the idle
        # refresh revalidates it; saved links must not restore an old domain.
        if self._cached_active_domain and not refresh:
            return self._cached_active_domain
        now = time.monotonic()
        if refresh and self._cached_active_domain:
            if now - self._domain_verified_at < 300 or now - self._domain_attempted_at < 60:
                return self._cached_active_domain
        if not self._domain_lock.acquire(blocking=False):
            return self._cached_active_domain or self.candidate_sc_domains[0]
        try:
            self._domain_attempted_at = now
            candidates = [self._cached_active_domain] if self._cached_active_domain else []
            candidates.extend(self.candidate_sc_domains)
            if target_url and target_url.startswith(('https://', 'http://')):
                candidates.append(target_url)
            for candidate in dict.fromkeys(c for c in candidates if c):
                verified = self._verify_single_url(candidate)
                if verified:
                    self._cached_active_domain = verified
                    self._domain_verified_at = time.monotonic()
                    return verified
            # A transient outage must not replace the last working domain.
            return self._cached_active_domain or self.candidate_sc_domains[0]
        finally:
            self._domain_lock.release()

    def extract_sc_images(self, item, cdn_url):
        poster = None
        cover = None
        background = None
        cover_mobile = None
        images = (item.get('images') or []) if isinstance(item, dict) else []
        for img in images:
            if isinstance(img, dict):
                t = img.get('type')
                fn = img.get('filename')
                if fn:
                    original = img.get('original_url_field') or img.get('original_url')
                    u = original if isinstance(original, str) and original.startswith('https://') else f"{cdn_url}/images/{fn}"
                    if 'image.tmdb.org/t/p/' in u:
                        u = re.sub(r'/t/p/[^/]+/', '/t/p/original/', u)
                    if t == 'poster' and not poster:
                        poster = u
                    elif t == 'background' and not background:
                        background = u
                    elif t == 'cover' and not cover:
                        cover = u
                    elif t == 'cover_mobile' and not cover_mobile:
                        cover_mobile = u
        
        if not poster and isinstance(item, dict):
            p = item.get('poster')
            if p: poster = p if p.startswith('http') else f"{cdn_url}/images/{p}"
        if not background and isinstance(item, dict):
            bg = item.get('background')
            if bg: background = bg if bg.startswith('http') else f"{cdn_url}/images/{bg}"
        if not cover and isinstance(item, dict):
            c = item.get('cover')
            if c: cover = c if c.startswith('http') else f"{cdn_url}/images/{c}"
            
        def _to_tmdb(img_u):
            if not img_u or not isinstance(img_u, str): return img_u
            if '/t/p/' in img_u:
                m = re.search(r'/t/p/([^/]+)/(.+)$', img_u)
                if m: return f"https://image.tmdb.org/t/p/{m.group(1)}/{m.group(2)}"
            return img_u
        best_cover = _to_tmdb(background or cover or cover_mobile or poster)
        best_poster = _to_tmdb(poster or cover or background)
        return best_poster, best_cover

    @staticmethod
    def _sanitize_media_item(item):
        if not isinstance(item, dict): return item
        for k in ('poster', 'cover', 'backdrop', 'image'):
            val = item.get(k)
            if val and isinstance(val, str) and '/t/p/' in val:
                m = re.search(r'/t/p/([^/]+)/(.+)$', val)
                if m:
                    item[k] = f"https://image.tmdb.org/t/p/{m.group(1)}/{m.group(2)}"
        return item

    def get_home_catalog(self):
        catalog = self.home_catalog_cache.get(self._fetch_home_catalog)
        catalog = home_rows(catalog)
        # Publish already loaded genres with the home itself. Reopening Home
        # must not turn usable carousels back into empty loading rows.
        for row in catalog.get('sliders', []):
            cached = self._home_genre_cache.get(row.get('genre'))
            if cached and cached[1].get('titles'):
                row['titles'] = cached[1]['titles'][:20]
            for item in row.get('titles', []):
                self._sanitize_media_item(item)
        if catalog.get('featured'):
            self._sanitize_media_item(catalog['featured'])
        if catalog.get('source_format') == 'html':
            self._modern_catalog = True
            for row in catalog.get('sliders', []):
                for item in row.get('titles', []):
                    self._modern_titles[str(item['id'])] = item
        return catalog

    def _fetch_home_catalog(self):
        try:
            catalog = None
            active_domain = self._cached_active_domain or (self.home_catalog_cache.value or {}).get('domain') or self.candidate_sc_domains[0]
            cdn_url = f"https://cdn.{active_domain.replace('https://', '')}"
            r_home = self.safe_get(f"{active_domain}/", timeout=6)
            # Newer domains serve the catalog at / using rendered HTML.
            if r_home.status_code != 200 or not re.search(r"data-page=[\"']", r_home.text):
                root_home = r_home
                if root_home.status_code == 200:
                    catalog = parse_home_catalog(root_home.text, active_domain)
                    if catalog:
                        self._modern_catalog = True
                        self._cached_active_domain = active_domain
                        self.home_catalog_cache.publish(catalog)
                        catalog['sliders'] = [r for r in catalog['sliders'] if not r.get('category_path')]
                        for row in catalog['sliders']:
                            for item in row['titles']:
                                self._modern_titles[str(item['id'])] = item
                        return catalog
                    r_home = root_home
                if not self.home_catalog_cache.usable(catalog):
                    r_home = self.safe_get(f"{active_domain}/it", timeout=6)
            if r_home and r_home.status_code == 200:
                match = re.search(r'data-page=\"(.*?)\"', r_home.text) or re.search(r"data-page='(.*?)'", r_home.text)
                if match:
                    dp = json.loads(html_module.unescape(match.group(1)))
                    props = dp.get('props', {})
                    raw_sliders = props.get('sliders') or []
                    cdn = props.get('cdn_url') or cdn_url

                    def parse_t(t):
                        if not isinstance(t, dict): return None
                        tid = t.get('id')
                        if not tid: return None
                        str_tid = str(tid)
                        slug = t.get('slug') or t.get('name', '').lower().replace(' ', '-').replace(':', '')
                        poster_url, cover_url = self.extract_sc_images(t, cdn)

                        cached_rel = self.dates_cache.get(str_tid)
                        raw_rel = cached_rel or t.get('release_date') or t.get('year') or t.get('last_air_date') or t.get('last_air_date_it') or t.get('first_air_date') or ''
                        clean_rel = str(raw_rel).strip()
                        if clean_rel == '2024' and not cached_rel:
                            clean_rel = str(t.get('last_air_date') or t.get('last_air_date_it') or t.get('first_air_date') or '').strip()

                        return {
                            "id": tid,
                            "name": t.get('name', ''),
                            "type": t.get('type') or 'movie',
                            "slug": slug,
                            "release_date": clean_rel,
                            "score": t.get('score') or '',
                            "seasons_count": t.get('seasons_count') or 0,
                            "poster": poster_url,
                            "backdrop": cover_url or poster_url,
                            "cover": cover_url or poster_url,
                            "plot": t.get('plot') or 'Nessuna trama disponibile.',
                            "source_format": "inertia", "source": "StreamingCommunity",
                            "watch_url": f"{active_domain}/it/watch/{tid}"
                        }

                    clean_sliders = []
                    for s in raw_sliders:
                        if isinstance(s, dict):
                            s_name = s.get('name') or 'Catalogo'
                            titles_list = [parse_t(t) for t in (s.get('titles') or []) if parse_t(t)]
                            clean_sliders.append({
                                "name": s_name,
                                "titles": titles_list
                            })

                    clean_featured = None
                    if props.get('featured'):
                        clean_featured = parse_t(props['featured'])

                    if not clean_featured and props.get('title'):
                        feature = dict(props['title'])
                        known = next((title for slider in raw_sliders for title in slider.get('titles', [])
                                      if str(title.get('id')) == str(feature.get('id'))), {})
                        feature['type'] = feature.get('type') or known.get('type') or 'movie'
                        clean_featured = parse_t(feature)
                    self._modern_catalog = False
                    catalog = {"success": True, "domain": active_domain, "source_format": "inertia",
                               "featured": clean_featured or parse_t(props.get('title')),
                               "genres": props.get('genres') or [], "sliders": clean_sliders}
                    self.home_catalog_cache.publish(catalog)
                    return catalog

        except Exception as ex:
            print("Home catalog parse error:", ex)
        return {"success": False, "domain": self.candidate_sc_domains[0], "sliders": []}

    def get_random_movie(self):
        try:
            active_domain = self.get_active_sc_domain()
            cdn_url = f"https://cdn.{active_domain.replace('https://', '')}"

            def parse_item(t):
                if not isinstance(t, dict): return None
                tid = t.get('id')
                if not tid: return None
                slug = t.get('slug') or t.get('name', '').lower().replace(' ', '-').replace(':', '')
                poster_url, cover_url = self.extract_sc_images(t, cdn_url)
                t_genres = []
                for tg in (t.get('genres') or []):
                    if isinstance(tg, dict):
                        g_name = tg.get('name')
                        for tr in (tg.get('translations') or []):
                            if isinstance(tr, dict) and tr.get('key') == 'name' and tr.get('value'):
                                g_name = tr.get('value')
                                break
                        if g_name:
                            t_genres.append(g_name)

                return {
                    "id": tid,
                    "name": t.get('name'),
                    "type": t.get('type') or 'movie',
                    "slug": slug,
                    "release_date": t.get('release_date') or t.get('year') or '',
                    "poster": poster_url,
                    "cover": cover_url,
                    "plot": t.get('plot', ''),
                    "genres": t_genres,
                    "score": t.get('score') or t.get('vote_average') or '',
                    "runtime": t.get('runtime') or '',
                    "watch_url": f"{active_domain}/it/watch/{tid}"
                }

            # 1. Try archive pages with a random page number between 1 and 60
            candidate_items = []
            for _ in range(3):
                rand_page = random.randint(1, 50)
                url = f"{active_domain}/it/archive?type=movie&page={rand_page}"
                res = self.safe_get(url, timeout=5)
                if res.status_code == 200:
                    match = re.search(r'data-page=\"(.*?)\"', res.text) or re.search(r"data-page='(.*?)'", res.text)
                    if match:
                        try:
                            dp = json.loads(html_module.unescape(match.group(1)))
                            props = dp.get('props', {})
                            titles = props.get('titles') or []
                            parsed = [parse_item(t) for t in titles if parse_item(t) and (t.get('type') == 'movie' or not t.get('type'))]
                            if parsed:
                                candidate_items.extend(parsed)
                                break
                        except Exception:
                            pass

            if candidate_items:
                chosen = random.choice(candidate_items)
                det = self.get_title_details(chosen['id'], chosen.get('slug', ''))
                if isinstance(det, dict) and not det.get('error'):
                    for k in ['name', 'plot', 'genres', 'cover', 'poster', 'runtime', 'release_date', 'score']:
                        if det.get(k): chosen[k] = det[k]
                return {"success": True, "movie": chosen}

            # Fallback: Pick random movie from home sliders
            home_data = self.get_home_catalog()
            sliders = home_data.get('sliders', [])
            all_pool = []
            for sl in sliders:
                for it in sl.get('items', []):
                    if it.get('type') == 'movie' or not it.get('type'):
                        all_pool.append(it)
            if all_pool:
                chosen = random.choice(all_pool)
                return {"success": True, "movie": chosen}

            return {"success": False, "error": "Nessun film trovato nel catalogo."}
        except Exception as ex:
            return {"success": False, "error": str(ex)}

    def resolve_primary_item(self, item):
        name = str(item.get('name') or item.get('title') or '').strip()[:200]
        match = match_title(item, self.search_streamingcommunity(name)) if name else None
        if not match:
            return {'success': False, 'error': 'Titolo non identificato nel catalogo StreamingCommunity ripristinato. Cercalo nella ricerca.'}
        target = {**item, **match, 'provider': 'streamingcommunity', 'source': 'StreamingCommunity',
                  'source_format': 'html', 'seasons': [], 'title_url': '', 'external_url': '',
                  'current_watch_url': '', 'current_episode_id': None}
        for field in ('series_id', 'titleId'):
            if field in target: target[field] = match['id']
        number = item.get('current_episode_number')
        if number and match.get('type') == 'tv':
            season = int(item.get('current_season_number') or 1)
            episodes = self.get_season_episodes(match['id'], match.get('slug', ''), season).get('episodes', [])
            selected = next((episode for episode in episodes if int(episode.get('number') or 0) == int(number)), None)
            if not selected:
                return {'success': False, 'error': 'Episodio non disponibile nel catalogo StreamingCommunity ripristinato.'}
            target.update(current_episode_id=selected['id'], current_watch_url=selected['watch_url'],
                          current_season_number=season, current_episode_number=int(number),
                          current_ep_name=selected.get('name', ''), current_ep_title=selected.get('name', ''))
        return {'success': True, 'item': target}

    def search_streamingcommunity(self, query):
        try:
            active_domain = self.get_active_sc_domain()
            headers = {
                'X-Inertia': 'true',
                'X-Requested-With': 'XMLHttpRequest'
            }

            r1 = self.safe_get(f"{active_domain}/it/search", timeout=5)
            if r1.status_code != 200 or not re.search(r"data-page=[\"']", r1.text):
                archive_url = f"{active_domain}/archivio?search={urllib.parse.quote(query, safe='')}"
                archive = self.safe_get(archive_url, timeout=8)
                if archive.status_code == 200:
                    results = parse_archive_catalog(archive.text, active_domain)
                    if results is not None:
                        self._modern_catalog = True
                        for item in results:
                            self._modern_titles[str(item['id'])] = item
                        return results
            match = re.search(r'data-page=\"(.*?)\"', r1.text) or re.search(r"data-page='(.*?)'", r1.text)
            if match:
                version = json.loads(html_module.unescape(match.group(1))).get('version')
                if version:
                    headers['X-Inertia-Version'] = version

            r2 = self.safe_get(f"{active_domain}/it/search?q={urllib.parse.quote(query)}", headers=headers, timeout=6)
            if r2.status_code == 200:
                data = r2.json()
                props = data.get('props') or {}
                cdn_url = props.get('cdn_url') or f"https://cdn.{active_domain.replace('https://', '')}"
                titles = props.get('titles') or []
                results = []
                for t in titles:
                    if isinstance(t, dict):
                        slug = t.get('slug') or t.get('name', '').lower().replace(' ', '-').replace(':', '')
                        poster_url, cover_url = self.extract_sc_images(t, cdn_url)
                        results.append({
                            "id": t.get('id'), "tmdb_id": t.get('tmdb_id'),
                            "name": t.get('name'),
                            "type": t.get('type') or 'movie',
                            "slug": slug,
                            "release_date": t.get('release_date') or t.get('year') or '',
                            "poster": poster_url,
                            "cover": cover_url,
                            "plot": t.get('plot', ''),
                            "source": "StreamingCommunity",
                            "lang": "ita",
                            "flag": "🇮🇹",
                            "source_format": "html",
                            "watch_url": f"{active_domain}/it/watch/{t.get('id')}"
                        })
                return results
        except Exception as ex:
            print("SC search error:", ex)
        return []



    def get_genre_catalog(self, genre='', media_type='all', sort='popular', page=1):
        sort_key = 'views' if sort == 'popular' else (sort or 'release_date')
        return self.get_archive_catalog(media_type=media_type, genres=[genre] if genre else None, sort=sort_key, page=page)

    def get_archive_catalog(self, media_type='all', genres=None, countries=None, year=None, score=None, views=None, service=None, quality=None, age=None, sort='release_date', search=None, page=1):
        try:
            active_domain = self.get_active_sc_domain()
            if genres and str(page or 1)=='1' and sort=='updated_at' and media_type=='all' and not any((countries,year,score,views,service,quality,age,search)):
                genre_names=genres if isinstance(genres,list) else str(genres).split(',')
                cached=getattr(self,'_home_genre_cache',{}).get(canonical_genre(genre_names[0])) if len(genre_names)==1 else None
                if cached and time.time()-cached[0]<300:return cached[1]
            if self._modern_catalog:
                # Current domains expose archive filters through the web API.
                offset = (max(1, int(page or 1)) - 1) * 30
                modern_params = {}
                type_label = {'movie': 'Film', 'tv': 'Serie TV', 'series': 'Serie TV'}.get(str(media_type).lower())
                if type_label:
                    modern_params['tipo'] = type_label
                if not type_label or offset:
                    modern_params['offset'] = offset
                modern_params['limit'] = 30
                def filter_value(value):
                    return ','.join(str(v) for v in value) if isinstance(value, list) else str(value or '')
                for key, value in [('genere', genres), ('paese', countries), ('anno', year),
                                   ('valutazione', score), ('views', views), ('servizio', service),
                                   ('altro', [v for v in (quality, age) if v]), ('q', search)]:
                    if value and filter_value(value) not in ('all', 'null'):
                        modern_params[key] = filter_value(value)
                sort_labels = {'moment':'Momento', 'popular': 'Views', 'score': 'Valutazione', 'name': 'Nome',
                    'updated_at': 'Data di aggiornamento', 'created_at': 'Data di aggiunta'}
                if sort in sort_labels:
                    modern_params['sort'] = sort_labels[sort]
                elif sort == 'upcoming':
                    modern_params['sorting'] = 'soon'
                elif offset:
                    modern_params['sort'] = 'Data di aggiornamento'
                if not offset:
                    modern_params['count'] = 1
                modern = self.safe_get(active_domain + '/api/v1/web/archive?' + urllib.parse.urlencode(modern_params), timeout=8)
                if modern is not None and modern.status_code == 200:
                    try:
                        payload = json.loads(modern.text)
                    except ValueError:
                        payload = {}
                    if payload.get('ok') and isinstance(payload.get('items'), list):
                        results = normalize_archive_items(payload['items'], active_domain)
                        self._modern_catalog = True
                        self._modern_titles.update({str(item['id']): item for item in results})
                        total = payload.get('count')
                        if total is None:
                            total = getattr(self, '_archive_total_count', offset + len(results) + (1 if len(results) == 30 else 0))
                        if not type_label and not offset:
                            self._archive_total_count = total
                        return {'success': True, 'titles': results, 'totalCount': total,
                                'page': max(1, int(page or 1)),
                                'hasMore': offset + len(results) < total}
                requested_genres = genres if isinstance(genres,list) else [genres] if genres else []
                selected_genre = canonical_genre(requested_genres[0]) if len(requested_genres)==1 else None
                if selected_genre:
                    if offset:
                        return {'success':False,'titles':[], 'error':'StreamingCommunity non rende al momento disponibili le pagine successive. Riprova tra poco.', 'hasMore':True}
                    page_params={k:v for k,v in modern_params.items() if k not in ('offset','limit','count')}
                    if 'q' in page_params:page_params['search']=page_params.pop('q')
                    category_path='/' + selected_genre.lower()
                    if type_label or any((countries,year,score,views,service,quality,age,search)) or sort not in ('updated_at','release_date'):
                        category_path='/archivio?'+urllib.parse.urlencode(page_params)
                    page_response = self.safe_get(active_domain + category_path, timeout=12)
                    state = parse_archive_state(page_response.text, active_domain) if page_response.status_code==200 else None
                    if state and any(canonical_genre(g)==selected_genre for g in state['filters'].get('Genere',[])):
                        items=state['titles']
                        self._modern_catalog=True
                        self._modern_titles.update({str(i['id']):i for i in items})
                        return {'success':True,'titles':items,'totalCount':state['totalCount'],'page':1,
                                'hasMore':len(items)<state['totalCount'],'source_format':'html'}
                    return {'success':False,'titles':[], 'error':'Categoria temporaneamente non disponibile su StreamingCommunity'}
                if self._modern_catalog:
                    if offset:
                        return {'success':False,'titles':[], 'error':'Le pagine successive di StreamingCommunity sono temporaneamente indisponibili. Riprova tra poco.','hasMore':True}
                    page_params={k:v for k,v in modern_params.items() if k not in ('offset','limit','count')}
                    if 'q' in page_params:page_params['search']=page_params.pop('q')
                    source_page=self.safe_get(active_domain+'/archivio?'+urllib.parse.urlencode(page_params),timeout=12)
                    state=parse_archive_state(source_page.text,active_domain) if source_page.status_code==200 else None
                    if state:
                        self._modern_titles.update({str(i['id']):i for i in state['titles']})
                        return {'success':True,'titles':state['titles'],'totalCount':state['totalCount'],'page':1,
                                'hasMore':len(state['titles'])<state['totalCount']}
                    return {'success':False,'titles':[],'error':'Archivio StreamingCommunity temporaneamente non disponibile'}
            cdn_url = f"https://cdn.{active_domain.replace('https://', '')}"
            query_parts = []

            # Type: 'movie', 'tv'
            if media_type and str(media_type).lower() not in ('all', '', 'null', 'tutto', 'tutti'):
                query_parts.append(f"type={urllib.parse.quote(str(media_type).lower())}")

            # The primary catalog uses numeric genre IDs, rather than the old labels.
            if genres and not self._modern_catalog:
                source_genres = (self.home_catalog_cache.value or {}).get('genres', []) or self.get_archive_metadata().get('genres', [])
                by_name = {canonical_genre(g.get('name')): g['id'] for g in source_genres
                           if canonical_genre(g.get('name'))}
                values = genres if isinstance(genres, list) else str(genres).split(',')
                genres = [by_name.get(canonical_genre(value), value) for value in values]
            # Genres (support list or comma-separated string)
            if genres:
                if isinstance(genres, (str, int)):
                    genres_list = [g.strip() for g in str(genres).split(',') if str(g).strip()]
                elif isinstance(genres, list):
                    genres_list = [str(g).strip() for g in genres if str(g).strip()]
                else:
                    genres_list = []
                for g in genres_list:
                    if g:
                        query_parts.append(f"genre%5B%5D={urllib.parse.quote(str(g))}")

            # Countries (support list or comma-separated string)
            if countries:
                if isinstance(countries, (str, int)):
                    countries_list = [c.strip() for c in str(countries).split(',') if str(c).strip()]
                elif isinstance(countries, list):
                    countries_list = [str(c).strip() for c in countries if str(c).strip()]
                else:
                    countries_list = []
                for c in countries_list:
                    if c:
                        query_parts.append(f"country%5B%5D={urllib.parse.quote(str(c))}")

            # Year
            if year and str(year).strip() not in ('', 'all', 'null', 'tutti'):
                query_parts.append(f"year={urllib.parse.quote(str(year).strip())}")

            # Score
            if score and str(score).strip() not in ('', 'all', 'null', 'qualsiasi'):
                query_parts.append(f"score={urllib.parse.quote(str(score).strip())}")

            # Views
            if views and str(views).strip() not in ('', 'all', 'null', 'qualsiasi'):
                query_parts.append(f"views={urllib.parse.quote(str(views).strip())}")

            # Service
            if service and str(service).strip() not in ('', 'all', 'null', 'tutti'):
                query_parts.append(f"service={urllib.parse.quote(str(service).strip())}")

            # Quality
            if quality and str(quality).strip() not in ('', 'all', 'null', 'tutte'):
                query_parts.append(f"quality={urllib.parse.quote(str(quality).strip())}")

            # Age
            if age and str(age).strip() not in ('', 'all', 'null', 'tutte'):
                query_parts.append(f"age={urllib.parse.quote(str(age).strip())}")

            # Sort: StreamingCommunity uses 'sort' parameter
            sort_val = str(sort or 'release_date').strip()
            if getattr(self, 'primary_vixcloud', False) and sort_val in ('updated_at','created_at','moment','popular','upcoming'):
                sort_val = 'release_date'
            if sort_val and sort_val not in ('', 'default', 'null'):
                query_parts.append(f"sort={urllib.parse.quote(sort_val)}")

            # Search query within archive
            if search and str(search).strip():
                query_parts.append(f"search={urllib.parse.quote(str(search).strip())}")

            # Page
            page_num = 1
            try:
                page_num = int(page) if page else 1
            except Exception:
                page_num = 1
            if page_num > 1:
                query_parts.append(f"page={page_num}")

            qs = f"?{'&'.join(query_parts)}" if query_parts else ""
            res = self.safe_get(f"{active_domain}/it/archive{qs}", timeout=8)
            if res and res.status_code == 200:
                match = re.search(r'data-page=\"(.*?)\"', res.text) or re.search(r"data-page='(.*?)'", res.text)
                if match:
                    dp = json.loads(html_module.unescape(match.group(1)))
                    props = dp.get('props', {})
                    cdn = props.get('cdn_url') or cdn_url
                    titles = props.get('titles') or []
                    total_count = props.get('totalCount') or len(titles)

                    if props.get('genres'):
                        self._cached_archive_genres = props['genres']
                    if props.get('countries'):
                        self._cached_archive_countries = props['countries']

                    results = []
                    for t in titles:
                        if isinstance(t, dict):
                            poster_url, cover_url = self.extract_sc_images(t, cdn)
                            slug = t.get('slug') or t.get('name', '').lower().replace(' ', '-').replace(':', '')
                            str_tid = str(t.get('id', ''))
                            cached_rel = self.dates_cache.get(str_tid)
                            raw_rel = cached_rel or t.get('release_date') or t.get('year') or t.get('last_air_date') or t.get('last_air_date_it') or t.get('first_air_date') or ''
                            clean_rel = str(raw_rel).strip()
                            if clean_rel == '2024' and not cached_rel:
                                clean_rel = str(t.get('last_air_date') or t.get('last_air_date_it') or t.get('first_air_date') or '').strip()

                            # Extract plot from translations if not in top-level
                            plot = t.get('plot') or ''
                            if not plot and t.get('translations'):
                                for tr in t['translations']:
                                    if tr.get('key') == 'plot':
                                        plot = tr.get('value', '')
                                        break
                            if not plot:
                                plot = 'Nessuna trama disponibile.'

                            # Extract name from translations if needed
                            name = t.get('name') or ''
                            if not name and t.get('translations'):
                                for tr in t['translations']:
                                    if tr.get('key') == 'name':
                                        name = tr.get('value', '')
                                        break

                            results.append({
                                "id": t.get('id'),
                                "name": name,
                                "type": t.get('type') or 'movie',
                                "slug": slug,
                                "release_date": clean_rel,
                                "score": t.get('score') or '',
                                "seasons_count": t.get('seasons_count') or 0,
                                "poster": poster_url,
                                "backdrop": cover_url or poster_url,
                                "cover": cover_url or poster_url,
                                "plot": plot,
                                "source_format": "inertia", "source": "StreamingCommunity",
                            "watch_url": f"{active_domain}/it/watch/{t.get('id')}",
                                "age": t.get('age') or '',
                                "sub_ita": t.get('sub_ita') or 0
                            })
                    return {
                        "success": True,
                        "titles": results,
                        "totalCount": total_count,
                        "page": page_num,
                        "hasMore": (len(results) >= 60) and (page_num * 60 < total_count)
                    }
        except Exception as ex:
            print("Archive catalog error:", ex)

        # Fallback for modern Next.js routes (/film, /serie-tv, /archivio)
        try:
            active_domain = self.get_active_sc_domain()
            target_path = '/film' if str(media_type).lower() in ('movie', 'film') else ('/serie-tv' if str(media_type).lower() in ('tv', 'series') else '/archivio')
            r_modern = self.safe_get(f"{active_domain}{target_path}", timeout=8)
            if r_modern and r_modern.status_code == 200:
                modern_results = []
                if target_path in ('/film', '/serie-tv'):
                    cat = parse_home_catalog(r_modern.text, active_domain)
                    if cat and cat.get('sliders'):
                        for sl in cat['sliders']:
                            for t in sl.get('titles', []):
                                if not any(x['id'] == t['id'] for x in modern_results):
                                    modern_results.append(t)
                else:
                    modern_results = parse_archive_catalog(r_modern.text, active_domain) or []
                if modern_results:
                    if hasattr(self, '_modern_titles'):
                        self._modern_titles.update({str(item['id']): item for item in modern_results})
                    return {
                        "success": True,
                        "titles": modern_results,
                        "totalCount": len(modern_results),
                        "page": 1,
                        "hasMore": False
                    }
        except Exception as e_mod:
            pass

        # Fallback to in-memory cached modern titles
        if hasattr(self, '_modern_titles') and self._modern_titles:
            cached = list(self._modern_titles.values())
            if str(media_type).lower() in ('movie', 'film'):
                cached = [t for t in cached if t.get('type') == 'movie' or not t.get('type')]
            elif str(media_type).lower() in ('tv', 'series'):
                cached = [t for t in cached if t.get('type') == 'tv' or (t.get('seasons_count') or 0) > 0]
            if cached:
                return {
                    "success": True,
                    "titles": cached,
                    "totalCount": len(cached),
                    "page": 1,
                    "hasMore": False
                }

        return {"success": True, "titles": [], "totalCount": 0, "page": 1, "hasMore": False}

    def get_archive_metadata(self):
        if self._modern_catalog:
            return {'success':True,'genres':[{'id':g,'name':g} for g in GENRES], 'countries':self._cached_archive_countries}
        try:
            if hasattr(self, '_cached_archive_genres') and self._cached_archive_genres and hasattr(self, '_cached_archive_countries') and self._cached_archive_countries:
                return {
                    "success": True,
                    "genres": self._cached_archive_genres,
                    "countries": self._cached_archive_countries
                }
            active_domain = self.get_active_sc_domain()
            res = self.safe_get(f"{active_domain}/it/archive", timeout=6)
            if res and res.status_code == 200:
                match = re.search(r'data-page=\"(.*?)\"', res.text) or re.search(r"data-page='(.*?)'", res.text)
                if match:
                    dp = json.loads(html_module.unescape(match.group(1)))
                    props = dp.get('props', {})
                    if props.get('genres'):
                        self._cached_archive_genres = props['genres']
                    if props.get('countries'):
                        self._cached_archive_countries = props['countries']
                    return {
                        "success": True,
                        "genres": self._cached_archive_genres,
                        "countries": self._cached_archive_countries
                    }
        except Exception as ex:
            print("Archive metadata error:", ex)
        return {"success": True, "genres": [{"id":g,"name":g} for g in GENRES], "countries": []}

    def search_catalog(self, query):
        try:
            return self.search_catalog_multi(query)
        except Exception as ex:
            print("Search catalog error:", ex)
            return []

    def search_catalog_multi(self, query):
        def primary():
            try:
                return self.search_streamingcommunity(query) or []
            except Exception:
                return []
        with ThreadPoolExecutor(max_workers=2) as pool:
            sc = pool.submit(primary)
            gs = pool.submit(Guardaserie(self.session).search, query)
            return sc.result() + gs.result()


    def get_modern_title_details(self, title_id, slug=""):
        domain = self.get_active_sc_domain()
        key = (domain, str(title_id))
        cached = self._modern_details.get(key)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        known = self._modern_titles.get(str(title_id), {})
        slug = slug or known.get('slug', '')
        path = slug if slug.startswith(str(title_id) + '-') else f"{title_id}-{slug.removesuffix('-streaming')}-streaming"
        url = known.get('title_url') or f"{domain}/titles/{path}"
        for timeout in (8, 15):
            page = self.safe_get(url, timeout=timeout)
            details = parse_title_details(page.text, domain, title_id) if page.status_code == 200 else None
            if details:
                self._modern_details[key] = (time.monotonic(), details)
                return details
        # Previously loaded episode lists remain usable during a source outage.
        return cached[1] if cached else {"error": "Dettagli del nuovo sito non disponibili"}

    def get_title_details(self, title_id, slug=""):
        return self._catalog_requests.get(('title', str(title_id)),
            lambda: self._get_title_details_uncached(title_id, slug))

    def _get_title_details_uncached(self, title_id, slug=""):
        if str(title_id).startswith("gs-"):
            res = Guardaserie(self.session).details(title_id)
        else:
            res = self.get_modern_title_details(title_id,slug)
        if isinstance(res, dict):
            self._sanitize_media_item(res)
            for s in res.get('seasons', []):
                for ep in s.get('episodes', []):
                    self._sanitize_media_item(ep)
        return res

    def get_season_episodes(self, title_id, slug, season_number):
        return self._catalog_requests.get(('season', str(title_id), int(season_number)),
            lambda: self._get_season_episodes_uncached(title_id, slug, season_number))

    def _get_season_episodes_uncached(self, title_id, slug, season_number):
        details = self.get_title_details(title_id,slug)
        season = next((s for s in details.get('seasons',[]) if int(s['number']) == int(season_number)),{})
        if details.get('error'): return details
        return {'season_number':int(season_number),'episodes':season.get('episodes',[]),
                'seasons':[{k:s.get(k) for k in ('number','name','episodes_count')} for s in details.get('seasons',[])]}





    def refresh_sc_stream_source(self, ref):
        parsed = urllib.parse.urlsplit(ref)
        if parsed.scheme != 'https' or parsed.hostname != 'v.vidxgo.co':
            return None
        headers = {'Referer': self.get_active_sc_domain().rstrip('/') + '/',
                   'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site',
                   'Cache-Control': 'no-cache'}
        response = media_get(self.session, ref, headers=headers, timeout=8)
        return parse_player_source(response.text) if response.status_code == 200 else None

    def extract_modern_stream(self, watch_url, force=False, diagnostics=None):
        from bs4 import BeautifulSoup
        active_domain = 'https://streaming-community.biz'
        if hasattr(self, 'get_active_sc_domain'):
            try:
                candidate = self.get_active_sc_domain()
                if isinstance(candidate, str):
                    active_domain = candidate
            except Exception:
                pass
        active_parsed = urllib.parse.urlsplit(active_domain)
        w_parsed = urllib.parse.urlsplit(watch_url)
        if w_parsed.path.startswith('/titles/'):
            watch_url = urllib.parse.urlunsplit((active_parsed.scheme, active_parsed.netloc, w_parsed.path, w_parsed.query, w_parsed.fragment))

        with self._modern_stream_lock:
            cached = self._modern_streams.get(watch_url)
            if cached and not force and time.monotonic() - cached[0] < 300:
                return cached[1]

        page = media_get(self.session, watch_url, timeout=8)
        document = BeautifulSoup(page.text, 'html.parser') if page.status_code == 200 else None
        iframe = document.select_one('.tc-player-frame iframe') if document else None
        if not iframe:
            if diagnostics is not None:
                diagnostics.update(stage='watch_page', upstream_status=page.status_code, reason='iframe_missing')
            return None
        embed = urllib.parse.urljoin(watch_url, iframe.get('src', ''))
        parsed = urllib.parse.urlsplit(embed)
        if parsed.scheme != 'https' or parsed.hostname != 'v.vidxgo.co':
            if diagnostics is not None:
                diagnostics.update(stage='embed_host', reason='unexpected_host')
            return None
        canonical = document.select_one('link[rel="canonical"]')
        source_url = canonical.get('href') if canonical else getattr(page, 'url', watch_url)
        source_page = urllib.parse.urlsplit(source_url or watch_url)
        player_headers = {
            'Referer': f'{source_page.scheme}://{source_page.netloc}/',
            'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site'
        }
        stream = None
        for attempt in range(2):
            player = media_get(self.session, embed, headers=player_headers, timeout=8)
            if player.status_code == 200:
                stream = parse_player_source(player.text)
                if stream:
                    break
            if player.status_code not in (200, 403, 429, 502, 503):
                break
        if not stream:
            if diagnostics is not None:
                diagnostics.update(stage='player_page', upstream_status=player.status_code, reason='source_missing')
            return None
        extracted = {'master_m3u8': stream, 'vix_url': embed, 'headers': media_headers(embed),
                     'subtitle_tracks': parse_player_subtitles(player.text, embed)}
        self.sc_stream_tokens.register(stream, embed)
        with self._modern_stream_lock:
            if len(self._modern_streams) > 200:
                self._modern_streams.clear()
            self._modern_streams[watch_url] = (time.monotonic(), extracted)
        return extracted

    def extract_guardaserie_stream(self, watch_url, force=False):
        if not watch_url:
            return None
        with self._guardaserie_stream_lock:
            cached = self._guardaserie_streams.get(watch_url)
            if cached and not force and (time.monotonic() - cached[0] < 600):
                return cached[1]
        host = urllib.parse.urlsplit(watch_url).hostname
        players = ([{'url': watch_url}] if host == 'vixsrc.to'
                   else Guardaserie(self.session).players(watch_url))
        res = None
        for player in players:
            if urllib.parse.urlsplit(player['url']).hostname != 'vixsrc.to':
                continue
            try:
                res = self.guardoserie_streams.extract(player['url'], force=force)
                if res:
                    break
            except Exception as error:
                app.logger.warning('Guardaserie direct source unavailable: %s', type(error).__name__)
        if not res:
            for player in players:
                try:
                    res = self.guardoserie_streams.extract(player['url'], force=force)
                    if res:
                        break
                except Exception:
                    pass
        if res:
            with self._guardaserie_stream_lock:
                if len(self._guardaserie_streams) > 150:
                    self._guardaserie_streams.clear()
                self._guardaserie_streams[watch_url] = (time.monotonic(), res)
        return res

    def extract_sc_m3u8(self, watch_url):
        if urllib.parse.urlsplit(watch_url or '').hostname in ('guardoseries.click', 'vixsrc.to'):
            return self.extract_guardaserie_stream(watch_url)
        domain = urllib.parse.urlsplit(self.get_active_sc_domain())
        target = urllib.parse.urlsplit(watch_url or '')
        if target.hostname != domain.hostname or not target.path.startswith('/titles/'): return None
        result = self.extract_modern_stream(watch_url)
        if not result: return None
        return {**result,'type':'hls','title':'StreamingCommunity'}



    def extract_vixcloud_details(self, watch_url):
        try:
            extracted = self.extract_sc_m3u8(watch_url)
            if not extracted:
                return {"error": "Impossibile estrarre lo stream VixCloud/M3U8 dal link fornito."}

            master_m3u8 = extracted['master_m3u8']
            vix_url = extracted['vix_url']
            title = extracted['title']

            qualities_data = self.get_stream_qualities(watch_url)
            qualities = qualities_data.get('qualities', []) if isinstance(qualities_data, dict) else []
            audio_tracks = qualities_data.get('audio_tracks', []) if isinstance(qualities_data, dict) else []
            subtitle_tracks = qualities_data.get('subtitle_tracks', []) if isinstance(qualities_data, dict) else []

            return {
                "success": True,
                "title": title,
                "original_url": watch_url,
                "vix_url": vix_url,
                "embed_url": vix_url,
                "master_m3u8": master_m3u8,
                "qualities": qualities,
                "audio_tracks": audio_tracks,
                "subtitle_tracks": subtitle_tracks
            }
        except Exception as ex:
            return {"error": f"Errore estrazione VixCloud: {str(ex)[:100]}"}

    def get_stream_qualities(self, url):
        extracted = self.extract_sc_m3u8(url)
        if not extracted: return {'error':'Flusso StreamingCommunity non disponibile'}
        master = self.sc_stream_tokens.sign(extracted['master_m3u8'],extracted['vix_url'])
        response = media_get(self.session,master,headers=extracted['headers'],timeout=8)
        if response.status_code != 200: return {'error':'Playlist non disponibile'}
        audio,subtitles,qualities = manifest_metadata(response.text,master,lambda resource:resource)
        return {'success':True,'url':url,'master_m3u8':master,'vix_url':extracted['vix_url'],
            'qualities':qualities,'audio_tracks':audio,'subtitle_tracks':subtitles}



    def start_download(self, url, media_type="hls", format_choice="1080p", custom_title=None, custom_headers=None, parent_folder=None, poster=None):
        download_id = f"dl_{int(time.time() * 1000)}"
        safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title or f"video_{download_id}").strip()
        if not safe_title:
            safe_title = f"video_{download_id}"

        if parent_folder:
            safe_parent = re.sub(r'[\\/*?:"<>|]', "", parent_folder).strip()
            dest_folder = os.path.join(DOWNLOADS_DIR, safe_parent)
        else:
            dest_folder = os.path.join(DOWNLOADS_DIR, safe_title)
        os.makedirs(dest_folder, exist_ok=True)
        target_filepath = os.path.join(dest_folder, f"{safe_title}.mp4")

        self.downloads[download_id] = {
            "download_id": download_id,
            "format_choice": format_choice,
            "media_type": media_type,
            "url": url,
            "title": custom_title or safe_title,
            "poster": poster,
            "state": "running",
            "phase": "downloading",
            "percent": 0.0,
            "speed": "0 MB/s",
            "downloaded": "0 MB",
            "folder": dest_folder,
            "filename": f"{safe_title}.mp4",
            "filepath": target_filepath,
            "error": None,
            "cancel_requested": False,
            "pause_requested": False
        }

        t = threading.Thread(target=self._run_download, args=(download_id, url, media_type, format_choice, custom_title, custom_headers, dest_folder, safe_title, target_filepath))
        t.daemon = True
        t.start()
        return {"download_id": download_id}

    def pause_download(self, download_id):
        if download_id in self.downloads:
            d = self.downloads[download_id]
            if d["state"] == "running":
                d["pause_requested"] = True
                d["state"] = "paused"
                return {"success": True, "state": "paused"}
        return {"error": "Download non trovato o non in esecuzione."}

    def resume_download(self, download_id):
        if download_id in self.downloads:
            d = self.downloads[download_id]
            if d["state"] == "paused":
                d["pause_requested"] = False
                d["state"] = "running"
                return {"success": True, "state": "running"}
        return {"error": "Download non trovato o non in pausa."}

    def _cleanup_download_files(self, safe_title, dest_folder=None):
        try:
            # 1. Rimuovi la cartella dei frammenti e file scaricati
            if dest_folder and os.path.exists(dest_folder):
                try:
                    shutil.rmtree(dest_folder, ignore_errors=True)
                    print(f"[Cleanup] Cartella frammenti eliminata: {dest_folder}")
                except Exception as e:
                    print(f"[Cleanup] Errore rimozione cartella {dest_folder}: {e}")

            # 2. Controllo per eventuale cartella omonima in DOWNLOADS_DIR
            if safe_title and len(safe_title) >= 2:
                folder_direct = os.path.join(DOWNLOADS_DIR, safe_title)
                if os.path.isdir(folder_direct):
                    try:
                        shutil.rmtree(folder_direct, ignore_errors=True)
                        print(f"[Cleanup] Cartella omonima rimossa: {folder_direct}")
                    except Exception:
                        pass

                # 3. Controllo file residui orfani in DOWNLOADS_DIR
                for fname in os.listdir(DOWNLOADS_DIR):
                    if fname == safe_title or fname.startswith(safe_title):
                        full_p = os.path.join(DOWNLOADS_DIR, fname)
                        try:
                            if os.path.isdir(full_p):
                                shutil.rmtree(full_p, ignore_errors=True)
                            elif os.path.isfile(full_p):
                                os.remove(full_p)
                                print(f"[Cleanup] File orfano rimosso: {full_p}")
                        except Exception:
                            pass
        except Exception as e:
            print(f"[Cleanup] Errore generale: {e}")

    def cancel_download(self, download_id):
        self.canceled_downloads.add(download_id)
        d = self.downloads.get(download_id)
        safe_title = ""
        dest_folder = None
        if d:
            d["cancel_requested"] = True
            d["state"] = "canceled"
            d["phase"] = "canceled"
            d["percent"] = 0.0
            safe_title = re.sub(r'[\\/*?:"<>|]', "", d.get("title", "")).strip()
            dest_folder = d.get("folder") or os.path.join(DOWNLOADS_DIR, safe_title)
            proc = d.get("process")
            if proc is None:
                proc = self.processes.get(download_id)
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass

        # Cleanup immediato sincronizzato
        self._cleanup_download_files(safe_title, dest_folder)

        # Ripeti pulizia a breve termine per liberare lock
        def do_cleanup_stages():
            for delay in (0.3, 0.8, 1.6):
                time.sleep(delay)
                self._cleanup_download_files(safe_title, dest_folder)
            self.downloads.pop(download_id, None)
            self.processes.pop(download_id, None)
            self.canceled_downloads.discard(download_id)

        threading.Thread(target=do_cleanup_stages, daemon=True).start()
        return {"success": True, "state": "canceled"}

    def get_status(self, download_id):
        return self.downloads.get(download_id, {"state": "error", "error": "Download non trovato."})

    def _run_download(self, download_id, url, media_type, format_choice, custom_title=None, custom_headers=None, dest_folder=None, safe_title=None, target_filepath=None):
        try:
            if not safe_title:
                safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title or f"video_{download_id}").strip() or f"video_{download_id}"
            if not dest_folder:
                dest_folder = os.path.join(DOWNLOADS_DIR, safe_title)
            os.makedirs(dest_folder, exist_ok=True)
            if not target_filepath:
                target_filepath = os.path.join(dest_folder, f"{safe_title}.mp4")

            master_m3u8 = None
            vix_url = "https://vixcloud.co/"
            extracted_headers = None

            # Unwrap proxy URLs if passed from frontend
            actual_url = url
            if '/api/stream/proxy' in actual_url or '/api/stream/segment' in actual_url:
                parsed_proxy = urllib.parse.urlsplit(actual_url)
                params = urllib.parse.parse_qs(parsed_proxy.query)
                if params.get('url'):
                    actual_url = params['url'][0]

            if ".m3u8" in actual_url or "/playlist/" in actual_url:
                master_m3u8 = actual_url
                vix_url = (custom_headers or {}).get('Referer') or 'https://vixcloud.cc/'
            else:
                extracted = self.extract_sc_m3u8(actual_url)
                if extracted:
                    master_m3u8 = extracted['master_m3u8']
                    vix_url = extracted['vix_url']
                    custom_title = custom_title or extracted.get('title')
                    extracted_headers = extracted['headers']
            if not master_m3u8: raise ValueError('Flusso StreamingCommunity non disponibile')
            headers_to_use = dict(extracted_headers or media_headers(vix_url))
            if custom_headers and isinstance(custom_headers, dict):
                headers_to_use.update(custom_headers)

            # Use the same renewing transport as playback for every HLS resource.
            # Passing the provider URL straight to yt-dlp freezes its short-lived
            # signature for the whole download, which stalls after a few minutes.
            proxy_base = getattr(self, 'download_proxy_base', None)
            if proxy_base:
                master_m3u8 = proxy_base + '/api/stream/segment?' + urllib.parse.urlencode({
                    'url': master_m3u8, 'ref': vix_url
                })

            out_tmpl = os.path.join(dest_folder, f"{safe_title}.%(ext)s")

            track_progress = {}

            def is_cancel_active():
                return download_id in self.canceled_downloads or self.downloads.get(download_id, {}).get("cancel_requested")

            def progress_hook(d):
                if is_cancel_active():
                    try:
                        from yt_dlp.utils import DownloadCancelled
                        raise DownloadCancelled("DOWNLOAD_CANCELLED")
                    except ImportError:
                        raise Exception("DOWNLOAD_CANCELLED")

                while self.downloads.get(download_id, {}).get("pause_requested"):
                    time.sleep(0.3)
                    if is_cancel_active():
                        try:
                            from yt_dlp.utils import DownloadCancelled
                            raise DownloadCancelled("DOWNLOAD_CANCELLED")
                        except ImportError:
                            raise Exception("DOWNLOAD_CANCELLED")

                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes', 0)
                    speed = d.get('speed', 0) or 0
                    raw_percent = (downloaded / total * 100) if total > 0 else 0
                    
                    fn = d.get('filename', 'default')
                    track_progress[fn] = raw_percent

                    tracks = list(track_progress.values())
                    if len(tracks) == 1:
                        overall_percent = min(85.0, tracks[0] * 0.85)
                    elif len(tracks) >= 2:
                        overall_percent = 85.0 + (tracks[1] * 0.13)
                    else:
                        overall_percent = raw_percent

                    if download_id in self.downloads and not is_cancel_active():
                        self.downloads[download_id].update({
                            "percent": round(overall_percent, 1),
                            "phase": "downloading" if overall_percent < 88 else "merging",
                            "speed": f"{speed / (1024*1024):.1f} MB/s" if speed else "0 MB/s",
                            "downloaded": f"{downloaded / (1024*1024):.1f} MB",
                            "folder": dest_folder
                        })

            ffmpeg_exe = get_ffmpeg_executable()
            ffmpeg_dir = os.path.dirname(ffmpeg_exe) if ffmpeg_exe else None

            ydl_opts = {
                'outtmpl': out_tmpl,
                'paths': {
                    'home': dest_folder,
                    'temp': dest_folder,
                },
                'progress_hooks': [progress_hook],
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'http_headers': headers_to_use,
                'fragment_retries': 10,
                'skip_unavailable_fragments': False,
                'buffersize': 2097152,
                'http_chunk_size': 10485760,
                'socket_timeout': 15
            }

            ydl_opts['concurrent_fragment_downloads'] = 8
            if 'Referer' in headers_to_use:
                ydl_opts['referer'] = headers_to_use['Referer']
            if 'User-Agent' in headers_to_use:
                ydl_opts['user_agent'] = headers_to_use['User-Agent']
            if ffmpeg_dir:
                ydl_opts['ffmpeg_location'] = ffmpeg_dir

            h = format_choice.removesuffix('p') if isinstance(format_choice, str) else '1080'
            if h != 'best' and not h.isdigit():
                raise ValueError('Qualità di download non valida')
            if ffmpeg_dir:
                ydl_opts.update({
                    'format': f'bv*[height<=?{h}]+ba/b[height<=?{h}]/best[height<=?{h}]',
                    'merge_output_format': 'mp4',
                    'postprocessor_args': {
                        'ffmpeg': ['-c:v', 'copy', '-c:a', 'aac']
                    }
                })
            else:
                ydl_opts.update({
                    'format': f'b[height<=?{h}]/best[height<=?{h}]/best'
                })

            if h == 'best':
                ydl_opts['format'] = 'bv*+ba/best' if ffmpeg_dir else 'best'

            try:
                import yt_dlp
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(master_m3u8, download=True)
                    filename = ydl.prepare_filename(info)
                    if not os.path.exists(filename):
                        base, _ = os.path.splitext(filename)
                        if os.path.exists(base + '.mp4'):
                            filename = base + '.mp4'
                        elif os.path.exists(base + '.mkv'):
                            filename = base + '.mkv'

                    # Pulizia di frammenti residui nella cartella
                    try:
                        for itm in os.listdir(dest_folder):
                            if itm.endswith('.part') or '.part-Frag' in itm or itm.endswith('.ytdl') or itm.endswith('.temp'):
                                try:
                                    os.remove(os.path.join(dest_folder, itm))
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    
                    if download_id in self.downloads and not is_cancel_active():
                        self.downloads[download_id].update({
                            "state": "completed",
                            "phase": "completed",
                            "percent": 100.0,
                            "filename": os.path.basename(filename),
                            "filepath": filename,
                            "folder": dest_folder
                        })
            except Exception as ex:
                if is_cancel_active() or "DOWNLOAD_CANCELLED" in str(ex) or "DownloadCancelled" in str(type(ex)):
                    print(f"[Download] Annullamento confermato per {download_id}: eliminazione cartella frammenti {dest_folder}")
                    self._cleanup_download_files(safe_title, dest_folder)
                    if download_id in self.downloads:
                        self.downloads[download_id].update({
                            "state": "canceled",
                            "phase": "canceled",
                            "percent": 0.0,
                            "speed": "0 MB/s",
                            "downloaded": "0 MB"
                        })
                    return
                else:
                    # Direct FFmpeg fallback
                    ref_hdr = headers_to_use.get('Referer', 'https://vixcloud.co/')
                    ua_hdr = headers_to_use.get('User-Agent')

                    ff_cmd = [
                        ffmpeg_exe or 'ffmpeg', '-y',
                        '-headers', f'User-Agent: {ua_hdr}\r\nReferer: {ref_hdr}\r\n',
                        '-i', master_m3u8,
                        '-c', 'copy',
                        '-bsf:a', 'aac_adtstoasc',
                        target_filepath
                    ]

                    proc = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if download_id in self.downloads:
                        self.processes[download_id] = proc

                    t0 = time.time()
                    while proc.poll() is None:
                        if is_cancel_active():
                            try:
                                proc.kill()
                            except Exception:
                                pass
                            self._cleanup_download_files(safe_title, dest_folder)
                            return

                        while self.downloads.get(download_id, {}).get("pause_requested"):
                            time.sleep(0.3)
                            if is_cancel_active():
                                try:
                                    proc.kill()
                                except Exception:
                                    pass
                                self._cleanup_download_files(safe_title, dest_folder)
                                return

                        time.sleep(0.5)
                        now = time.time()
                        duration = now - t0
                        if os.path.exists(target_filepath):
                            current_size = os.path.getsize(target_filepath)
                            downloaded_mb = current_size / (1024 * 1024)
                            speed_mb = downloaded_mb / duration if duration > 0 else 0
                            pct = min(98.0, (downloaded_mb / (downloaded_mb + 150)) * 100) if downloaded_mb > 0 else 1.0
                            
                            if download_id in self.downloads and not is_cancel_active():
                                self.downloads[download_id].update({
                                    "percent": round(pct, 1),
                                    "phase": "downloading",
                                    "speed": f"{speed_mb:.1f} MB/s",
                                    "downloaded": f"{downloaded_mb:.1f} MB",
                                    "folder": dest_folder
                                })

                    proc.wait()
                    self.processes.pop(download_id, None)

                    if is_cancel_active():
                        self._cleanup_download_files(safe_title, dest_folder)
                        return

                    if os.path.exists(target_filepath) and os.path.getsize(target_filepath) > 10000:
                        if download_id in self.downloads and not is_cancel_active():
                            self.downloads[download_id].update({
                                "state": "completed",
                                "phase": "completed",
                                "percent": 100.0,
                                "filename": os.path.basename(target_filepath),
                                "filepath": target_filepath,
                                "folder": dest_folder
                            })
                    else:
                        raise Exception("Download fallito: file di output mancante o troppo piccolo")

        except Exception as ex:
            self.processes.pop(download_id, None)
            if download_id in self.downloads and not self.downloads[download_id].get("cancel_requested") and download_id not in self.canceled_downloads:
                self.downloads[download_id].update({
                    "state": "error",
                    "phase": "error",
                    "error": str(ex)
                })
    def get_status(self, download_id):
        d = self.downloads.get(download_id, {"state": "error", "error": "Download non trovato."})
        return {k: v for k, v in d.items() if k != "process"}

engine = Engine()

# -------------------------------------------------------------
# FLASK ROUTES
# -------------------------------------------------------------
@app.route('/healthz')
def healthz():
    return jsonify(status='ok')

@app.route('/')
def index():
    resp = make_response(render_template('index.html', watchparty_local=os.environ.get('WATCHPARTY_LOCAL_ONLY') == '1', tmdb_api_key=TMDB_API_KEY))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/api/sc/domain', methods=['GET'])
def get_sc_domain():
    refresh = request.args.get('refresh') == 'idle'
    downloading = any(d.get('state') == 'running' for d in list(engine.downloads.values()))
    domain = engine.get_active_sc_domain(refresh=refresh and not downloading)
    return jsonify({"domain": domain, "deferred": bool(refresh and downloading)})

@app.route('/api/sc/home', methods=['GET'])
def home_sc():
    return jsonify(engine.get_home_catalog())

@app.route('/api/sc/home/genre', methods=['GET'])
def home_genre_sc():
    genre=canonical_genre(request.args.get('genre',''))
    if not genre:return jsonify(success=False,error='Genere non valido'),400
    cached=engine._home_genre_cache.get(genre)
    if cached and time.time()-cached[0]<300:return jsonify(cached[1])
    result=engine.get_archive_catalog(genres=[genre],sort='updated_at',page=1)
    if result.get('success') and result.get('titles'):
        with engine._home_genre_lock:
            engine._home_genre_cache[genre]=(time.time(),result)
            try:
                with open(engine._home_genre_file+'.tmp','w') as destination:json.dump(engine._home_genre_cache,destination)
                os.replace(engine._home_genre_file+'.tmp',engine._home_genre_file)
            except OSError:pass
    elif cached:result=cached[1]
    return jsonify(result)

@app.route('/api/sc/random', methods=['GET', 'POST'])
def random_sc():
    return jsonify(engine.get_random_movie())

TRAILER_CACHE = {
    "marfil": "aczjESBhGVg",
    "marfil - gli opposti": "aczjESBhGVg",
    "the last sunrise": "BZeqbOjLNNQ",
    "the gentlemen": "6bRj-EKRC1g",
    "reacher": "l7ipiGrlzbs",
    "dark matter": "zLjnnL3Egm8",
    "shards": "5v6FfPmsF2o",
    "the shards": "5v6FfPmsF2o",
    "crew girl": "kM9f41b2kU4",
    "10+te": "WlDq6o5mZAE",
    "beauty in black": "c1fA3o-P2fA",
    "casa a prima vista": "jJ5P2e7Z2zI",
    "4 hotel": "YVzB3c9w4Z8",
}

@app.route('/api/trailer', methods=['GET'])
def get_trailer():
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({"success": False, "error": "Titolo mancante"}), 400
    
    clean_key = title.lower()
    for k, vid in TRAILER_CACHE.items():
        if k in clean_key or clean_key in k:
            return jsonify({"success": True, "video_id": vid, "title": title})
    
    # Try searching with yt-dlp
    try:
        import subprocess, json
        search_query = f"{title} trailer ufficiale italiano"
        cmd = ['yt-dlp', f'ytsearch1:{search_query}', '--dump-json', '--no-playlist']
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if proc.returncode == 0 and proc.stdout:
            data = json.loads(proc.stdout)
            vid = data.get('id')
            if vid:
                TRAILER_CACHE[clean_key] = vid
                return jsonify({"success": True, "video_id": vid, "title": title})
    except Exception as e:
        print("Trailer lookup error:", e)
    
    return jsonify({"success": False, "error": "Trailer non trovato"}), 404

import base64 as _b64
DEFAULT_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not DEFAULT_GEMINI_API_KEY:
    try:
        with open(os.path.join(BASE_DIR, '.gemini_api_key')) as local_key:
            DEFAULT_GEMINI_API_KEY = local_key.read().strip()
    except OSError:
        pass

@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    try:
        data = request.get_json() or {}
        user_message = (data.get('message') or data.get('prompt') or '').strip()
        api_key = data.get('apiKey', '').strip() or os.environ.get('GEMINI_API_KEY', '').strip() or DEFAULT_GEMINI_API_KEY
        history = data.get('history', [])

        if not api_key:
            return jsonify({
                "success": False,
                "error": "API Key di Gemini non inserita. Configura la tua chiave."
            }), 400

        if not user_message:
            return jsonify({"success": False, "error": "Messaggio vuoto."}), 400

        system_instruction = (
            "Sei Gemini CineBot, l'assistente cinema e serie TV integrato nell'app StreamingCommunity.\n"
            "REGOLE TASSATIVE:\n"
            "1. Sii CONCISO e DIRETTO: nessun saluto cerimonioso o conclusione prolissa.\n"
            "2. Consiglia sempre 4 o 5 titoli (film o serie TV) altamente pertinenti alla richiesta dell'utente.\n"
            "3. Inserisci SEMPRE il TITOLO ESATTO di ciascun film/serie tra doppie parentesi quadre, ad esempio [[Interstellar]], [[Seven]], [[Shutter Island]].\n"
            "4. Per ogni titolo indica: Anno, Genere e una sola riga sintetica con il motivo della scelta.\n"
            "5. DIVIETO ASSOLUTO DI EMOJI O EMOTICON: Non usare MAI alcuna emoji, emoticon o simbolo grafico (niente faccine, popcorn, stelle, razzi, ciak, ecc.). Usa solo testo pulito e trattini o elenchi puntati semplici.\n"
            "6. Rispondi sempre in lingua italiana."
        )

        contents = []
        for h in history[-8:]:
            role = "user" if h.get('role') == 'user' else "model"
            txt = h.get('content') or h.get('text') or ''
            if txt:
                contents.append({"role": role, "parts": [{"text": txt}]})

        contents.append({"role": "user", "parts": [{"text": user_message}]})

        # Utilizzo prioritario di modelli ultra-veloci e performanti
        models_to_try = [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
            "gemini-flash-lite-latest"
        ]
        ai_reply = None
        last_err = None

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            payload = {
                "systemInstruction": {
                    "parts": [{"text": system_instruction}]
                },
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 750
                }
            }
            try:
                res = cffi_requests.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=14
                )
                if res.status_code == 200:
                    res_json = res.json()
                    candidates = res_json.get('candidates', [])
                    if candidates:
                        parts = candidates[0].get('content', {}).get('parts', [])
                        if parts:
                            ai_reply = parts[0].get('text', '')
                            break
                elif res.status_code in (400, 403, 404, 503):
                    err_json = res.json() if 'application/json' in res.headers.get('Content-Type', '') else {}
                    last_err = err_json.get('error', {}).get('message', res.text)
                else:
                    last_err = f"HTTP {res.status_code}: {res.text[:200]}"
            except Exception as e:
                last_err = str(e)

        if not ai_reply:
            return jsonify({"success": False, "error": f"Errore risposta Gemini: {last_err or 'Nessuna risposta disponibile.'}"}), 500

        # Rimuove categoricamente qualsiasi carattere emoji residuo
        ai_reply = re.sub(r'[\U00010000-\U0010ffff]', '', ai_reply)

        # Extract titles in [[...]]
        raw_titles = re.findall(r'\[\[(.*?)\]\]', ai_reply)
        extracted_titles = []
        for t in raw_titles:
            clean_name = t.strip().replace('"', '').replace("'", "")
            if clean_name and clean_name not in extracted_titles:
                extracted_titles.append(clean_name)

        # Cross-reference with StreamingCommunity catalog
        matched_catalog = []
        seen_ids = set()
        for title in extracted_titles[:6]:
            try:
                sc_res = engine.search_catalog(title)
                if isinstance(sc_res, dict) and sc_res.get('results'):
                    for item in sc_res['results'][:1]:
                        iid = item.get('id')
                        if iid and iid not in seen_ids:
                            seen_ids.add(iid)
                            matched_catalog.append(item)
            except Exception as ex:
                print(f"Error matching title '{title}':", ex)

        return jsonify({
            "success": True,
            "reply": ai_reply,
            "extracted_titles": extracted_titles,
            "catalog_matches": matched_catalog
        })
    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500

@app.route('/api/ai/test-key', methods=['POST'])
def ai_test_key():
    try:
        data = request.get_json() or {}
        api_key = data.get('apiKey', '').strip() or DEFAULT_GEMINI_API_KEY
        if not api_key:
            return jsonify({"success": False, "error": "Inserisci un'API Key valida."}), 400

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "Rispondi solo con: OK"}]}]
        }
        res = cffi_requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=8)
        if res.status_code == 200:
            return jsonify({"success": True, "message": "API Key di Gemini valida e attiva!"})
    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500

# -------------------------------------------------------------
# ACTOR INFO ENDPOINT (WIKIPEDIA BIO & AWARDS + FILMOGRAPHY & SC ARCHIVE)
# -------------------------------------------------------------
actor_info_cache = {}

def clean_actor_award_entries(raw_list):
    cleaned = []
    seen = set()
    current_cat = ''
    for item in raw_list:
        lines = [l.strip() for l in str(item).split('\n') if l.strip()]
        for l in lines:
            if any(k in l.lower() for k in ['oscar', 'golden globe', 'bafta', 'sag', 'david di donatello', 'nastro d\'argento', 'venezia', 'cannes', 'emmy', 'critics']):
                if not re.search(r'\d{4}', l):
                    current_cat = l
                    continue
            clean_l = re.sub(r'\[\d+\]', '', l).strip()
            if not clean_l or len(clean_l) < 4:
                continue
            y_m = re.search(r'(19\d\d|20\d\d)', clean_l)
            year = y_m.group(1) if y_m else ''
            is_win = 'candidatura' not in clean_l.lower() and 'nominat' not in clean_l.lower()
            key = clean_l.lower()
            if key not in seen:
                seen.add(key)
                cat = current_cat
                if not cat:
                    for c_cand in ['Premio Oscar', 'Golden Globe', 'Premio BAFTA', 'David di Donatello', 'Nastro d\'argento', 'Screen Actors Guild Award', 'Festival di Cannes', 'Mostra del Cinema di Venezia', 'Premio Emmy']:
                        if c_cand.lower() in clean_l.lower():
                            cat = c_cand
                            break
                cleaned.append({
                    'category': cat or 'Riconoscimento',
                    'text': clean_l,
                    'year': year,
                    'is_win': is_win
                })
    return cleaned

@app.route('/api/sc/actor_info', methods=['GET'])
def get_actor_info():
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({"success": False, "error": "Nome attore richiesto."}), 400

    cache_key = name.lower()
    if cache_key in actor_info_cache:
        return jsonify({"success": True, "actor": actor_info_cache[cache_key]})

    from bs4 import BeautifulSoup
    import concurrent.futures

    session = requests.Session()
    session.headers.update({'User-Agent': 'StreamingCommunityCastBot/1.0 (dev@streaming.local)'})

    page_title = name
    bio = ""
    desc = ""
    wiki_photo = ""
    try:
        r_w = session.get('https://it.wikipedia.org/w/api.php', params={
            'action': 'query', 'list': 'search', 'srsearch': name, 'format': 'json'
        }, timeout=6).json()
        items = r_w.get('query', {}).get('search', [])
        if items:
            page_title = items[0]['title']
        
        r_sum = session.get(f'https://it.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(page_title)}', timeout=6).json()
        bio = r_sum.get('extract', '')
        desc = r_sum.get('description', '')
        wiki_photo = r_sum.get('thumbnail', {}).get('source', '')
    except Exception as ex:
        print(f"[Actor Info] Wikipedia summary error for {name}: {ex}")

    raw_awards = []
    wiki_films = []
    try:
        r_sec = session.get('https://it.wikipedia.org/w/api.php', params={
            'action': 'parse', 'page': page_title, 'prop': 'sections', 'format': 'json'
        }, timeout=6).json()
        secs = r_sec.get('parse', {}).get('sections', [])

        ric_idx = None
        film_idx = None
        for s in secs:
            l = s['line'].lower()
            if any(k in l for k in ['riconoscimenti', 'premi']) and ric_idx is None:
                ric_idx = s['index']
            elif 'filmografia' in l and film_idx is None:
                film_idx = s['index']

        if ric_idx:
            rr = session.get('https://it.wikipedia.org/w/api.php', params={
                'action': 'parse', 'page': page_title, 'section': ric_idx, 'prop': 'text', 'format': 'json'
            }, timeout=6).json()
            soup_r = BeautifulSoup(rr.get('parse', {}).get('text', {}).get('*', ''), 'html.parser')
            subpage = None
            for a in soup_r.find_all('a'):
                href = a.get('href', '')
                if 'Premi_e_riconoscimenti' in href or 'riconoscimenti' in href.lower():
                    subpage = a.get_text().strip()
                    break

            def parse_awards_soup(sp):
                out = []
                for li in sp.find_all('li'):
                    t = li.get_text().strip()
                    t = re.sub(r'\[\d+\]', '', t).strip()
                    if t and not t.startswith('^') and len(t) < 190:
                        if any(w in t.lower() for w in ['oscar', 'globe', 'bafta', 'sag', 'david', 'nastro', 'venezia', 'cannes', 'emmy', 'miglior', 'candidatura', 'vinto', 'coppa volpi']):
                            out.append(t)
                return out

            raw_awards = parse_awards_soup(soup_r)
            if (not raw_awards or len(raw_awards) < 2) and subpage:
                try:
                    r_sub = session.get('https://it.wikipedia.org/w/api.php', params={
                        'action': 'parse', 'page': subpage, 'prop': 'text', 'format': 'json'
                    }, timeout=6).json()
                    sp_sub = BeautifulSoup(r_sub.get('parse', {}).get('text', {}).get('*', ''), 'html.parser')
                    raw_awards = parse_awards_soup(sp_sub)
                except Exception:
                    pass

        if film_idx:
            rf = session.get('https://it.wikipedia.org/w/api.php', params={
                'action': 'parse', 'page': page_title, 'section': film_idx, 'prop': 'text', 'format': 'json'
            }, timeout=6).json()
            soup_f = BeautifulSoup(rf.get('parse', {}).get('text', {}).get('*', ''), 'html.parser')
            for li in soup_f.find_all('li'):
                raw_text = re.sub(r'\[\d+\]', '', li.get_text().strip())
                if not raw_text or len(raw_text) < 4:
                    continue
                y_m = re.search(r'\((\d{4})\)', raw_text)
                year = y_m.group(1) if y_m else ''
                it = li.find('i') or li.find('a')
                t = it.get_text().strip() if it and it.get_text().strip() else re.split(r',| – | - |\(', raw_text)[0].strip()
                t_clean = re.sub(r'\(.*?\)', '', t).strip()
                if t_clean and len(t_clean) > 1:
                    wiki_films.append({'title': t_clean, 'year': year, 'character': '', 'poster': '', 'media_type': 'movie', 'vote': 0})
    except Exception as ex:
        print(f"[Actor Info] Wikipedia awards/filmography error for {name}: {ex}")

    cleaned_awards = clean_actor_award_entries(raw_awards)

    tmdb_films = []
    tmdb_photo = ''
    try:
        r_tmdb = session.get(f'https://api.themoviedb.org/3/search/person?api_key={TMDB_API_KEY}&query={urllib.parse.quote(name)}&language=it-IT', timeout=6).json()
        p_res = r_tmdb.get('results', [])
        if p_res:
            p = p_res[0]
            if p.get('profile_path'):
                tmdb_photo = f'https://image.tmdb.org/t/p/h632{p["profile_path"]}'
            p_id = p['id']
            r_c = session.get(f'https://api.themoviedb.org/3/person/{p_id}/combined_credits?api_key={TMDB_API_KEY}&language=it-IT', timeout=6).json()
            cast_list = r_c.get('cast', [])
            cast_list.sort(key=lambda x: (x.get('vote_count', 0), x.get('popularity', 0)), reverse=True)
            for c in cast_list[:30]:
                t = c.get('title') or c.get('name')
                d = c.get('release_date') or c.get('first_air_date') or ''
                y = d[:4] if d else ''
                poster = f'https://image.tmdb.org/t/p/w342{c["poster_path"]}' if c.get('poster_path') else ''
                tmdb_films.append({
                    'title': t,
                    'year': y,
                    'character': c.get('character', ''),
                    'poster': poster,
                    'media_type': c.get('media_type', 'movie'),
                    'vote': round(float(c.get('vote_average') or 0), 1)
                })
    except Exception as ex:
        print(f"[Actor Info] TMDB error for {name}: {ex}")

    final_films = tmdb_films if tmdb_films else wiki_films[:25]

    def clean_t(txt):
        return re.sub(r'[^a-zA-Z0-9]', '', str(txt).lower())

    def check_sc(film):
        title = film['title']
        try:
            res = engine.search_streamingcommunity(title) or []
            target = clean_t(title)
            for it in res:
                it_name = clean_t(it.get('name', ''))
                if it_name == target or target in it_name or it_name in target:
                    return {
                        'in_archive': True,
                        'sc_item': {
                            'id': it.get('id'),
                            'name': it.get('name'),
                            'type': it.get('type') or film.get('media_type', 'movie'),
                            'slug': it.get('slug', ''),
                            'poster': it.get('poster', film.get('poster', '')),
                            'score': it.get('score', ''),
                            'release_date': it.get('release_date', film.get('year', ''))
                        }
                    }
        except Exception:
            pass
        return {'in_archive': False, 'sc_item': None}

    # Check catalog presence for top 6 titles without hanging or blocking server
    ex = ThreadPoolExecutor(max_workers=5)
    try:
        futures = {ex.submit(check_sc, f): f for f in final_films[:6]}
        done, not_done = concurrent.futures.wait(futures.keys(), timeout=2.2)
        for fut in done:
            f = futures[fut]
            try:
                match_res = fut.result()
                f['in_archive'] = match_res.get('in_archive', False)
                f['sc_item'] = match_res.get('sc_item')
            except Exception:
                f['in_archive'] = False
                f['sc_item'] = None
        for fut in not_done:
            try:
                fut.cancel()
            except Exception:
                pass
            f = futures[fut]
            f['in_archive'] = False
            f['sc_item'] = None
    except Exception as ex_pool:
        print(f"[Actor Info] Thread pool error: {ex_pool}")
    finally:
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    for f in final_films[6:]:
        f['in_archive'] = False
        f['sc_item'] = None

    clean_actor_name = re.sub(r'\s*\([^)]*\)$', '', page_title or name).strip()
    result_data = {
        'name': clean_actor_name or name,
        'bio': bio or "Nessuna biografia disponibile su Wikipedia.",
        'description': desc or "",
        'photo': tmdb_photo or wiki_photo or "",
        'awards': cleaned_awards[:12],
        'filmography': final_films[:24]
    }

    actor_info_cache[cache_key] = result_data
    return jsonify({"success": True, "actor": result_data})

@app.route('/api/sc/search', methods=['GET', 'POST'])
def search_sc():
    data = request.get_json(silent=True) or {}
    query = request.args.get('q') or request.args.get('query') or data.get('query', '')
    if not query or not query.strip():
        return jsonify({"success": True, "titles": [], "results": []})
    res = engine.search_catalog_multi(query.strip())
    titles = []
    if isinstance(res, dict):
        titles = res.get('titles') or res.get('results') or []
    elif isinstance(res, list):
        titles = res
    for it in titles:
        engine._sanitize_media_item(it)
    return jsonify({"success": True, "titles": titles, "results": titles,
                    "source_warnings": [Guardaserie.search_error(query.strip())] if Guardaserie.search_error(query.strip()) else []})


@app.route('/api/sc/browse', methods=['GET', 'POST'])
@app.route('/api/sc/genre', methods=['GET', 'POST'])
def browse_sc():
    data = request.get_json(silent=True) or {}
    genre = request.args.get('genre') or data.get('genre', '')
    m_type = request.args.get('type') or data.get('type', 'all')
    sort = request.args.get('sort') or request.args.get('sortBy') or data.get('sort') or 'release_date'
    page = request.args.get('page') or data.get('page', 1)
    res = engine.get_archive_catalog(media_type=m_type, genres=[genre] if genre else None, sort=sort, page=page)
    titles = res.get('titles', [])
    for it in titles:
        engine._sanitize_media_item(it)
    return jsonify({"success": True, "titles": titles, "totalCount": res.get('totalCount', len(titles)), "page": res.get('page', 1), "hasMore": res.get('hasMore', False)})

@app.route('/api/sc/archive', methods=['GET', 'POST'])
def archive_sc():
    data = request.get_json(silent=True) or {}
    m_type = request.args.get('type') or data.get('type', 'all')

    # Genres (support multiple parameters or comma string)
    genres = request.args.getlist('genre[]') or request.args.getlist('genre') or data.get('genre')
    if not genres and (request.args.get('genre') or data.get('genre')):
        genres = request.args.get('genre') or data.get('genre')

    # Countries (support multiple parameters or comma string)
    countries = request.args.getlist('country[]') or request.args.getlist('country') or data.get('country')
    if not countries and (request.args.get('country') or data.get('country')):
        countries = request.args.get('country') or data.get('country')

    year = request.args.get('year') or data.get('year')
    score = request.args.get('score') or data.get('score')
    views = request.args.get('views') or data.get('views')
    service = request.args.get('service') or data.get('service')
    quality = request.args.get('quality') or data.get('quality')
    age = request.args.get('age') or data.get('age')
    sort = request.args.get('sort') or request.args.get('sortBy') or data.get('sort', 'release_date')
    search = request.args.get('search') or request.args.get('q') or data.get('search') or data.get('q')
    page = request.args.get('page') or data.get('page', 1)

    res = engine.get_archive_catalog(
        media_type=m_type,
        genres=genres,
        countries=countries,
        year=year,
        score=score,
        views=views,
        service=service,
        quality=quality,
        age=age,
        sort=sort,
        search=search,
        page=page
    )
    return jsonify(res)

@app.route('/api/sc/archive/meta', methods=['GET'])
def archive_meta_sc():
    res = engine.get_archive_metadata()
    return jsonify(res)

@app.route('/api/sc/resolve', methods=['POST'])
def resolve_primary_sc():
    data = request.get_json(silent=True) or {}
    return jsonify(engine.resolve_primary_item(data))

@app.route('/api/sc/title/<title_id>', methods=['GET'])
@app.route('/api/sc/details/<title_id>', methods=['GET'])
@app.route('/api/sc/details', methods=['GET', 'POST'])
def details_sc(title_id=None):
    data = request.get_json(silent=True) or {}
    tid = title_id or request.args.get('id') or data.get('id')
    slug = request.args.get('slug') or data.get('slug', '')
    res = engine.get_title_details(tid, slug)
    return jsonify({"success": True, "title": res, "media": res} if isinstance(res, dict) else res)

@app.route('/api/cast', methods=['GET'])
@app.route('/api/sc/cast/<title_id>', methods=['GET'])
def get_cast_route(title_id=None):
    tid = title_id or request.args.get('id') or request.args.get('title_id')
    tmdb_id = request.args.get('tmdb_id')
    title_name = request.args.get('title') or ''
    m_type = request.args.get('type', 'movie')
    
    cast_list = []
    if not tmdb_id and tid:
        t_data = engine.get_title_details(tid)
        if isinstance(t_data, dict):
            if t_data.get('cast'):
                return jsonify({"success": True, "cast": t_data.get('cast')})
            tmdb_id = t_data.get('tmdb_id')
            if not title_name: title_name = t_data.get('name', '')
            if t_data.get('type'): m_type = t_data.get('type')
            
    if not tmdb_id and title_name:
        try:
            import urllib.parse
            clean_q = title_name.split('(')[0].strip()
            s_u = f"https://api.themoviedb.org/3/search/{m_type}?api_key={TMDB_API_KEY}&language=it-IT&query={urllib.parse.quote(clean_q)}"
            r_s = engine.safe_get(s_u, timeout=3)
            if r_s and r_s.status_code == 200:
                s_json = r_s.json()
                results = s_json.get('results') or []
                if results:
                    tmdb_id = results[0].get('id')
        except Exception:
            pass

    if tmdb_id:
        try:
            c_u = f"https://api.themoviedb.org/3/{m_type}/{tmdb_id}/credits?api_key={TMDB_API_KEY}&language=it-IT"
            r_c = engine.safe_get(c_u, timeout=3)
            if r_c and r_c.status_code == 200:
                c_json = r_c.json()
                for actor in (c_json.get('cast') or []):
                    p_path = actor.get('profile_path')
                    cast_list.append({
                        "name": actor.get('name', ''),
                        "character": actor.get('character', '') or 'Ruolo sconosciuto',
                        "image": f"https://image.tmdb.org/t/p/w185{p_path}" if p_path else ""
                    })
        except Exception:
            pass
            
    return jsonify({"success": True, "cast": cast_list})

@app.route('/api/sc/preview', methods=['POST'])
def preview_sc():
    data = request.get_json(silent=True) or {}
    return jsonify(engine.get_title_preview(data.get('id'), data.get('slug', '')))

@app.route('/api/sc/season/<title_id>/<season_num>', methods=['GET'])
@app.route('/api/sc/season', methods=['GET', 'POST'])
def season_sc(title_id=None, season_num=None):
    data = request.get_json(silent=True) or {}
    tid = title_id or request.args.get('id') or data.get('id')
    slug = request.args.get('slug') or data.get('slug', '')
    s_num = season_num or request.args.get('season') or data.get('season', 1)
    res = engine.get_season_episodes(tid, slug, int(s_num))
    eps = []
    if isinstance(res, dict):
        eps = res.get('episodes') or []
    return jsonify({"success": not bool(isinstance(res, dict) and res.get('error')), "episodes": eps, "season_number": s_num,
                    "seasons": res.get('seasons', []) if isinstance(res, dict) else []})

@app.route('/api/sc/episode/outro', methods=['GET', 'POST'])
def episode_outro_sc():
    data = request.get_json(silent=True) or {}
    title_id = request.args.get('title_id') or data.get('title_id') or request.args.get('id') or data.get('id')
    season_num = request.args.get('season') or data.get('season', 1)
    ep_num = request.args.get('episode') or data.get('episode', 1)
    tmdb_id = request.args.get('tmdb_id') or data.get('tmdb_id')
    player_duration = request.args.get('duration') or data.get('duration')

    try:
        season_num = int(season_num)
    except Exception:
        season_num = 1

    try:
        ep_num = int(ep_num)
    except Exception:
        ep_num = 1

    dur_seconds = None
    if player_duration:
        try:
            dur_seconds = float(player_duration)
        except Exception:
            pass

    # If tmdb_id missing, retrieve from SC title details
    if not tmdb_id and title_id:
        try:
            t_data = engine.get_title_details(str(title_id))
            if isinstance(t_data, dict):
                tmdb_id = t_data.get('tmdb_id')
                if not dur_seconds and t_data.get('runtime'):
                    dur_seconds = float(t_data.get('runtime')) * 60.0
        except Exception:
            pass

    # Query online metadata from TMDB if tmdb_id exists
    tmdb_runtime = None
    if tmdb_id:
        try:
            tmdb_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}/episode/{ep_num}?api_key={TMDB_API_KEY}&language=it-IT"
            r_ep = engine.safe_get(tmdb_url, timeout=3)
            if r_ep and r_ep.status_code == 200:
                ep_json = r_ep.json()
                if ep_json.get('runtime'):
                    tmdb_runtime = float(ep_json.get('runtime')) * 60.0
        except Exception:
            pass

    final_duration = dur_seconds or tmdb_runtime or 2400.0

    if final_duration <= 1600:
        credits_offset = 35.0
    elif final_duration <= 3200:
        credits_offset = 42.0
    else:
        credits_offset = 50.0

    if tmdb_runtime and tmdb_runtime > 0:
        outro_start = tmdb_runtime
    else:
        outro_start = max(10.0, final_duration - credits_offset)

    return jsonify({
        "success": True,
        "title_id": title_id,
        "season": season_num,
        "episode": ep_num,
        "duration": final_duration,
        "credits_offset": credits_offset,
        "outro_start": round(outro_start, 2),
        "source": "tmdb" if tmdb_runtime else ("player" if dur_seconds else "calculated")
    })


@app.route('/api/sc/qualities', methods=['POST'])
def qualities_sc():
    url = (request.get_json(silent=True) or {}).get('url', '')
    return jsonify(engine.get_stream_qualities(url))


@app.route('/api/vixcloud/extract', methods=['GET','POST','OPTIONS'])
def extract_vixcloud():
    if request.method == 'OPTIONS': return jsonify(success=True)
    data = request.get_json(silent=True) or {}
    url = data.get('url') or request.args.get('url','')
    if not url: return jsonify(success=False,error='Titolo StreamingCommunity non valido'),400
    if urllib.parse.urlsplit(url).hostname in ('guardoseries.click', 'vixsrc.to'):
        try:
            result = engine.extract_guardaserie_stream(url, force=data.get('force') is True)
            if not result:
                return jsonify(success=False, error='Nessun flusso diretto disponibile su questo server Guardaserie'), 502
            if not result.get('manifest_text'):
                response = media_get(engine.session, result['master_m3u8'], headers=result['headers'], timeout=12)
                response.raise_for_status()
                result['manifest_text'] = response.text
            def resource(target):
                return '/api/stream/segment?' + urllib.parse.urlencode({'url': target, 'ref': result['vix_url']})
            audio, subtitles, qualities = manifest_metadata(result['manifest_text'], result['master_m3u8'], resource)
            proxy = '/api/stream/proxy?' + urllib.parse.urlencode({'url': url})
            return jsonify(success=True, is_embed=False, provider='guardoseries', master_m3u8=proxy,
                           vix_url=result['vix_url'], audio_tracks=audio, subtitle_tracks=subtitles, qualities=qualities)
        except Exception as error:
            app.logger.warning('Guardaserie extraction failed: %s', type(error).__name__)
            return jsonify(success=False, error='Flusso diretto Guardaserie temporaneamente non disponibile'), 502

    active_sc_domain = engine.get_active_sc_domain()
    domain = urllib.parse.urlsplit(active_sc_domain)
    target = urllib.parse.urlsplit(url)
    watch_match = re.search(r'/(?:it/)?watch/(\d+)', target.path)
    if target.path.startswith('/titles/'):
        url = urllib.parse.urlunsplit((domain.scheme, domain.netloc, target.path, target.query, target.fragment))
    elif watch_match:
        url = urllib.parse.urlunsplit((domain.scheme, domain.netloc, f"/titles/{watch_match.group(1)}/watching", target.query, target.fragment))
    elif target.hostname != domain.hostname:
        return jsonify(success=False,error='Apri il titolo dal catalogo StreamingCommunity ripristinato'),400
    try:
        diagnostics = {}
        result = engine.extract_modern_stream(url,force=data.get('force') is True,diagnostics=diagnostics)
        if not result:
            app.logger.warning('StreamingCommunity extraction unavailable: %s', diagnostics)
            return jsonify(success=False,error='Flusso StreamingCommunity temporaneamente non disponibile',diagnostics=diagnostics),502
        if not result.get('manifest_text'):
            try:
                sign_master = engine.sc_stream_tokens.sign(result['master_m3u8'], result['vix_url'])
                m_res = media_get(engine.session, sign_master, headers=result['headers'], timeout=6)
                if m_res.status_code == 200:
                    result['manifest_text'] = m_res.text
            except Exception:
                pass
        proxy = '/api/stream/proxy?' + urllib.parse.urlencode({'url':url})
        tracks = [{**track,'uri':'/api/stream/segment?' + urllib.parse.urlencode({'url':track['uri'],'ref':track['referrer']})}
                  for track in result.get('subtitle_tracks',[])]
        return jsonify(success=True,master_m3u8=proxy,vix_url=result['vix_url'],embed_url=result['vix_url'],subtitle_tracks=tracks)
    except Exception as error:
        app.logger.warning('StreamingCommunity extraction failed: %s',type(error).__name__)
        return jsonify(success=False,error='Flusso StreamingCommunity temporaneamente non disponibile'),502



from src.online_subtitles import OnlineSubtitles
online_subtitles = OnlineSubtitles(engine, TMDB_API_KEY)

@app.route('/api/subtitles/search', methods=['POST'])
def search_online_subtitles():
    item = request.get_json(silent=True) or {}
    if not isinstance(item, dict): return jsonify(error='Titolo non valido'), 400
    try:
        return jsonify(success=True, tracks=online_subtitles.search(item), source='OpenSubtitles / Stremio')
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    except Exception:
        return jsonify(error='Ricerca sottotitoli temporaneamente non disponibile. Riprova.'), 502

@app.route('/api/subtitles/file/<token>.vtt')
def load_online_subtitle(token):
    if not re.fullmatch(r'[0-9a-f]{32}', token):return jsonify(error='Traccia non valida'), 404
    try:
        return Response(online_subtitles.load(token), content_type='text/vtt; charset=utf-8',
            headers={'Cache-Control':'private, max-age=300', 'X-Content-Type-Options':'nosniff'})
    except KeyError:
        return jsonify(error='Traccia scaduta. Ripeti la ricerca.'), 404
    except Exception:
        return jsonify(error='Sottotitoli non disponibili. Prova un’altra traccia.'), 502


@app.route('/api/download/options', methods=['POST'])
def get_download_options():
    from src.download_options import download_options
    item = request.get_json(silent=True) or {}
    if not isinstance(item, dict):
        return jsonify(error='Titolo non valido'), 400
    try:
        return jsonify(success=True, sources=download_options(engine, Guardaserie(engine.session), item))
    except (ValueError, TypeError):
        return jsonify(error='Titolo o episodio non valido'), 400


@app.route('/api/download/start', methods=['POST'])
def start_download():
    data = request.get_json() or {}
    # The server's listening port, rather than the client-controlled Host header.
    engine.download_proxy_base = f"http://127.0.0.1:{int(request.environ.get('SERVER_PORT', 5555))}"
    return jsonify(engine.start_download(
        url=data.get('url'),
        media_type=data.get('media_type', 'hls'),
        format_choice=data.get('format_choice', '1080p'),
        custom_title=data.get('custom_title'),
        custom_headers=data.get('custom_headers'),
        parent_folder=data.get('parent_folder'),
        poster=data.get('poster')
    ))

@app.route('/api/download/pause/<download_id>', methods=['POST'])
def pause_download(download_id):
    return jsonify(engine.pause_download(download_id))

@app.route('/api/download/resume/<download_id>', methods=['POST'])
def resume_download(download_id):
    return jsonify(engine.resume_download(download_id))

@app.route('/api/download/cancel/<download_id>', methods=['POST'])
def cancel_download(download_id):
    return jsonify(engine.cancel_download(download_id))

@app.route('/api/download/status/<download_id>', methods=['GET'])
def download_status(download_id):
    return jsonify(engine.get_status(download_id))

@app.route('/api/download/all', methods=['GET'])
def get_all_downloads():
    d_list = [{k: v for k, v in d.items() if k != "process"} for d in engine.downloads.values()]
    d_list.sort(key=lambda x: x.get('download_id', ''), reverse=True)
    return jsonify({"success": True, "downloads": d_list})

@app.route('/api/download/open-folder', methods=['POST', 'GET'])
def open_download_folder():
    try:
        data = request.get_json(silent=True) or {}
        filepath = data.get('filepath')
        if filepath and os.path.exists(filepath):
            if os.path.isfile(filepath):
                subprocess.run(['open', '-R', filepath])
            else:
                subprocess.run(['open', filepath])
        elif filepath and os.path.exists(os.path.dirname(filepath)):
            subprocess.run(['open', os.path.dirname(filepath)])
        else:
            subprocess.run(['open', DOWNLOADS_DIR])
        return jsonify({"success": True})
    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)})

@app.route('/api/stream/master.m3u8', methods=['GET'])
def stream_master_proxy():
    title_id = request.args.get('titleId') or request.args.get('id')
    ep_id = request.args.get('e') or request.args.get('episodeId')
    active_domain = engine.get_active_sc_domain()
    url = f"{active_domain}/it/watch/{title_id}" if title_id else ""
    if ep_id:
        url += f"?e={ep_id}"
    extracted = engine.extract_sc_m3u8(url) if url else None
    if extracted and extracted.get('master_m3u8'):
        return redirect(extracted['master_m3u8'])
    return jsonify({"error": "Stream not found"}), 404

@app.route('/api/stream/proxy', methods=['GET'])
def stream_proxy_manifest():
    watch_url = request.args.get('url', '')
    title_id = request.args.get('titleId') or request.args.get('id')
    ep_id = request.args.get('e') or request.args.get('episodeId')
    if not watch_url and title_id:
        active_domain = engine.get_active_sc_domain()
        watch_url = f"{active_domain}/it/watch/{title_id}"
        if ep_id:
            watch_url += f"?e={ep_id}"
    if not watch_url:
        return jsonify({"error": "Parametro URL mancante"}), 400

    modern = '/titles/' in urllib.parse.urlsplit(watch_url).path and '/watching' in urllib.parse.urlsplit(watch_url).path
    guardaserie = urllib.parse.urlsplit(watch_url).hostname in ('guardoseries.click', 'vixsrc.to')
    extracted = (engine.extract_guardaserie_stream(watch_url, force=bool(request.args.get('renew'))) if guardaserie else
                 engine.extract_modern_stream(watch_url, force=bool(request.args.get('renew'))) if modern else engine.extract_sc_m3u8(watch_url))
    if not extracted:
        return jsonify({"error": "Impossibile estrarre lo stream Vixcloud"}), 404

    master_m3u8 = extracted['master_m3u8']
    vix_url = extracted['vix_url']

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': vix_url or 'https://vixcloud.co/',
        'Origin': 'https://vixcloud.co'
    }

    if guardaserie:
        headers = extracted['headers']
    if modern:
        headers = extracted['headers']
        master_m3u8 = engine.sc_stream_tokens.sign(master_m3u8, vix_url)
    try:
        content = extracted.get('manifest_text')
        if not content:
            r = media_get(engine.session, master_m3u8, headers=headers, timeout=8)
            if modern and r.status_code in (401, 403):
                extracted = engine.extract_modern_stream(watch_url, force=True)
                if extracted:
                    master_m3u8, vix_url = extracted['master_m3u8'], extracted['vix_url']
                    r = media_get(engine.session, master_m3u8, headers=extracted['headers'], timeout=8)
            if r.status_code != 200:
                return jsonify({"error": "Impossibile recuperare il manifest HLS"}), 500
            content = r.text
            extracted['manifest_text'] = content
        lines = content.splitlines()
        rewritten_lines = []

        def make_proxy_url(target_u):
            abs_u = urllib.parse.urljoin(master_m3u8, target_u)
            return f"/api/stream/segment?url={urllib.parse.quote(abs_u)}&ref={urllib.parse.quote(vix_url)}"

        for line in lines:
            line_str = line.strip()
            if line_str and not line_str.startswith('#'):
                rewritten_lines.append(make_proxy_url(line_str))
            elif 'URI=' in line_str:
                def replace_uri(match):
                    u = match.group(1)
                    return f'URI="{make_proxy_url(u)}"'
                rewritten_tag = re.sub(r'URI=["\']([^"\']+)["\']', replace_uri, line_str)
                rewritten_lines.append(rewritten_tag)
            else:
                rewritten_lines.append(line_str)

        response_text = "\n".join(rewritten_lines)
        return Response(response_text, mimetype='application/vnd.apple.mpegurl', headers={
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-cache'
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500





_cdn_pooled_session = None
_cdn_pooled_lock = threading.Lock()
_playlist_cache = {}
_playlist_lock = threading.Lock()
_segment_cache = {}
_segment_lock = threading.Lock()

def get_cdn_pooled_session():
    global _cdn_pooled_session
    if _cdn_pooled_session is None:
        with _cdn_pooled_lock:
            if _cdn_pooled_session is None:
                s = requests.Session()
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=64,
                    pool_maxsize=64,
                    max_retries=1,
                    pool_block=False
                )
                s.mount('https://', adapter)
                s.mount('http://', adapter)
                _cdn_pooled_session = s
    return _cdn_pooled_session

@app.route('/api/stream/segment', methods=['GET'])
def stream_proxy_segment():
    segment_url = request.args.get('url', '')
    ref_url = request.args.get('ref', '')
    if not segment_url:
        return jsonify({"error": "Parametro URL segment mancante"}), 400

    segment_url = engine.sc_stream_tokens.sign(segment_url, ref_url)
    parsed_seg = urllib.parse.urlsplit(segment_url)
    is_vidxgo = (
        parsed_seg.hostname == 'v.vidxgo.co' or
        (parsed_seg.hostname and (parsed_seg.hostname.endswith('.d2b.you') or 'd2b' in parsed_seg.hostname)) or
        (ref_url and 'vidxgo' in ref_url)
    )

    if is_vidxgo:
        effective_ref = ref_url if (ref_url and 'vidxgo' in ref_url) else 'https://v.vidxgo.co/'
        headers = media_headers(effective_ref)
    else:
        effective_ref = ref_url or 'https://vixcloud.cc/'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': effective_ref,
            'Origin': urllib.parse.urlsplit(effective_ref).scheme + '://' + urllib.parse.urlsplit(effective_ref).netloc
        }
    try:
        is_manifest = '.m3u8' in parsed_seg.path.lower() or 'playlist' in parsed_seg.path.lower()
        if is_manifest:
            with _playlist_lock:
                cached_pl = _playlist_cache.get(segment_url)
                if cached_pl and time.monotonic() - cached_pl[0] < 45:
                    return Response(cached_pl[1], mimetype='application/vnd.apple.mpegurl', headers={
                        'Access-Control-Allow-Origin': '*',
                        'Cache-Control': 'public, max-age=15'
                    })
            r = media_get(engine.session, segment_url, headers=headers, timeout=10)
            if r.status_code in (401, 403):
                renewed_url = engine.sc_stream_tokens.sign(segment_url, ref_url, force=True)
                if renewed_url != segment_url:
                    segment_url = renewed_url
                    r = media_get(engine.session, segment_url, headers=headers, timeout=10)
            if r.status_code != 200:
                return jsonify({"error": "Risorsa video temporaneamente non disponibile"}), r.status_code
            content = r.text
            lines = content.splitlines()
            rewritten_lines = []
            def make_sub_proxy_url(target_u):
                abs_u = urllib.parse.urljoin(segment_url, target_u)
                return f"/api/stream/segment?url={urllib.parse.quote(abs_u)}&ref={urllib.parse.quote(ref_url)}"

            for line in lines:
                line_str = line.strip()
                if line_str and not line_str.startswith('#'):
                    rewritten_lines.append(make_sub_proxy_url(line_str))
                elif 'URI=' in line_str:
                    def replace_uri(match):
                        u = match.group(1)
                        return f'URI="{make_sub_proxy_url(u)}"'
                    rewritten_tag = re.sub(r'URI=["\']([^"\']+)["\']', replace_uri, line_str)
                    rewritten_lines.append(rewritten_tag)
                else:
                    rewritten_lines.append(line_str)

            response_text = "\n".join(rewritten_lines)
            with _playlist_lock:
                if len(_playlist_cache) > 80:
                    _playlist_cache.clear()
                _playlist_cache[segment_url] = (time.monotonic(), response_text)
            return Response(response_text, mimetype='application/vnd.apple.mpegurl', headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=15'
            })

        # Fast Segment in-memory cache check
        if '_segment_lock' in globals() and '_segment_cache' in globals():
            with _segment_lock:
                cached_seg = _segment_cache.get(segment_url)
            if cached_seg and time.monotonic() - cached_seg[0] < 300:
                c_data, c_status, c_type = cached_seg[1], cached_seg[2], cached_seg[3]
                if c_type == 'text/html':
                    c_type = 'video/mp2t'
                return Response(c_data, status=c_status, content_type=c_type, headers={
                    'Access-Control-Allow-Origin': '*',
                    'Content-Length': str(len(c_data)),
                    'Accept-Ranges': 'bytes',
                    'Cache-Control': 'public, max-age=86400, immutable'
                })

        # Video chunk / segment: progressive streaming
        if request.headers.get('Range'):
            headers['Range'] = request.headers['Range']
        client = getattr(engine, 'session', None) or cffi_requests.Session(impersonate='chrome120')
        upstream = media_get(client, segment_url, headers=headers, stream=True, timeout=15)
        if upstream.status_code in (401, 403):
            renewed_url = engine.sc_stream_tokens.sign(segment_url, ref_url, force=True)
            if renewed_url != segment_url:
                segment_url = renewed_url
                upstream = media_get(client, segment_url, headers=headers, stream=True, timeout=15)

        if upstream.status_code not in (200, 206):
            return jsonify(error='Risorsa video temporaneamente non disponibile'), upstream.status_code

        raw_c_type = upstream.headers.get('Content-Type', '')
        url_lower = segment_url.lower()
        if 'enc.key' in url_lower or url_lower.endswith('.key') or '/storage/key' in url_lower or 'key' in parsed_seg.path.lower():
            c_type = 'application/octet-stream'
        elif '.vtt' in url_lower or 'subtitle' in url_lower:
            c_type = 'text/vtt'
        elif '/audio/' in url_lower:
            c_type = 'video/mp2t'
        elif '/video/' in url_lower or '.ts' in url_lower or '.html' in parsed_seg.path or raw_c_type == 'text/html':
            c_type = 'video/mp2t'
        else:
            c_type = raw_c_type or 'video/mp2t'
        outgoing = {key: upstream.headers[key] for key in
                    ('Content-Range', 'Content-Length', 'Accept-Ranges') if upstream.headers.get(key)}
        if 'Accept-Ranges' not in outgoing:
            outgoing['Accept-Ranges'] = 'bytes'
        outgoing['Access-Control-Allow-Origin'] = '*'
        outgoing['Cache-Control'] = 'public, max-age=86400, immutable'
        outgoing['X-Accel-Buffering'] = 'no'

        def generate():
            try:
                for chunk in upstream.iter_content(chunk_size=131072):
                    if chunk:
                        yield chunk
            finally:
                if hasattr(upstream, 'close'):
                    upstream.close()

        return Response(generate(), status=upstream.status_code, content_type=c_type, headers=outgoing)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500



# HISTORY PERSISTENCE ON DISK
HISTORY_FILE = ensure_seed_data(user_data_file("history.json", "~/.streamingcommunity_history.json"), "history.json")
history_lock = threading.RLock()

def load_history_data():
    with history_lock:
        for p in [HISTORY_FILE, HISTORY_FILE + ".bak"]:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                except Exception:
                    pass
        return []

def save_history_data(history_list):
    with history_lock:
        try:
            tmp = HISTORY_FILE + ".tmp"
            bak = HISTORY_FILE + ".bak"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(history_list, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            try:
                shutil.copyfile(tmp, bak)
            except Exception:
                pass
            os.replace(tmp, HISTORY_FILE)
        except Exception as e:
            print("Error saving history to disk:", e)

FAVORITES_FILE = ensure_seed_data(user_data_file("favorites.json", "~/.streamingcommunity_favorites.json"), "favorites.json")
favorites_lock = threading.RLock()

def load_favorites_data():
    with favorites_lock:
        for p in [FAVORITES_FILE, FAVORITES_FILE + ".bak"]:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            return data
                except Exception:
                    pass
        return {}

def save_favorites_data(fav_data):
    with favorites_lock:
        try:
            tmp = FAVORITES_FILE + ".tmp"
            bak = FAVORITES_FILE + ".bak"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(fav_data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(FAVORITES_FILE) and os.path.getsize(FAVORITES_FILE) > 0:
                try:
                    shutil.copyfile(FAVORITES_FILE, bak)
                except Exception:
                    pass
            os.replace(tmp, FAVORITES_FILE)
        except Exception as e:
            print("Error saving favorites to disk:", e)

# -------------------------------------------------------------
# MULTI-USER PROFILES SYSTEM (PERSISTENCE & SECURITY)
# -------------------------------------------------------------
PROFILES_FILE = ensure_seed_data(user_data_file("profiles.json", "~/.streamingcommunity_profiles.json"), "profiles.json")
AVATARS_DIR = os.path.expanduser("~/.streamingcommunity/avatars")
try:
    os.makedirs(AVATARS_DIR, exist_ok=True)
except Exception:
    pass

profiles_lock = threading.RLock()

def load_profiles_data():
    with profiles_lock:
        data = None
        for path in [PROFILES_FILE, PROFILES_FILE + ".bak"]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict) and "profiles" in loaded and isinstance(loaded["profiles"], list):
                            if len(loaded["profiles"]) >= 3:
                                data = loaded
                                break
                            elif len(loaded["profiles"]) > 0:
                                data = loaded
                except Exception as e:
                    print(f"Error reading profiles data from {path}:", e)

        # Merge or initialize with seed_data if Martina or Francesco are missing
        try:
            import seed_data
            seed_profs = seed_data.PROFILES_DATA.get("profiles", [])
            if not data or not isinstance(data.get("profiles"), list) or len(data.get("profiles")) == 0:
                data = dict(seed_data.PROFILES_DATA)
                save_profiles_data(data)
                return data
            else:
                existing_names = {p.get("name") for p in data.get("profiles", []) if isinstance(p, dict)}
                existing_ids = {p.get("id") for p in data.get("profiles", []) if isinstance(p, dict)}
                changed = False
                for sp in seed_profs:
                    if sp.get("name") not in existing_names and sp.get("id") not in existing_ids:
                        data["profiles"].append(sp)
                        changed = True
                    else:
                        for p in data["profiles"]:
                            if p.get("name") == sp.get("name"):
                                if not p.get("history") and sp.get("history"):
                                    p["history"] = sp.get("history")
                                    changed = True
                                if not p.get("favorites") and sp.get("favorites"):
                                    p["favorites"] = sp.get("favorites")
                                    changed = True
                                if not p.get("pin") and sp.get("pin"):
                                    p["pin"] = sp.get("pin")
                                    changed = True
                if changed:
                    save_profiles_data(data)
                return data
        except Exception as e:
            print("Error loading profiles from seed_data:", e)

        if data:
            return data
        return {
            "active_profile_id": None,
            "profiles": []
        }

def save_profiles_data(data):
    with profiles_lock:
        try:
            if not isinstance(data, dict) or "profiles" not in data:
                print("Refusing to save invalid profiles data:", data)
                return

            tmp_file = PROFILES_FILE + ".tmp"
            bak_file = PROFILES_FILE + ".bak"

            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())

            if os.path.exists(PROFILES_FILE) and os.path.getsize(PROFILES_FILE) > 0:
                try:
                    shutil.copyfile(PROFILES_FILE, bak_file)
                except Exception:
                    pass

            os.replace(tmp_file, PROFILES_FILE)
        except Exception as e:
            print("Error saving profiles data:", e)

def sanitize_profile(prof):
    if not prof:
        return None
    p = dict(prof)
    p["has_pin"] = bool(p.get("pin"))
    p.pop("pin", None)
    p.pop("biometric_enabled", None)
    p.pop("webauthn_credential_id", None)
    p.pop("has_biometrics", None)
    p.pop("history", None)
    p.pop("favorites", None)
    return p

def get_profile_by_id(profiles_data, profile_id):
    if not profile_id:
        return None
    for p in profiles_data.get("profiles", []):
        if p.get("id") == profile_id:
            return p
    # Fallback alias if a temporary session ID is passed
    if profile_id == "prof_1789233590_45a7c9":
        for p in profiles_data.get("profiles", []):
            if p.get("id") == "prof_1789214856_30de20":
                return p
    return None

@app.route('/api/profiles', methods=['GET'])
def get_profiles():
    data = load_profiles_data()
    return jsonify({
        "active_profile_id": data.get("active_profile_id"),
        "profiles": [sanitize_profile(p) for p in data.get("profiles", [])]
    })

@app.route('/api/profiles/create', methods=['POST'])
def create_profile():
    import time, uuid
    req = request.get_json(silent=True) or {}
    name = (req.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Il nome del profilo è obbligatorio"}), 400

    prof_id = f"prof_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    avatar = req.get("avatar") or "preset:netflix-red"
    pin = (req.get("pin") or "").strip()

    data = load_profiles_data()
    is_first = len(data.get("profiles", [])) == 0

    initial_history = []
    initial_favorites = {}
    if is_first:
        initial_history = load_history_data()
        initial_favorites = load_favorites_data()

    new_profile = {
        "id": prof_id,
        "name": name,
        "avatar": avatar,
        "pin": pin if pin else None,
        "history": initial_history,
        "favorites": initial_favorites,
        "created_at": int(time.time() * 1000)
    }

    data["profiles"].append(new_profile)
    data["active_profile_id"] = prof_id
    save_profiles_data(data)

    return jsonify({
        "success": True,
        "profile": sanitize_profile(new_profile),
        "active_profile_id": prof_id,
        "profiles": [sanitize_profile(p) for p in data["profiles"]]
    })

@app.route('/api/profiles/update', methods=['POST'])
def update_profile():
    req = request.get_json(silent=True) or {}
    prof_id = req.get("id")
    if not prof_id:
        return jsonify({"success": False, "error": "ID profilo mancante"}), 400

    data = load_profiles_data()
    prof = get_profile_by_id(data, prof_id)
    if not prof:
        return jsonify({"success": False, "error": "Profilo non trovato"}), 404

    is_disabling_pin = (("enable_pin" in req and not req.get("enable_pin")) or ("remove_pin" in req and req.get("remove_pin")))
    if prof.get("pin") and is_disabling_pin:
        current_pin = str(req.get("current_pin") or "").strip()
        if not current_pin or current_pin != str(prof.get("pin")).strip():
            return jsonify({"success": False, "error": "PIN attuale errato. Impossibile disabilitare la sicurezza."}), 403

    if "name" in req and req["name"].strip():
        prof["name"] = req["name"].strip()
    if "avatar" in req and req["avatar"]:
        prof["avatar"] = req["avatar"]
    if is_disabling_pin:
        prof["pin"] = None
    elif "pin" in req:
        new_pin = req["pin"].strip() if isinstance(req["pin"], str) else None
        prof["pin"] = new_pin if new_pin else None

    prof.pop("biometric_enabled", None)
    prof.pop("webauthn_credential_id", None)

    save_profiles_data(data)
    return jsonify({
        "success": True,
        "profile": sanitize_profile(prof),
        "profiles": [sanitize_profile(p) for p in data["profiles"]]
    })

@app.route('/api/profiles/delete', methods=['POST'])
def delete_profile():
    req = request.get_json(silent=True) or {}
    prof_id = req.get("id")
    if not prof_id:
        return jsonify({"success": False, "error": "ID profilo mancante"}), 400

    data = load_profiles_data()
    prof = get_profile_by_id(data, prof_id)
    if not prof:
        return jsonify({"success": False, "error": "Profilo non trovato"}), 404

    if prof.get("pin"):
        current_pin = str(req.get("current_pin") or "").strip()
        if not current_pin or current_pin != str(prof.get("pin")).strip():
            return jsonify({"success": False, "error": "PIN errato. Impossibile eliminare il profilo protetto."}), 403

    data["profiles"] = [p for p in data.get("profiles", []) if p.get("id") != prof_id]
    if data.get("active_profile_id") == prof_id:
        data["active_profile_id"] = data["profiles"][0]["id"] if data["profiles"] else None

    save_profiles_data(data)
    return jsonify({
        "success": True,
        "active_profile_id": data.get("active_profile_id"),
        "profiles": [sanitize_profile(p) for p in data["profiles"]]
    })

@app.route('/api/profiles/select', methods=['POST'])
def select_profile():
    req = request.get_json(silent=True) or {}
    prof_id = req.get("id")
    data = load_profiles_data()
    prof = get_profile_by_id(data, prof_id)
    if not prof:
        return jsonify({"success": False, "error": "Profilo non trovato"}), 404

    data["active_profile_id"] = prof_id
    save_profiles_data(data)
    return jsonify({
        "success": True,
        "active_profile_id": prof_id,
        "profile": sanitize_profile(prof)
    })

@app.route('/api/profiles/verify_pin', methods=['POST'])
def verify_profile_pin():
    req = request.get_json(silent=True) or {}
    prof_id = req.get("id")
    pin = str(req.get("pin") or "").strip()
    data = load_profiles_data()
    prof = get_profile_by_id(data, prof_id)
    if not prof:
        return jsonify({"success": False, "error": "Profilo non trovato"}), 404

    stored_pin = str(prof.get("pin") or "").strip()
    if not stored_pin or stored_pin == pin:
        return jsonify({"success": True, "valid": True})
    return jsonify({"success": False, "valid": False, "error": "PIN non corretto"}), 401

@app.route('/api/profiles/upload-avatar', methods=['POST'])
def upload_avatar():
    try:
        import time, uuid, base64
        avatar_url = ""
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
                filename = f"avatar_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                filepath = os.path.join(AVATARS_DIR, filename)
                file.save(filepath)
                avatar_url = f"/api/profiles/avatar/{filename}"
        else:
            json_data = request.get_json(silent=True) or {}
            data_url = json_data.get("image_data", "")
            if data_url and data_url.startswith("data:image"):
                header, encoded = data_url.split(",", 1)
                ext = "png"
                if "jpeg" in header or "jpg" in header: ext = "jpg"
                elif "webp" in header: ext = "webp"
                filename = f"avatar_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                filepath = os.path.join(AVATARS_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(encoded))
                avatar_url = f"/api/profiles/avatar/{filename}"

        if avatar_url:
            return jsonify({"success": True, "avatar_url": avatar_url})
        return jsonify({"success": False, "error": "Nessuna immagine valida ricevuta"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/profiles/avatar/<filename>', methods=['GET'])
def get_avatar_file(filename):
    from flask import send_from_directory
    return send_from_directory(AVATARS_DIR, filename)

@app.route('/api/user_data/bundle', methods=['GET'])
def get_user_data_bundle():
    try:
        return jsonify({
            "success": True,
            "profiles": load_profiles_data(),
            "favorites": load_favorites_data(),
            "history": load_history_data()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/user_data/sync', methods=['POST'])
def sync_user_data():
    try:
        data = request.get_json() or {}
        if "profiles" in data and isinstance(data["profiles"], dict):
            save_profiles_data(data["profiles"])
        if "favorites" in data and isinstance(data["favorites"], dict):
            save_favorites_data(data["favorites"])
        if "history" in data and isinstance(data["history"], list):
            save_history_data(data["history"])
        return jsonify({"success": True, "message": "Dati utente sincronizzati con successo."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# -------------------------------------------------------------
# WATCHPARTY — SYNCHRONIZED VIEWING BETWEEN PROFILES
# -------------------------------------------------------------
WATCHPARTY_FILE = ensure_seed_data(user_data_file("watchparty.json", "~/.streamingcommunity_watchparty.json"), "watchparty.json")
WATCHPARTY_LOCK = threading.RLock()

def load_watchparty_data():
    if os.path.exists(WATCHPARTY_FILE):
        try:
            with open(WATCHPARTY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sessions": []}

def save_watchparty_data(data):
    try:
        # Replace the file in one operation so polling clients never read a
        # partially-written JSON document.
        temp_file = f"{WATCHPARTY_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, WATCHPARTY_FILE)
    except Exception as e:
        print("Error saving watchparty data:", e)

def cleanup_old_sessions(data):
    import time as _time
    now = _time.time() * 1000
    max_age = 3600000 * 2  # 2 hours
    data["sessions"] = [s for s in data.get("sessions", [])
        if (now - s.get("created_at", 0)) < max_age and streamingcommunity_item(s.get('item'))]
    return data

@app.route('/api/watchparty/create', methods=['POST'])
def watchparty_create():
    import time as _time, uuid as _uuid
    req = request.get_json(silent=True) or {}
    host_profile_id = req.get("host_profile_id")
    guest_profile_id = req.get("guest_profile_id")
    item = req.get("item")

    if not host_profile_id or not item:
        return jsonify({"success": False, "error": "Parametri mancanti"}), 400
    if not streamingcommunity_item(item):
        return jsonify(success=False,error='Seleziona un titolo StreamingCommunity'),400

    profiles_data = load_profiles_data()
    host_prof = get_profile_by_id(profiles_data, host_profile_id)
    if not host_prof:
        return jsonify({"success": False, "error": "Profilo host non trovato"}), 404

    guest_prof = get_profile_by_id(profiles_data, guest_profile_id) if guest_profile_id else None
    guest_name = req.get("guest_name") or (guest_prof.get("name") if guest_prof else "Ospite")
    guest_avatar = req.get("guest_avatar") or (guest_prof.get("avatar") if guest_prof else "")

    session_id = (req.get("session_id") and str(req.get("session_id")).strip()) or f"wp_{int(_time.time())}_{_uuid.uuid4().hex[:8]}"

    with WATCHPARTY_LOCK:
        data = cleanup_old_sessions(load_watchparty_data())

        # A profile can host only one live party at a time.
        for s in data["sessions"]:
            if s.get("session_id") != session_id and s.get("host_profile_id") == host_profile_id and s.get("status") in ("waiting", "active"):
                s["status"] = "ended"

        initial_time = 0.0
        try:
            initial_time = float(item.get("currentTime") or item.get("current_time") or 0)
        except Exception:
            initial_time = 0.0

        data["sessions"] = [s for s in data["sessions"] if s.get("session_id") != session_id]

        session = {
            "session_id": session_id,
            "host_profile_id": host_profile_id,
            "host_name": host_prof.get("name", "Host"),
            "host_avatar": host_prof.get("avatar", ""),
            "guest_profile_id": guest_profile_id or None,
            "guest_name": guest_name,
            "guest_avatar": guest_avatar,
            "item": item,
            "status": "waiting",
            "current_time": initial_time,
            "stream_url": str(req.get("stream_url", ""))[:2000] if req.get("stream_url") else None,
            "paused": True,
            "guest_ready": False,
            "guest_buffering": False,
            "last_action": None,
            "last_sync": int(_time.time() * 1000),
            "created_at": int(_time.time() * 1000)
        }

        data["sessions"].append(session)
        save_watchparty_data(data)

    req["session_id"] = session_id
    # Also proxy to Render Hub asynchronously so both nodes know about the session without blocking
    proxy_to_render_wp_async("create", method="POST", json_data=req)

    return jsonify({"success": True, "session_id": session_id, "session": session})

def proxy_to_render_wp(endpoint, method="GET", json_data=None, params=None):
    if os.environ.get("WATCHPARTY_LOCAL_ONLY") == "1": return None
    try:
        import urllib.request
        import urllib.parse
        import json
        import ssl
        ctx = ssl._create_unverified_context()
        hub_url = os.environ.get("RENDER_WP_HUB", "https://mediadownloaderpro-3q69.onrender.com").rstrip("/")
        url = f"{hub_url}/api/watchparty/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req_data = json.dumps(json_data).encode("utf-8") if json_data is not None else None
        headers = {"User-Agent": "MediaDownloaderStream"}
        if req_data:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        with urllib.request.urlopen(req, context=ctx, timeout=1.5) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {"success": True}
    except Exception as e:
        print("[WatchParty Proxy Error]", e)
        return None

def proxy_to_render_wp_async(endpoint, method="POST", json_data=None, params=None):
    try:
        import threading
        t = threading.Thread(
            target=proxy_to_render_wp,
            args=(endpoint,),
            kwargs={"method": method, "json_data": json_data, "params": params},
            daemon=True
        )
        t.start()
    except Exception as e:
        print("[WatchParty Proxy Async Launch Error]", e)

@app.route('/api/watchparty/pending', methods=['GET'])
def watchparty_pending():
    profile_id = request.args.get("profile_id")
    if not profile_id:
        return jsonify({"success": True, "sessions": []})

    data = load_watchparty_data()
    data = cleanup_old_sessions(data)

    pending = [s for s in data.get("sessions", [])
               if s.get("guest_profile_id") == profile_id and s.get("status") == "waiting"]

    # If nothing found locally, query Render Hub so invitations from external clients reach localhost
    if not pending:
        remote_res = proxy_to_render_wp("pending", method="GET", params={"profile_id": profile_id})
        if remote_res and isinstance(remote_res.get("sessions"), list):
            for rs in remote_res["sessions"]:
                pending.append(rs)

    return jsonify({"success": True, "sessions": pending})

@app.route('/api/watchparty/accept', methods=['POST'])
def watchparty_accept():
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    guest_profile_id = req.get("guest_profile_id")
    guest_name = req.get("guest_name")
    guest_avatar = req.get("guest_avatar")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with WATCHPARTY_LOCK:
        data = load_watchparty_data()
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id and s.get("status") in ("waiting", "active"):
                s["status"] = "active"
                if guest_profile_id:
                    s["guest_profile_id"] = guest_profile_id
                if guest_name:
                    s["guest_name"] = guest_name
                if guest_avatar:
                    s["guest_avatar"] = guest_avatar
                s["last_sync"] = int(time.time() * 1000)
                save_watchparty_data(data)
                proxy_to_render_wp_async("accept", method="POST", json_data=req)
                return jsonify({"success": True, "session": s})

    remote = proxy_to_render_wp("accept", method="POST", json_data=req)
    if remote and remote.get("success"):
        return jsonify(remote)

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

@app.route('/api/watchparty/decline', methods=['POST'])
def watchparty_decline():
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with WATCHPARTY_LOCK:
        data = load_watchparty_data()
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id and s.get("status") == "waiting":
                s["status"] = "declined"
                save_watchparty_data(data)
                proxy_to_render_wp_async("decline", method="POST", json_data={"session_id": session_id})
                return jsonify({"success": True})

    remote = proxy_to_render_wp("decline", method="POST", json_data={"session_id": session_id})
    if remote and remote.get("success"):
        return jsonify(remote)

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

@app.route('/api/watchparty/sync', methods=['POST'])
def watchparty_sync():
    import time as _time
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with WATCHPARTY_LOCK:
        data = load_watchparty_data()
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id and s.get("status") in ("waiting", "active"):
                if "current_time" in req:
                    s["current_time"] = max(0, float(req["current_time"]))
                if "paused" in req:
                    s["paused"] = bool(req["paused"])
                if "guest_ready" in req:
                    s["guest_ready"] = bool(req["guest_ready"])
                if "guest_buffering" in req:
                    s["guest_buffering"] = bool(req["guest_buffering"])
                if req.get("stream_url"):
                    s["stream_url"] = str(req["stream_url"])[:2000]
                if isinstance(req.get("item"), dict):
                    allowed = ("id", "name", "title", "slug", "type", "poster",
                               "backdrop", "cover", "current_watch_url",
                               "provider", "source", "source_format", "external_url", "watch_url",
                               "current_episode_id", "current_episode_number",
                               "current_season_number", "current_ep_name",
                               "current_ep_title", "currentTime", "current_time")
                    s["item"] = {k: req["item"].get(k) for k in allowed}
                s["last_action"] = req.get("action", req.get("last_action", "sync"))
                s["last_sync"] = int(_time.time() * 1000)
                save_watchparty_data(data)
                proxy_to_render_wp_async("sync", method="POST", json_data=req)
                return jsonify({"success": True, "session": s})

    remote = proxy_to_render_wp("sync", method="POST", json_data=req)
    if remote and remote.get("success"):
        return jsonify(remote)

    return jsonify({"success": False, "error": "Sessione non trovata o non attiva"}), 404

# Chat uses the same room identity, with a separate store from playback commands.
from src.watchparty_chat import register_watchparty_chat

def lookup_chat_session(session_id):
    # Playback authority lives on the shared hub, including for localhost users.
    remote = proxy_to_render_wp("state", method="GET", params={"session_id": session_id})
    return remote.get("session") if remote and remote.get("success") else None

register_watchparty_chat(app, lookup_chat_session)

@app.route('/api/watchparty/state', methods=['GET'])
def watchparty_state():
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    data = load_watchparty_data()
    for s in data.get("sessions", []):
        if s.get("session_id") == session_id:
            return jsonify({"success": True, "session": s})

    remote = proxy_to_render_wp("state", method="GET", params={"session_id": session_id})
    if remote and remote.get("success"):
        return jsonify(remote)

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

@app.route('/api/watchparty/end', methods=['POST'])
def watchparty_end():
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with WATCHPARTY_LOCK:
        data = load_watchparty_data()
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id:
                s["status"] = "ended"
                save_watchparty_data(data)
                proxy_to_render_wp_async("end", method="POST", json_data={"session_id": session_id})
                return jsonify({"success": True})

    remote = proxy_to_render_wp("end", method="POST", json_data={"session_id": session_id})
    if remote and remote.get("success"):
        return jsonify(remote)

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

@app.route('/watch/<room_id>', methods=['GET'])
def watch_room_redirect(room_id):
    from flask import redirect
    return redirect(f"/?room={room_id}")

SOCKET_ROOMS = {}
SOCKET_ROOMS_LOCK = threading.RLock()

def get_py_room_state(room):
    if not room: return None
    import time as _t
    members = list(room.get("members", {}).values())
    return {
        "roomId": room.get("roomId"),
        "playing": bool(room.get("playing")),
        "currentTime": float(room.get("currentTime", 0.0)),
        "playbackRate": float(room.get("playbackRate", 1.0)),
        "updatedAt": int(room.get("updatedAt", 0)),
        "serverTimestamp": int(_t.time() * 1000),
        "hostId": room.get("hostSocketId"),
        "hostProfile": room.get("hostProfile"),
        "controlMode": room.get("controlMode", "host-only"),
        "item": room.get("item"),
        "streamUrl": room.get("streamUrl", ""),
        "members": members
    }

if SOCKETIO_AVAILABLE and socketio:
    @socketio.on('join-room')
    def py_socket_join(payload):
        import time as _t
        from flask import request as req
        sid = getattr(req, 'sid', None)
        if not sid: return
        raw_room = payload.get("roomId") or "GLOBAL" if isinstance(payload, dict) else "GLOBAL"
        room_id = str(raw_room).strip().upper()
        profile = payload.get("profile") if isinstance(payload, dict) else {"id": sid, "name": "Utente", "avatar": ""}
        if not profile: profile = {"id": sid, "name": "Utente", "avatar": ""}
        item = payload.get("item") if isinstance(payload, dict) else None
        stream_url = payload.get("streamUrl", "") if isinstance(payload, dict) else ""
        control_mode = payload.get("controlMode", "host-only") if isinstance(payload, dict) else "host-only"

        join_room(f"room:{room_id}")

        with SOCKET_ROOMS_LOCK:
            room = SOCKET_ROOMS.get(room_id)
            is_host = False
            if not room:
                is_host = True
                room = {
                    "roomId": room_id,
                    "hostSocketId": sid,
                    "hostProfile": profile,
                    "controlMode": control_mode,
                    "playing": False,
                    "currentTime": float(payload.get("currentTime", 0.0) or 0.0) if isinstance(payload, dict) else 0.0,
                    "playbackRate": 1.0,
                    "updatedAt": int(_t.time() * 1000),
                    "item": item,
                    "streamUrl": stream_url,
                    "members": {}
                }
                SOCKET_ROOMS[room_id] = room
            else:
                if not room.get("hostSocketId") or room.get("hostSocketId") not in room.get("members", {}):
                    room["hostSocketId"] = sid
                    room["hostProfile"] = profile
                    is_host = True
                else:
                    is_host = (room.get("hostSocketId") == sid)
                if is_host:
                    if item: room["item"] = item
                    if stream_url: room["streamUrl"] = stream_url

            room["members"][sid] = {
                "socketId": sid,
                "profileId": profile.get("id", sid),
                "name": profile.get("name", "Utente"),
                "avatar": profile.get("avatar", ""),
                "isHost": is_host,
                "ready": True,
                "buffering": False
            }

            state = get_py_room_state(room)

        emit('room-state', state)
        emit('user-joined', {
            "user": room["members"][sid],
            "members": state["members"]
        }, to=f"room:{room_id}", include_self=False)
        emit('members-update', {"members": state["members"]}, to=f"room:{room_id}")

    @socketio.on('player-action')
    def py_socket_action(data):
        import time as _t
        from flask import request as req
        sid = getattr(req, 'sid', None)
        if not sid or not isinstance(data, dict): return
        room_id = str(data.get("roomId", "")).strip().upper()
        with SOCKET_ROOMS_LOCK:
            room = SOCKET_ROOMS.get(room_id)
            if not room: return
            is_host = (sid == room.get("hostSocketId"))
            if room.get("controlMode") == "host-only" and not is_host:
                emit('action-denied', {"reason": "Solo l'host può controllare la riproduzione"})
                return

            action = data.get("action")
            try: cur_time = float(data.get("currentTime", room.get("currentTime", 0.0)))
            except Exception: cur_time = room.get("currentTime", 0.0)

            room["currentTime"] = max(0.0, cur_time)
            if action == "play": room["playing"] = True
            elif action == "pause": room["playing"] = False
            room["playbackRate"] = float(data.get("playbackRate", 1.0) or 1.0)
            room["updatedAt"] = int(_t.time() * 1000)

        emit('player-action', {
            "action": action,
            "currentTime": room["currentTime"],
            "playbackRate": room["playbackRate"],
            "serverTimestamp": int(_t.time() * 1000),
            "by": "host" if is_host else "guest"
        }, to=f"room:{room_id}", include_self=False)

    @socketio.on('sync')
    def py_socket_sync(data):
        import time as _t
        from flask import request as req
        sid = getattr(req, 'sid', None)
        if not sid or not isinstance(data, dict): return
        room_id = str(data.get("roomId", "")).strip().upper()
        with SOCKET_ROOMS_LOCK:
            room = SOCKET_ROOMS.get(room_id)
            if not room: return
            is_host = (sid == room.get("hostSocketId"))
            if room.get("controlMode") == "host-only" and not is_host: return

            try: cur_time = float(data.get("currentTime", room.get("currentTime", 0.0)))
            except Exception: cur_time = room.get("currentTime", 0.0)

            room["currentTime"] = max(0.0, cur_time)
            room["playing"] = bool(data.get("playing"))
            room["playbackRate"] = float(data.get("playbackRate", 1.0) or 1.0)
            room["updatedAt"] = int(_t.time() * 1000)
            if data.get("item"): room["item"] = data["item"]
            if data.get("streamUrl"): room["streamUrl"] = data["streamUrl"]

            resp = {
                "currentTime": room["currentTime"],
                "playing": room["playing"],
                "playbackRate": room["playbackRate"],
                "serverTimestamp": int(_t.time() * 1000),
                "item": room["item"],
                "streamUrl": room["streamUrl"]
            }

        emit('sync', resp, to=f"room:{room_id}", include_self=False)

    @socketio.on('change-episode')
    def py_socket_change_ep(data):
        import time as _t
        from flask import request as req
        sid = getattr(req, 'sid', None)
        if not sid or not isinstance(data, dict): return
        room_id = str(data.get("roomId", "")).strip().upper()
        with SOCKET_ROOMS_LOCK:
            room = SOCKET_ROOMS.get(room_id)
            if not room: return
            is_host = (sid == room.get("hostSocketId"))
            if room.get("controlMode") == "host-only" and not is_host:
                emit('action-denied', {"reason": "Solo l'host può cambiare episodio"})
                return

            room["item"] = data.get("item", room.get("item"))
            room["streamUrl"] = data.get("streamUrl", "")
            room["currentTime"] = 0.0
            room["playing"] = True
            room["updatedAt"] = int(_t.time() * 1000)

            resp = {
                "item": room["item"],
                "streamUrl": room["streamUrl"],
                "currentTime": 0.0,
                "serverTimestamp": int(_t.time() * 1000)
            }

        emit('change-episode', resp, to=f"room:{room_id}", include_self=False)

    @socketio.on('set-control-mode')
    def py_socket_ctrl_mode(data):
        from flask import request as req
        sid = getattr(req, 'sid', None)
        if not sid or not isinstance(data, dict): return
        room_id = str(data.get("roomId", "")).strip().upper()
        with SOCKET_ROOMS_LOCK:
            room = SOCKET_ROOMS.get(room_id)
            if not room or sid != room.get("hostSocketId"): return
            mode = "all" if data.get("controlMode") == "all" else "host-only"
            room["controlMode"] = mode

        emit('control-mode-changed', {"controlMode": mode}, to=f"room:{room_id}")

    @socketio.on('member-status')
    def py_socket_member_status(data):
        from flask import request as req
        sid = getattr(req, 'sid', None)
        if not sid or not isinstance(data, dict): return
        room_id = str(data.get("roomId", "")).strip().upper()
        with SOCKET_ROOMS_LOCK:
            room = SOCKET_ROOMS.get(room_id)
            if not room: return
            member = room.get("members", {}).get(sid)
            if member:
                if "ready" in data: member["ready"] = bool(data["ready"])
                if "buffering" in data: member["buffering"] = bool(data["buffering"])

        emit('member-status-update', {
            "socketId": sid,
            "ready": data.get("ready"),
            "buffering": data.get("buffering")
        }, to=f"room:{room_id}", include_self=False)

    @socketio.on('disconnect')
    def py_socket_disconnect():
        from flask import request as req
        sid = getattr(req, 'sid', None)
        if not sid: return
        with SOCKET_ROOMS_LOCK:
            for room_id, room in list(SOCKET_ROOMS.items()):
                if sid in room.get("members", {}):
                    was_host = (sid == room.get("hostSocketId"))
                    member = room["members"].pop(sid, None)
                    if not room["members"]:
                        SOCKET_ROOMS.pop(room_id, None)
                    else:
                        if was_host:
                            next_sid = next(iter(room["members"]))
                            room["hostSocketId"] = next_sid
                            room["hostProfile"] = room["members"][next_sid]
                            emit('host-changed', {
                                "newHost": {"socketId": next_sid, "profile": room["members"][next_sid]}
                            }, to=f"room:{room_id}")
                        state = get_py_room_state(room)
                        emit('user-left', {
                            "socketId": sid,
                            "name": member.get("name") if member else "Un partecipante",
                            "members": state["members"]
                        }, to=f"room:{room_id}")
                        emit('members-update', {"members": state["members"]}, to=f"room:{room_id}")

def streamingcommunity_item(item):
    if not isinstance(item, dict): return False
    if item.get('provider') == 'guardoseries':
        return bool(re.fullmatch(r'gs-[0-9a-f]+', str(item.get('titleId') or item.get('id') or '')))
    if item.get('provider') and item['provider'] != 'streamingcommunity': return False
    if item.get('source') and not str(item['source']).startswith('StreamingCommunity'): return False
    identifier = str(item.get('series_id') or item.get('titleId') or item.get('id') or '').split('_')[0]
    return identifier.isdigit()

@app.route('/api/history', methods=['GET'])
def get_history():
    profile_id = request.args.get('profile_id')
    profiles_data = load_profiles_data()
    target_prof = get_profile_by_id(profiles_data, profile_id) if profile_id else get_profile_by_id(profiles_data, profiles_data.get("active_profile_id"))
    raw_list = target_prof.get("history", []) if target_prof else load_history_data()

    def parse_ts(item):
        if not isinstance(item, dict): return 0
        ts = item.get('updatedAt')
        if isinstance(ts, (int, float)): return float(ts)
        if isinstance(ts, str):
            try: return float(ts)
            except Exception: pass
        if item.get('updated_at'):
            try:
                import datetime
                dt = datetime.datetime.fromisoformat(item['updated_at'].replace('Z', '+00:00'))
                return dt.timestamp() * 1000
            except Exception: pass
        return 0.0

    raw_list = [item for item in raw_list if streamingcommunity_item(item)]
    raw_list.sort(key=parse_ts, reverse=True)
    return jsonify(raw_list)

@app.route('/api/favorites', methods=['GET'])
def get_favorites():
    profile_id = request.args.get('profile_id')
    profiles_data = load_profiles_data()
    target_prof = get_profile_by_id(profiles_data, profile_id) if profile_id else get_profile_by_id(profiles_data, profiles_data.get("active_profile_id"))
    if target_prof:
        return jsonify({k:v for k,v in target_prof.get("favorites", {}).items() if streamingcommunity_item(v)})
    return jsonify({k:v for k,v in load_favorites_data().items() if streamingcommunity_item(v)})

@app.route('/api/favorites/save', methods=['POST'])
def save_favorites():
    data = request.get_json(silent=True) or {}
    profile_id = request.args.get('profile_id') or (data.get('profile_id') if isinstance(data, dict) else None)
    fav_items = data.get('favorites') if (isinstance(data, dict) and 'favorites' in data) else data
    if isinstance(fav_items, dict) and 'profile_id' in fav_items:
        fav_items = {k: v for k, v in fav_items.items() if k != 'profile_id'}
    fav_items = {k:v for k,v in fav_items.items() if streamingcommunity_item(v)} if isinstance(fav_items,dict) else {}

    profiles_data = load_profiles_data()
    target_prof = get_profile_by_id(profiles_data, profile_id) if profile_id else get_profile_by_id(profiles_data, profiles_data.get("active_profile_id"))
    if target_prof:
        target_prof["favorites"] = fav_items
        save_profiles_data(profiles_data)
    else:
        save_favorites_data(fav_items)
    return jsonify({"success": True})

@app.route('/api/history/save', methods=['POST'])
def save_history_item():
    data = request.get_json(silent=True) or {}
    if 'item' in data and isinstance(data['item'], dict):
        pid = data.get('profile_id')
        data = dict(data['item'])
        if pid:
            data['profile_id'] = pid

    if not streamingcommunity_item(data):
        return jsonify(error='Titolo StreamingCommunity non valido'),400

    item_id = str(data.get('id') or data.get('url') or '').strip()
    if not item_id:
        return jsonify({"error": "ID mancante"}), 400

    title_id = str(data.get('titleId') or '').strip()
    base_target = title_id or (item_id.split('_')[0] if '_' in item_id else item_id)

    # Ensure updatedAt is an integer millisecond timestamp
    now_ts = int(time.time() * 1000)
    data['updatedAt'] = int(data.get('updatedAt') or now_ts)

    def is_same_show_or_item(h):
        if not isinstance(h, dict): return False
        hid = str(h.get('id') or '')
        htid = str(h.get('titleId') or '')
        hurl = str(h.get('url') or '')
        if hid == item_id or (hurl and hurl == data.get('url')):
            return True
        if base_target:
            if htid == base_target or hid == base_target or hid.startswith(base_target + '_'):
                return True
        return False

    profile_id = data.get('profile_id') or request.args.get('profile_id')
    profiles_data = load_profiles_data()
    target_prof = get_profile_by_id(profiles_data, profile_id) if profile_id else get_profile_by_id(profiles_data, profiles_data.get("active_profile_id"))

    if target_prof:
        hist = target_prof.get("history", [])
        hist = [h for h in hist if not is_same_show_or_item(h)]
        hist.insert(0, data)
        target_prof["history"] = hist[:30]
        save_profiles_data(profiles_data)
        # Keep global fallback in sync
        global_hist = [h for h in load_history_data() if not is_same_show_or_item(h)]
        global_hist.insert(0, data)
        save_history_data(global_hist[:30])
        return jsonify({"success": True, "history": target_prof["history"]})

    history = load_history_data()
    history = [h for h in history if not is_same_show_or_item(h)]
    history.insert(0, data)
    history = history[:30]
    save_history_data(history)
    return jsonify({"success": True, "history": history})

@app.route('/api/history/remove', methods=['POST'])
def remove_history_item():
    data = request.get_json(silent=True) or {}
    item_id = str(data.get('id') or data.get('url') or '').strip()
    title_id = str(data.get('titleId') or '').strip()
    profile_id = data.get('profile_id') or request.args.get('profile_id')

    if not item_id and not title_id:
        return jsonify({"error": "ID mancante"}), 400

    base_target = title_id or (item_id.split('_')[0] if '_' in item_id else None)

    def item_matches(h):
        if not isinstance(h, dict): return False
        hid = str(h.get('id') or '')
        htid = str(h.get('titleId') or '')
        hurl = str(h.get('url') or '')
        if item_id and (hid == item_id or htid == item_id or hurl == item_id):
            return True
        if title_id and (hid == title_id or htid == title_id or hurl == title_id):
            return True
        if base_target:
            if hid == base_target or htid == base_target or hid.startswith(base_target + '_'):
                return True
        return False

    # 1. Remove from all profiles in profiles_data
    profiles_data = load_profiles_data()
    changed = False
    for p in profiles_data.get("profiles", []):
        old_len = len(p.get("history", []))
        p["history"] = [h for h in p.get("history", []) if not item_matches(h)]
        if len(p["history"]) != old_len:
            changed = True

    if changed:
        save_profiles_data(profiles_data)

    # 2. ALWAYS remove from global fallback history file
    global_hist = load_history_data()
    new_global_hist = [h for h in global_hist if not item_matches(h)]
    if len(new_global_hist) != len(global_hist):
        save_history_data(new_global_hist)

    target_prof = get_profile_by_id(profiles_data, profile_id) if profile_id else get_profile_by_id(profiles_data, profiles_data.get("active_profile_id"))
    res_list = target_prof.get("history", []) if target_prof else new_global_hist
    return jsonify({"success": True, "history": res_list})

@app.route('/api/history/clear', methods=['POST'])
@app.route('/api/history/clear-all', methods=['POST'])
def clear_history():
    profile_id = request.args.get('profile_id')
    profiles_data = load_profiles_data()
    for p in profiles_data.get("profiles", []):
        if not profile_id or p.get("id") == profile_id:
            p["history"] = []
    save_profiles_data(profiles_data)
    save_history_data([])
    for fpath in [HISTORY_FILE + ".bak", HISTORY_FILE + ".tmp"]:
        if os.path.exists(fpath):
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump([], f)
            except Exception:
                pass
    return jsonify({"success": True})



# -------------------------------------------------------------
# GOOGLE OAUTH 2.0 AUTHENTICATION ENGINE
# -------------------------------------------------------------
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
AUTH_SESSION_FILE = user_data_file("auth.json", "~/.streamingcommunity_auth.json")

def load_auth_session():
    if os.path.exists(AUTH_SESSION_FILE):
        try:
            with open(AUTH_SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_auth_session(user_info):
    try:
        if user_info is None:
            if os.path.exists(AUTH_SESSION_FILE):
                os.remove(AUTH_SESSION_FILE)
        else:
            with open(AUTH_SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(user_info, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving auth session:", e)

@app.route('/api/auth/status', methods=['GET'])
def get_auth_status():
    user = load_auth_session()
    return jsonify({
        "authenticated": bool(user and user.get("email")),
        "user": user
    })

@app.route('/api/auth/google/login', methods=['GET', 'POST'])
def start_google_login():
    import webbrowser
    import secrets
    try:
        redirect_uri = "http://localhost:5555/api/auth/google/callback"

        state = secrets.token_urlsafe(16)
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account"
        }
        oauth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
        
        def open_browser():
            time.sleep(0.15)
            try:
                webbrowser.open(oauth_url)
            except Exception as e:
                print("Error opening browser:", e)

        threading.Thread(target=open_browser, daemon=True).start()

        return jsonify({"success": True, "auth_url": oauth_url, "redirect_uri": redirect_uri})
    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500

@app.route('/api/auth/google/callback', methods=['GET'])
def google_auth_callback():
    error = request.args.get('error')
    if error:
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>Errore Accesso Google</title><meta charset="utf-8"></head>
        <body style="font-family: -apple-system, sans-serif; background: #0f172a; color: #fff; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;">
            <div style="background: #1e293b; border-radius: 16px; padding: 32px; text-align: center; max-width: 420px; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
                <div style="font-size: 48px; margin-bottom: 12px;">⚠️</div>
                <h2 style="color: #ef4444; margin: 0 0 10px;">Accesso Annullato o Non Riuscito</h2>
                <p style="color: #94a3b8; font-size: 14px;">Dettaglio: {html_module.escape(error)}</p>
                <p style="color: #cbd5e1; font-size: 13px; margin-top: 20px;">Puoi chiudere questa scheda e riprovare dall'app.</p>
            </div>
        </body>
        </html>
        """, 400

    code = request.args.get('code')
    if not code:
        return "Codice di autorizzazione non fornito.", 400

    try:
        import urllib.request
        redirect_uri = "http://localhost:5555/api/auth/google/callback"

        token_payload = urllib.parse.urlencode({
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }).encode('utf-8')

        token_req = urllib.request.Request(
            'https://oauth2.googleapis.com/token',
            data=token_payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'StreamingCommunityApp/1.0'}
        )
        with urllib.request.urlopen(token_req, timeout=15) as token_res:
            token_data = json.loads(token_res.read().decode('utf-8'))

        access_token = token_data.get('access_token')
        if not access_token:
            return "Impossibile ottenere l'access token da Google.", 400

        userinfo_req = urllib.request.Request(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {access_token}', 'User-Agent': 'StreamingCommunityApp/1.0'}
        )
        with urllib.request.urlopen(userinfo_req, timeout=15) as userinfo_res:
            uinfo = json.loads(userinfo_res.read().decode('utf-8'))

        user_name = uinfo.get('name') or uinfo.get('given_name') or uinfo.get('email', '').split('@')[0]
        user_email = uinfo.get('email', '')
        user_avatar = uinfo.get('picture') or f"https://ui-avatars.com/api/?name={urllib.parse.quote(user_name)}&background=6366f1&color=fff&size=128"

        user_profile = {
            'id': uinfo.get('sub', str(time.time())),
            'name': user_name,
            'email': user_email,
            'avatar': user_avatar,
            'logged_in_at': time.time(),
            'provider': 'google'
        }
        save_auth_session(user_profile)

        return f"""
        <!DOCTYPE html>
        <html lang="it">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Accesso StreamingCommunity Completato</title>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    background: radial-gradient(circle at top center, #1e1b4b 0%, #09090b 100%);
                    color: #f8fafc;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    overflow: hidden;
                }}
                .card {{
                    background: rgba(30, 41, 59, 0.7);
                    backdrop-filter: blur(20px);
                    -webkit-backdrop-filter: blur(20px);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 24px;
                    padding: 40px 32px;
                    text-align: center;
                    max-width: 440px;
                    width: 90%;
                    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7), 0 0 40px rgba(99, 102, 241, 0.2);
                    animation: popIn 0.5s cubic-bezier(0.16, 1, 0.3, 1);
                }}
                @keyframes popIn {{
                    from {{ opacity: 0; transform: scale(0.9) translateY(20px); }}
                    to {{ opacity: 1; transform: scale(1) translateY(0); }}
                }}
                .avatar {{
                    width: 80px;
                    height: 80px;
                    border-radius: 50%;
                    border: 3px solid #6366f1;
                    box-shadow: 0 0 20px rgba(99, 102, 241, 0.5);
                    margin: 0 auto 16px;
                    object-fit: cover;
                }}
                .badge {{
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    background: rgba(34, 197, 94, 0.15);
                    color: #4ade80;
                    border: 1px solid rgba(34, 197, 94, 0.3);
                    padding: 6px 14px;
                    border-radius: 9999px;
                    font-size: 13px;
                    font-weight: 600;
                    margin-bottom: 16px;
                }}
                h1 {{
                    font-size: 22px;
                    font-weight: 800;
                    margin: 0 0 8px;
                    color: #ffffff;
                }}
                p {{
                    color: #94a3b8;
                    font-size: 14px;
                    margin: 0 0 24px;
                    line-height: 1.5;
                }}
                .user-info {{
                    background: rgba(15, 23, 42, 0.6);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 12px;
                    padding: 12px;
                    margin-bottom: 24px;
                }}
                .user-name {{
                    font-weight: 700;
                    font-size: 15px;
                    color: #f1f5f9;
                }}
                .user-email {{
                    font-size: 13px;
                    color: #64748b;
                }}
                .btn {{
                    background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
                    color: white;
                    border: none;
                    padding: 12px 24px;
                    border-radius: 12px;
                    font-weight: 600;
                    font-size: 14px;
                    cursor: pointer;
                    text-decoration: none;
                    display: inline-block;
                    box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4);
                    transition: transform 0.2s;
                }}
                .btn:hover {{
                    transform: translateY(-2px);
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <img class="avatar" src="{html_module.escape(user_avatar)}" alt="Avatar">
                <div class="badge">
                    <span>✓</span> Accesso Eseguito
                </div>
                <h1>Benvenuto, {html_module.escape(user_name)}!</h1>
                <div class="user-info">
                    <div class="user-name">{html_module.escape(user_name)}</div>
                    <div class="user-email">{html_module.escape(user_email)}</div>
                </div>
                <p>Il tuo account Google è stato collegato a StreamingCommunity. Puoi chiudere questa scheda e tornare all'app!</p>
                <button class="btn" onclick="window.close()">Chiudi Scheda</button>
            </div>
            <script>
                setTimeout(() => {{
                    try {{ window.close(); }} catch(e) {{}}
                }}, 2500);
            </script>
        </body>
        </html>
        """
    except Exception as ex:
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>Errore Autenticazione</title><meta charset="utf-8"></head>
        <body style="font-family: -apple-system, sans-serif; background: #0f172a; color: #fff; padding: 40px; text-align: center;">
            <h2 style="color: #ef4444;">Errore durante lo scambio credenziali con Google</h2>
            <p style="color: #94a3b8;">{html_module.escape(str(ex))}</p>
        </body>
        </html>
        """, 500

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    save_auth_session(None)
    return jsonify({"success": True})


# -------------------------------------------------------------
# CAST, SMART TV & WIRELESS SCREEN ENGINE (MIRACAST / DLNA / CHROMECAST)
# -------------------------------------------------------------
import socket

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

CURRENT_CAST_STATE = {
    "title": "",
    "url": "",
    "time": 0,
    "isPlaying": False
}

@app.route('/api/cast/info', methods=['GET'])
def get_cast_info():
    local_ip = get_local_ip()
    port = 5555
    tv_url = f"http://{local_ip}:{port}/tv"
    return jsonify({
        "local_ip": local_ip,
        "port": port,
        "tv_url": tv_url,
        "current": CURRENT_CAST_STATE,
        "supported": ["Chromecast", "Miracast Receiver", "Samsung Smart View", "LG Screen Share", "Fire TV", "DLNA"]
    })

@app.route('/api/cast/update', methods=['POST'])
def update_cast_state():
    global CURRENT_CAST_STATE
    data = request.get_json() or {}
    CURRENT_CAST_STATE.update(data)
    return jsonify({"success": True, "state": CURRENT_CAST_STATE})

@app.route('/tv', methods=['GET', 'HEAD', 'OPTIONS'])
@app.route('/tv/', methods=['GET', 'HEAD', 'OPTIONS'])
def tv_player_page():
    return render_template('tv.html')





# -------------------------------------------------------------
# APP ENTRY POINT
# -------------------------------------------------------------
def find_free_port(start_port=5555):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', start_port))
        s.close()
        return start_port
    except OSError:
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        p = s.getsockname()[1]
        s.close()
        return p

def run_flask_on_port(port_num):
    engine.download_proxy_base = f'http://127.0.0.1:{int(port_num)}'
    app.run(host='0.0.0.0', port=port_num, debug=False, use_reloader=False)

if __name__ == '__main__':
    import webview

    # Handle launch via custom macOS URL Scheme (streamingcommunity://download?url=...&title=...)
    for arg in sys.argv:
        if arg.startswith('streamingcommunity://') or arg.startswith('scdown://'):
            try:
                parsed = urllib.parse.urlparse(arg)
                qs = urllib.parse.parse_qs(parsed.query)
                dl_url = qs.get('url', [''])[0]
                dl_title = qs.get('title', ['Media Download'])[0]
                if dl_url:
                    engine.start_download(dl_url, custom_title=dl_title)
            except Exception as e:
                print("Error handling launch URL:", e)

    target_port = find_free_port(5555)
    t = threading.Thread(target=run_flask_on_port, args=(target_port,), daemon=True)
    t.start()
    time.sleep(1)

    webview.create_window(
        title='Netflix',
        url=f'http://127.0.0.1:{target_port}',
        width=1380,
        height=880,
        resizable=True,
        fullscreen=False,
        min_size=(960, 600),
        background_color='#09090b',
        text_select=True,
        zoomable=True
    )
    webview.start(debug=False)
