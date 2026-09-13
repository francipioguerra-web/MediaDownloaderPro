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
import requests
from curl_cffi import requests as cffi_requests, curl
from flask import Flask, render_template, request, jsonify, Response, redirect, make_response

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
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
else:
    app = Flask(__name__, template_folder='templates', static_folder='static')

app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

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

DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# -------------------------------------------------------------
# CORE ENGINE: HOME CATALOG & STREAMINGCOMMUNITY DOWNLOADER
# -------------------------------------------------------------
class Engine:
    def __init__(self):
        self.session = cffi_requests.Session(impersonate='chrome120')
        self.candidate_sc_domains = [
            "https://streamingcommunityz.style",
            "https://streamingcommunityz.miami",
            "https://streamingcommunityz.luxe",
            "https://streamingcommunityz.boats",
            "https://streamingcommunityz.hair",
            "https://streamingcommunityz.bio",
            "https://streamingcommunity.computer"
        ]
        self._cached_active_domain = None
        self.downloads = {}
        self.canceled_downloads = set()
        self.dates_cache_file = os.path.expanduser('~/.streamingcommunity_dates_cache.json')
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
            is_valid = st == 200 and ('streamingcommunity' in body.lower() or 'inertia' in body.lower() or 'data-page' in body.lower())
            if is_valid:
                p_eff = urllib.parse.urlparse(eff_str)
                return f"{p_eff.scheme}://{p_eff.netloc}"
        except Exception:
            pass
        return None

    def safe_get(self, url, headers=None, timeout=6):
        try:
            r = self.session.get(url, headers=headers, timeout=timeout)
            if r.status_code in (200, 301, 302, 304):
                return r
        except Exception:
            pass
            
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.netloc
            ips = self._resolve_doh_ips(hostname)
            
            c = curl.Curl()
            c.impersonate('chrome120')
            c.setopt(curl.CurlOpt.URL, url)
            if ips:
                c.setopt(curl.CurlOpt.RESOLVE, [f'{hostname}:443:{ip}' for ip in ips] + [f'{hostname}:80:{ip}' for ip in ips])
            c.setopt(curl.CurlOpt.FOLLOWLOCATION, 1)
            c.setopt(curl.CurlOpt.ACCEPT_ENCODING, b'')
            c.setopt(curl.CurlOpt.TIMEOUT, timeout)
            if headers:
                hdrs = [f'{k}: {v}'.encode() for k, v in headers.items()]
                c.setopt(curl.CurlOpt.HTTPHEADER, hdrs)
                
            buf = io.BytesIO()
            c.setopt(curl.CurlOpt.WRITEDATA, buf)
            c.perform()
            st = c.getinfo(curl.CurlInfo.RESPONSE_CODE)
            body = buf.getvalue().decode('utf-8', errors='ignore')
            c.close()
            
            class DummyResponse:
                def __init__(self, status_code, text):
                    self.status_code = status_code
                    self.text = text
                    
            return DummyResponse(st, body)
        except Exception as e:
            class DummyErrorResponse:
                def __init__(self, err):
                    self.status_code = 500
                    self.text = str(err)
            return DummyErrorResponse(e)

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

    def get_active_sc_domain(self, target_url=None):
        if target_url and target_url.startswith('http'):
            v = self._verify_single_url(target_url)
            if v:
                self._cached_active_domain = v
                return v

        if self._cached_active_domain:
            return self._cached_active_domain

        for d in self.candidate_sc_domains:
            v = self._verify_single_url(d)
            if v:
                self._cached_active_domain = v
                return v

        online_domain = self.perform_online_domain_search()
        if online_domain:
            self._cached_active_domain = online_domain
            return online_domain

        return self.candidate_sc_domains[0]

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
                    u = f"{cdn_url}/images/{fn}"
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
            
        best_cover = background or cover or cover_mobile or poster
        best_poster = poster or cover or background
        return best_poster, best_cover

    def get_home_catalog(self):
        try:
            active_domain = self.get_active_sc_domain()
            cdn_url = f"https://cdn.{active_domain.replace('https://', '')}"
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

                    # Resolve debut release dates concurrently for featured and top titles
                    try:
                        all_items = []
                        if clean_featured:
                            all_items.append(clean_featured)
                        for sl in clean_sliders:
                            for it in sl.get('titles', []):
                                all_items.append(it)

                        uncached = [it for it in all_items if str(it['id']) not in self.dates_cache][:30]
                        if uncached:
                            def _fetch_item_rel(item):
                                try:
                                    det = self.get_title_details(item['id'], item.get('slug', ''))
                                    if isinstance(det, dict) and det.get('release_date'):
                                        rd = str(det['release_date']).strip()
                                        if rd:
                                            return str(item['id']), rd
                                except Exception:
                                    pass
                                return str(item['id']), None

                            with ThreadPoolExecutor(max_workers=8) as executor:
                                results = dict(executor.map(_fetch_item_rel, uncached))

                            updated_any = False
                            for str_id, rd in results.items():
                                if rd:
                                    self.dates_cache[str_id] = rd
                                    updated_any = True
                            if updated_any:
                                self._save_dates_cache()
                                for it in all_items:
                                    str_id = str(it['id'])
                                    if str_id in self.dates_cache:
                                        it['release_date'] = self.dates_cache[str_id]
                    except Exception as ex_pool:
                        print("Background date enrichment notice:", ex_pool)

                    return {
                        "success": True,
                        "domain": active_domain,
                        "featured": clean_featured,
                        "genres": props.get('genres') or [],
                        "sliders": clean_sliders
                    }
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

    def search_streamingcommunity(self, query):
        try:
            active_domain = self.get_active_sc_domain()
            headers = {
                'X-Inertia': 'true',
                'X-Requested-With': 'XMLHttpRequest'
            }

            r1 = self.session.get(f"{active_domain}/it/search", timeout=5)
            match = re.search(r'data-page=\"(.*?)\"', r1.text) or re.search(r"data-page='(.*?)'", r1.text)
            if match:
                version = json.loads(html_module.unescape(match.group(1))).get('version')
                if version:
                    headers['X-Inertia-Version'] = version

            r2 = self.session.get(f"{active_domain}/it/search?q={urllib.parse.quote(query)}", headers=headers, timeout=6)
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
                            "id": t.get('id'),
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
                            "watch_url": f"{active_domain}/it/watch/{t.get('id')}"
                        })
                return results
        except Exception as ex:
            print("SC search error:", ex)
        return []

    def search_animeworld(self, query):
        try:
            url = f"https://www.animeworld.ac/filter?keyword={urllib.parse.quote(query)}"
            r = self.session.get(url, timeout=5)
            if r.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, 'html.parser')
                results = []
                for el in soup.select('.film-list .item, .items .item, .poster')[:12]:
                    a = el.select_one('a.name, a.poster, a')
                    img = el.select_one('img')
                    if a and img:
                        title = a.get_text(strip=True) or a.get('title') or img.get('alt')
                        href = a.get('href') or ''
                        src = img.get('src') or img.get('data-src') or ''
                        if title and href:
                            slug_id = href.strip('/').split('/')[-1]
                            results.append({
                                "id": f"aw-{slug_id}",
                                "name": title,
                                "type": "tv",
                                "slug": slug_id,
                                "release_date": "Anime ITA",
                                "poster": src if src.startswith('http') else f"https://www.animeworld.ac{src}",
                                "cover": src if src.startswith('http') else f"https://www.animeworld.ac{src}",
                                "plot": "Anime doppiato o sottotitolato in italiano disponibile su AnimeWorld.",
                                "source": "AnimeWorld",
                                "lang": "ita",
                                "flag": "🇮🇹",
                                "watch_url": f"https://www.animeworld.ac{href}"
                            })
                return results
        except Exception as ex:
            print("AW search error:", ex)
        return []

    def search_international_tmdb(self, query):
        try:
            url = f"https://api.themoviedb.org/3/search/multi?api_key=4e44d9029b1270a757cddc766a1bcb63&query={urllib.parse.quote(query)}&language=en-US"
            r = self.session.get(url, timeout=5)
            if r.status_code == 200:
                raw_results = r.json().get('results', [])
                results = []
                for t in raw_results:
                    m_type = t.get('media_type')
                    if m_type not in ['movie', 'tv']: continue
                    title = t.get('title') or t.get('name')
                    poster_path = t.get('poster_path')
                    poster_url = f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else ""
                    backdrop_path = t.get('backdrop_path')
                    cover_url = f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else poster_url
                    t_id = t.get('id')
                    embed_url = f"https://vidsrc.xyz/embed/movie/{t_id}" if m_type == 'movie' else f"https://vidsrc.xyz/embed/tv/{t_id}"
                    results.append({
                        "id": f"tmdb-{t_id}",
                        "name": title,
                        "type": m_type,
                        "slug": str(t_id),
                        "release_date": (t.get('release_date') or t.get('first_air_date') or '')[:4],
                        "poster": poster_url,
                        "cover": cover_url,
                        "plot": t.get('overview', ''),
                        "source": "LookMovie / VidSrc (ENG)",
                        "lang": "eng",
                        "flag": "🇬🇧",
                        "watch_url": embed_url
                    })
                return results
        except Exception as ex:
            print("TMDB search error:", ex)
        return []

    def get_genre_catalog(self, genre='', media_type='all', sort='popular', page=1):
        sort_key = 'views' if sort == 'popular' else (sort or 'release_date')
        return self.get_archive_catalog(media_type=media_type, genres=[genre] if genre else None, sort=sort_key, page=page)

    def get_archive_catalog(self, media_type='all', genres=None, countries=None, year=None, score=None, views=None, service=None, quality=None, age=None, sort='release_date', search=None, page=1):
        try:
            active_domain = self.get_active_sc_domain()
            cdn_url = f"https://cdn.{active_domain.replace('https://', '')}"
            query_parts = []

            # Type: 'movie', 'tv'
            if media_type and str(media_type).lower() not in ('all', '', 'null', 'tutto', 'tutti'):
                query_parts.append(f"type={urllib.parse.quote(str(media_type).lower())}")

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
        return {"success": True, "titles": [], "totalCount": 0, "page": 1, "hasMore": False}

    def get_archive_metadata(self):
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
        return {"success": True, "genres": [], "countries": []}

    def search_catalog(self, query):
        try:
            return self.search_catalog_multi(query)
        except Exception as ex:
            print("Search catalog error:", ex)
            return []

    def search_catalog_multi(self, query):
        try:
            import concurrent.futures
            active_domain = self.get_active_sc_domain()

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                f_sc = executor.submit(self.search_streamingcommunity, query)
                f_aw = executor.submit(self.search_animeworld, query)
                f_tmdb = executor.submit(self.search_international_tmdb, query)

                res_sc = f_sc.result() or []
                res_aw = f_aw.result() or []
                res_tmdb = f_tmdb.result() or []

            def clean_t(txt):
                return re.sub(r'[^a-zA-Z0-9]', '', str(txt).lower())

            # Cross-reference matches between Italian & English sources
            for sc_item in res_sc:
                c_sc = clean_t(sc_item.get('name', ''))
                sc_item['alt_sources'] = []
                for tmdb_item in res_tmdb:
                    c_tmdb = clean_t(tmdb_item.get('name', ''))
                    if c_sc and (c_sc == c_tmdb or c_sc in c_tmdb or c_tmdb in c_sc):
                        sc_item['alt_sources'].append({
                            "id": tmdb_item.get('id'),
                            "name": tmdb_item.get('name'),
                            "type": tmdb_item.get('type'),
                            "source": "LookMovie / VidSrc",
                            "lang": "eng",
                            "flag": "🇬🇧",
                            "watch_url": tmdb_item.get('watch_url')
                        })
                        sc_item['has_multi_lang'] = True
                        break

            for tmdb_item in res_tmdb:
                c_tmdb = clean_t(tmdb_item.get('name', ''))
                tmdb_item['alt_sources'] = []
                for sc_item in res_sc:
                    c_sc = clean_t(sc_item.get('name', ''))
                    if c_tmdb and (c_sc == c_tmdb or c_sc in c_tmdb or c_tmdb in c_sc):
                        tmdb_item['alt_sources'].append({
                            "id": sc_item.get('id'),
                            "name": sc_item.get('name'),
                            "type": sc_item.get('type'),
                            "source": "StreamingCommunity",
                            "lang": "ita",
                            "flag": "🇮🇹",
                            "watch_url": sc_item.get('watch_url')
                        })
                        tmdb_item['has_multi_lang'] = True
                        break

            # Prioritize StreamingCommunity, then AnimeWorld, then International
            combined = res_sc + res_aw + res_tmdb
            return {"domain": active_domain, "results": combined}
        except Exception as ex:
            return {"error": f"Errore ricerca: {str(ex)[:100]}"}

    def get_title_details(self, title_id, slug=""):
        str_id = str(title_id)
        if str_id.startswith('tmdb-'):
            return self._get_tmdb_title_details(str_id.replace('tmdb-', ''))
        elif str_id.startswith('aw-'):
            return self._get_aw_title_details(str_id.replace('aw-', ''))

        try:
            active_domain = self.get_active_sc_domain()
            url = f"{active_domain}/it/titles/{title_id}-{slug}" if slug else f"{active_domain}/it/watch/{title_id}"
            res = self.safe_get(url, timeout=6)
            if res.status_code != 200:
                res = self.safe_get(f"{active_domain}/it/watch/{title_id}", timeout=6)
            if res.status_code != 200:
                return {"error": "Impossibile caricare il titolo."}

            match = re.search(r'data-page=\"(.*?)\"', res.text) or re.search(r"data-page='(.*?)'", res.text)
            if not match:
                return {"error": "Dati titolo non trovati."}

            data = json.loads(html_module.unescape(match.group(1)))
            props = data.get('props') or {}
            cdn_url = props.get('cdn_url') or f"https://cdn.{active_domain.replace('https://', '')}"

            media_info = props.get('title') or props.get('media') or props.get('loadedTitle') or {}
            if not media_info:
                return {"error": "Informazioni multimediali non trovate."}

            found_slug = media_info.get('slug') or slug or media_info.get('name', '').lower().replace(' ', '-').replace(':', '')

            images = (media_info.get('images') or []) if isinstance(media_info, dict) else []
            if not images and found_slug:
                try:
                    t_url = f"{active_domain}/it/titles/{title_id}-{found_slug}"
                    r_t = self.safe_get(t_url, timeout=5)
                    m_t = re.search(r'data-page=\"(.*?)\"', r_t.text) or re.search(r"data-page='(.*?)'", r_t.text)
                    if m_t:
                        data_t = json.loads(html_module.unescape(m_t.group(1)))
                        props_t = data_t.get('props') or {}
                        t_media = props_t.get('title') or {}
                        if isinstance(t_media, dict) and t_media.get('images'):
                            media_info = t_media
                except Exception:
                    pass

            poster_img, cover_img = self.extract_sc_images(media_info, cdn_url)
            seasons = (media_info.get('seasons') or []) if isinstance(media_info, dict) else []
            seasons_list = [s for s in seasons if isinstance(s, dict)]
            loaded_season = props.get('loadedSeason') or {}
            if not isinstance(loaded_season, dict): loaded_season = {}

            title_name = media_info.get('name') or media_info.get('title') or 'Titolo Streaming'

            episodes_list = []
            episodes_src = (loaded_season.get('episodes') or []) if isinstance(loaded_season, dict) else []
            if not episodes_src and props.get('episode'):
                episodes_src = [props.get('episode')]

            for ep in episodes_src:
                if isinstance(ep, dict):
                    ep_img = None
                    for img in (ep.get('images') or []):
                        if isinstance(img, dict) and img.get('filename'):
                            ep_img = f"{cdn_url}/images/{img.get('filename')}"
                            break
                    episodes_list.append({
                        "id": ep.get('id'),
                        "number": ep.get('number'),
                        "name": ep.get('name'),
                        "plot": ep.get('plot', ''),
                        "duration": ep.get('duration'),
                        "image": ep_img,
                        "watch_url": f"{active_domain}/it/watch/{title_id}?e={ep.get('id')}"
                    })

            has_dub_ita = bool(media_info.get('dub_ita', 1))
            has_audio_orig = bool(media_info.get('audio_orig', 1))
            has_sub_ita = bool(media_info.get('sub_ita', 0))
            tmdb_id = media_info.get('tmdb_id')
            imdb_id = media_info.get('imdb_id')
            m_type = media_info.get('type', 'movie')

            cast_list = []
            if tmdb_id:
                try:
                    tmdb_mtype = 'tv' if m_type == 'tv' else 'movie'
                    tmdb_u = f"https://api.themoviedb.org/3/{tmdb_mtype}/{tmdb_id}?api_key=4e44d9029b1270a757cddc766a1bcb63&language=it-IT&append_to_response=credits"
                    r_tmdb = self.safe_get(tmdb_u, timeout=3)
                    if r_tmdb and r_tmdb.status_code == 200:
                        tmdb_json = r_tmdb.json()
                        if tmdb_json.get('backdrop_path'):
                            cover_img = f"https://image.tmdb.org/t/p/original{tmdb_json.get('backdrop_path')}"
                        raw_cast = (tmdb_json.get('credits') or {}).get('cast') or []
                        for actor in raw_cast[:20]:
                            p_path = actor.get('profile_path')
                            cast_list.append({
                                "name": actor.get('name', ''),
                                "character": actor.get('character', '') or 'Ruolo sconosciuto',
                                "image": f"https://image.tmdb.org/t/p/w185{p_path}" if p_path else ""
                            })
                except Exception:
                    pass

            if not cast_list and media_info.get('main_actors'):
                for act in (media_info.get('main_actors') or [])[:15]:
                    if isinstance(act, dict) and act.get('name'):
                        cast_list.append({
                            "name": act.get('name', ''),
                            "character": act.get('character', '') or (act.get('pivot') or {}).get('job', '') or 'Cast',
                            "image": ""
                        })

            alt_sources = []
            if tmdb_id:
                eng_watch_url = f"https://vidsrc.xyz/embed/movie/{tmdb_id}" if m_type == 'movie' else f"https://vidsrc.xyz/embed/tv/{tmdb_id}"
                alt_sources.append({
                    "id": f"tmdb-{tmdb_id}",
                    "name": title_name,
                    "type": m_type,
                    "source": "LookMovie / VidSrc",
                    "lang": "eng",
                    "flag": "🇬🇧",
                    "watch_url": eng_watch_url
                })

            t_genres = []
            for tg in (media_info.get('genres') or []):
                if isinstance(tg, dict):
                    g_name = tg.get('name')
                    for tr in (tg.get('translations') or []):
                        if isinstance(tr, dict) and tr.get('key') == 'name' and tr.get('value'):
                            g_name = tr.get('value')
                            break
                    if g_name:
                        t_genres.append(g_name)

            final_rel = str(media_info.get('release_date') or media_info.get('year') or '').strip()
            if final_rel and final_rel != '2024':
                str_tid = str(title_id)
                if self.dates_cache.get(str_tid) != final_rel:
                    self.dates_cache[str_tid] = final_rel
                    self._save_dates_cache()

            return {
                "domain": active_domain,
                "id": title_id,
                "slug": found_slug,
                "name": title_name,
                "type": m_type,
                "plot": media_info.get('plot', ''),
                "release_date": final_rel,
                "score": media_info.get('score') or media_info.get('vote_average') or '',
                "runtime": media_info.get('runtime') or '',
                "genres": t_genres,
                "poster": poster_img,
                "cover": cover_img,
                "source": "StreamingCommunity",
                "lang": "ita",
                "flag": "🇮🇹",
                "dub_ita": has_dub_ita,
                "audio_orig": has_audio_orig,
                "sub_ita": has_sub_ita,
                "tmdb_id": tmdb_id,
                "imdb_id": imdb_id,
                "alt_sources": alt_sources,
                "audio_options": [
                    {"id": "ita", "name": "Italiano (Doppiato)", "flag": "🇮🇹", "available": has_dub_ita, "watch_url": f"{active_domain}/it/watch/{title_id}"},
                    {"id": "orig", "name": "Originale (ENG)", "flag": "🇬🇧", "available": has_audio_orig, "watch_url": f"{active_domain}/it/watch/{title_id}?audio=orig"}
                ],
                "sub_options": [
                    {"id": "none", "name": "Disattivati", "flag": "🚫", "available": True},
                    {"id": "ita", "name": "Italiano", "flag": "🇮🇹", "available": has_sub_ita}
                ],
                "seasons": seasons_list,
                "seasons_count": len(seasons),
                "current_season": loaded_season.get('number', 1),
                "episodes": episodes_list,
                "cast": cast_list
            }
        except Exception as ex:
            return {"error": f"Errore caricamento dettagli: {str(ex)[:100]}"}

    def _get_tmdb_title_details(self, tmdb_id):
        try:
            # Try movie first, then tv
            for m_type in ['movie', 'tv']:
                url = f"https://api.themoviedb.org/3/{m_type}/{tmdb_id}?api_key=4e44d9029b1270a757cddc766a1bcb63&language=it-IT"
                r = self.session.get(url, timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    name = d.get('title') or d.get('name')
                    plot = d.get('overview') or 'Nessuna trama disponibile in italiano.'
                    poster = f"https://image.tmdb.org/t/p/w342{d.get('poster_path')}" if d.get('poster_path') else ''
                    cover = f"https://image.tmdb.org/t/p/original{d.get('backdrop_path')}" if d.get('backdrop_path') else poster
                    
                    episodes = []
                    seasons_count = len(d.get('seasons', [])) if m_type == 'tv' else 0
                    if m_type == 'tv' and seasons_count > 0:
                        s_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/1?api_key=4e44d9029b1270a757cddc766a1bcb63&language=it-IT"
                        sr = self.session.get(s_url, timeout=4)
                        if sr.status_code == 200:
                            for ep in sr.json().get('episodes', []):
                                ep_num = ep.get('episode_number')
                                still_path = ep.get('still_path')
                                ep_img = f"https://image.tmdb.org/t/p/w342{still_path}" if still_path else None
                                episodes.append({
                                    "id": f"{tmdb_id}-1-{ep_num}",
                                    "number": ep_num,
                                    "name": ep.get('name') or f"Episodio {ep_num}",
                                    "plot": ep.get('overview') or '',
                                    "duration": ep.get('runtime') or 45,
                                    "image": ep_img,
                                    "watch_url": f"https://vidsrc.xyz/embed/tv/{tmdb_id}/1-{ep_num}"
                                })

                    return {
                        "id": f"tmdb-{tmdb_id}",
                        "name": name,
                        "type": m_type,
                        "slug": str(tmdb_id),
                        "plot": plot,
                        "poster": poster,
                        "cover": cover,
                        "source": "LookMovie / VidSrc (ENG)",
                        "lang": "eng",
                        "flag": "🇬🇧",
                        "seasons_count": seasons_count,
                        "episodes": episodes,
                        "watch_url": f"https://vidsrc.xyz/embed/movie/{tmdb_id}" if m_type == 'movie' else f"https://vidsrc.xyz/embed/tv/{tmdb_id}"
                    }
        except Exception as ex:
            print("TMDB details error:", ex)
        return {"error": "Dettagli internazionali non trovati."}

    def _get_aw_title_details(self, slug):
        try:
            url = f"https://www.animeworld.ac/play/{slug}"
            r = self.session.get(url, timeout=5)
            if r.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, 'html.parser')
                title_el = soup.select_one('.title, h1.name, .info .name')
                title_name = title_el.get_text(strip=True) if title_el else slug
                plot_el = soup.select_one('.desc, .story, .plot')
                plot = plot_el.get_text(strip=True) if plot_el else 'Anime disponibile su AnimeWorld.'
                img_el = soup.select_one('.poster img, .thumb img, .thumb')
                poster = img_el.get('src') if img_el else ''
                if poster and not poster.startswith('http'):
                    poster = f"https://www.animeworld.ac{poster}"

                episodes = []
                for idx, ep_a in enumerate(soup.select('.episodes li a, .server-episodes a')[:50], 1):
                    ep_href = ep_a.get('href')
                    ep_name = ep_a.get_text(strip=True) or f"Episodio {idx}"
                    if ep_href:
                        ep_watch = ep_href if ep_href.startswith('http') else f"https://www.animeworld.ac{ep_href}"
                        episodes.append({
                            "id": f"aw-{slug}-{idx}",
                            "number": idx,
                            "name": ep_name,
                            "plot": "Episodio AnimeWorld",
                            "duration": 24,
                            "watch_url": ep_watch
                        })

                return {
                    "id": f"aw-{slug}",
                    "name": title_name,
                    "type": "tv",
                    "slug": slug,
                    "plot": plot,
                    "poster": poster,
                    "cover": poster,
                    "source": "AnimeWorld",
                    "lang": "ita",
                    "flag": "🇮🇹",
                    "seasons_count": 1,
                    "episodes": episodes,
                    "watch_url": url
                }
        except Exception as ex:
            print("AW details error:", ex)
        return {"error": "Dettagli AnimeWorld non trovati."}

    def get_season_episodes(self, title_id, slug, season_number):
        str_id = str(title_id)
        if str_id.startswith('tmdb-'):
            tmdb_id = str_id.replace('tmdb-', '')
            try:
                s_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_number}?api_key=4e44d9029b1270a757cddc766a1bcb63&language=it-IT"
                sr = self.session.get(s_url, timeout=5)
                if sr.status_code == 200:
                    episodes = []
                    for ep in sr.json().get('episodes', []):
                        ep_num = ep.get('episode_number')
                        still_path = ep.get('still_path')
                        ep_img = f"https://image.tmdb.org/t/p/w342{still_path}" if still_path else None
                        episodes.append({
                            "id": f"{tmdb_id}-{season_number}-{ep_num}",
                            "number": ep_num,
                            "name": ep.get('name') or f"Episodio {ep_num}",
                            "plot": ep.get('overview') or '',
                            "duration": ep.get('runtime') or 45,
                            "image": ep_img,
                            "watch_url": f"https://vidsrc.xyz/embed/tv/{tmdb_id}/{season_number}-{ep_num}"
                        })
                    return {"season_number": season_number, "episodes": episodes}
            except Exception as ex:
                print("TMDB season fetch error:", ex)
            return {"season_number": season_number, "episodes": []}

        try:
            active_domain = self.get_active_sc_domain()
            cdn_url = f"https://cdn.{active_domain.replace('https://', '')}"
            headers = {
                'X-Inertia': 'true',
                'X-Requested-With': 'XMLHttpRequest'
            }

            base_path = f"/it/titles/{title_id}-{slug}" if slug else f"/it/titles/{title_id}"
            r1 = self.session.get(f"{active_domain}{base_path}", timeout=5)
            match = re.search(r'data-page=\"(.*?)\"', r1.text) or re.search(r"data-page='(.*?)'", r1.text)
            if match:
                version = json.loads(html_module.unescape(match.group(1))).get('version')
                if version:
                    headers['X-Inertia-Version'] = version

            season_url = f"{active_domain}{base_path}/season-{season_number}"
            r2 = self.session.get(season_url, headers=headers, timeout=6)
            if r2.status_code == 200:
                data = r2.json()
                ls = data.get('props', {}).get('loadedSeason', {})
                episodes = []
                for ep in ls.get('episodes', []):
                    ep_img = None
                    for img in (ep.get('images') or []):
                        if isinstance(img, dict) and img.get('filename'):
                            ep_img = f"{cdn_url}/images/{img.get('filename')}"
                            break
                    episodes.append({
                        "id": ep.get('id'),
                        "number": ep.get('number'),
                        "name": ep.get('name'),
                        "plot": ep.get('plot', ''),
                        "duration": ep.get('duration'),
                        "image": ep_img,
                        "watch_url": f"{active_domain}/it/watch/{title_id}?e={ep.get('id')}"
                    })
                return {"season_number": season_number, "episodes": episodes}
        except Exception as ex:
            return {"error": f"Errore caricamento stagione: {str(ex)[:100]}"}
    def _build_vix_m3u8_url(self, playlist_url, token, expires, iframe_src=None, audio_orig=False, sub_ita=False, extra_params=None):
        parsed = urllib.parse.urlparse(playlist_url)
        path = parsed.path
        if not path.endswith('.m3u8'):
            path = path + '.m3u8'
        
        params = urllib.parse.parse_qs(parsed.query)
        params['token'] = [token]
        params['expires'] = [expires]

        # Extract parameters from iframe_src if available (e.g. canPlayFHD -> h=1, scz -> scz=1, lang)
        if iframe_src:
            iframe_qs = urllib.parse.parse_qs(urllib.parse.urlparse(iframe_src).query)
            if 'canPlayFHD' in iframe_qs or 'h' in iframe_qs:
                params['h'] = ['1']
            if 'scz' in iframe_qs:
                params['scz'] = ['1']
            if 'lang' in iframe_qs:
                params['lang'] = [iframe_qs['lang'][0]]
        else:
            params.setdefault('h', ['1'])
            params.setdefault('scz', ['1'])

        if extra_params and isinstance(extra_params, dict):
            for k, v in extra_params.items():
                if v and k not in params:
                    params[k] = [str(v)]

        if audio_orig or 'audio' in params or 'orig' in parsed.query:
            params['audio'] = ['orig']
            params['lang'] = ['orig']
        elif 'lang' not in params:
            params['lang'] = ['it']

        if sub_ita or 'sub' in params or 'sub=it' in parsed.query:
            params['sub'] = ['it']
        
        flat_params = []
        for k, v_list in params.items():
            for v in v_list:
                flat_params.append((k, v))
                
        new_query = urllib.parse.urlencode(flat_params)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, new_query, parsed.fragment))

    def extract_sc_m3u8(self, watch_url):
        if any(d in watch_url.lower() for d in ['vidsrc', 'lookmovie', 'superembed', 'autoembed', '2embed']):
            return {
                "type": "hls",
                "title": "International English Stream",
                "master_m3u8": watch_url,
                "vix_url": watch_url,
                "is_embed": True,
                "headers": {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Referer': watch_url
                }
            }

        if 'vixcloud.co' in watch_url.lower():
            parsed_v = urllib.parse.urlparse(watch_url)
            embed_id_match = re.search(r'/(?:playlist|embed|iframe)/(\d+)', watch_url)
            embed_id = embed_id_match.group(1) if embed_id_match else ""
            referer_header = f"https://vixcloud.co/embed/{embed_id}" if embed_id else "https://vixcloud.co/"
            
            full_m3u8 = watch_url
            if 'playlist' in watch_url and '.m3u8' not in parsed_v.path:
                if not parsed_v.path.endswith('.m3u8'):
                    new_path = parsed_v.path + '.m3u8'
                    full_m3u8 = urllib.parse.urlunparse((parsed_v.scheme, parsed_v.netloc, new_path, parsed_v.params, parsed_v.query, parsed_v.fragment))

            return {
                "type": "hls",
                "title": f"Stream Vixcloud ({embed_id or parsed_v.netloc})",
                "master_m3u8": full_m3u8,
                "vix_url": referer_header,
                "headers": {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Referer': referer_header,
                    'Origin': 'https://vixcloud.co'
                }
            }

        try:
            match_id = re.search(r'/(?:watch|titles)/(\d+)', watch_url)
            title_id_ext = match_id.group(1) if match_id else None

            parsed_input = urllib.parse.urlparse(watch_url)
            query_params = urllib.parse.parse_qs(parsed_input.query)

            req_ep_id = None
            if 'e' in query_params:
                req_ep_id = query_params['e'][0]
            elif 'episode' in query_params:
                req_ep_id = query_params['episode'][0]

            req_season_num = int(query_params.get('s', ['0'])[0]) if 's' in query_params else None
            req_ep_num = int(query_params.get('ep', ['0'])[0]) if 'ep' in query_params else None

            session = cffi_requests.Session(impersonate='chrome')
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7'
            }
            session.headers.update(headers)

            active_domain = self.get_active_sc_domain(watch_url)
            domains = [
                active_domain,
                f"{parsed_input.scheme}://{parsed_input.netloc}" if parsed_input.netloc else None,
                "https://streamingcommunity.computer",
                "https://streamingcommunityz.support"
            ]
            domains = [d for d in domains if d]

            res1 = None
            working_url = watch_url
            for d in domains:
                try:
                    test_url = f"{d}/it/watch/{title_id_ext}" if title_id_ext else watch_url
                    if req_ep_id:
                        test_url += f"?e={req_ep_id}"
                    r = session.get(test_url, timeout=5, allow_redirects=True)
                    if r.status_code == 200 and ('data-page' in r.text or 'inertia' in r.text):
                        res1 = r
                        working_url = test_url
                        break
                except Exception:
                    continue

            if not res1:
                res1 = session.get(watch_url, timeout=5, allow_redirects=True)

            if res1.status_code != 200:
                return None

            inertia_match = re.search(r'data-page=\"(.*?)\"', res1.text) or re.search(r"data-page='(.*?)'", res1.text)
            if not inertia_match:
                return None

            data_json = html_module.unescape(inertia_match.group(1))
            data = json.loads(data_json)
            props = data.get('props', {})

            embed_url = props.get('embedUrl')
            media_info = props.get('title') or props.get('media') or props.get('loadedTitle') or {}
            title_name = media_info.get('name') or media_info.get('title') or 'Film/Serie Streaming'

            if not embed_url and 'loadedTitle' in props:
                loaded = props['loadedTitle']
                title_id = loaded.get('id') or title_id_ext
                seasons = loaded.get('seasons', [])
                
                selected_ep = None
                if req_ep_id:
                    for s in seasons:
                        for ep in s.get('episodes', []):
                            if str(ep.get('id')) == str(req_ep_id) or str(ep.get('number')) == str(req_ep_id):
                                selected_ep = ep
                                break
                        if selected_ep: break

                if not selected_ep and req_season_num and req_ep_num:
                    for s in seasons:
                        if s.get('number') == req_season_num:
                            for ep in s.get('episodes', []):
                                if ep.get('number') == req_ep_num:
                                    selected_ep = ep
                                    break
                            if selected_ep: break

                if not selected_ep and seasons and seasons[0].get('episodes'):
                    selected_ep = seasons[0]['episodes'][0]

                if selected_ep:
                    ep_id = selected_ep.get('id')
                    ep_num = selected_ep.get('number')
                    s_num = selected_ep.get('season_number', 1)
                    ep_name = selected_ep.get('name', '')
                    title_name = f"{title_name} - S{s_num}E{ep_num} {ep_name}".strip()
                    embed_url = f"{active_domain}/iframe/{title_id}?episode={ep_id}"

            if not embed_url:
                return None

            episode_info = props.get('episode')
            if episode_info:
                ep_num = episode_info.get('number')
                ep_name = episode_info.get('name')
                title_name = f"{title_name} - Ep. {ep_num} {ep_name}".strip()

            session.headers['Referer'] = watch_url
            res2 = session.get(embed_url, timeout=6)

            iframe_match = re.search(r'<iframe[^>]+src=\"(.*?)\"', res2.text) or re.search(r"<iframe[^>]+src='(.*?)'", res2.text)
            if not iframe_match:
                return None

            iframe_src = html_module.unescape(iframe_match.group(1))

            session.headers['Referer'] = embed_url
            res3 = session.get(iframe_src, timeout=6)

            token_match = re.search(r"'token':\s*'([^']+)'", res3.text)
            expires_match = re.search(r"'expires':\s*'([^']+)'", res3.text)
            playlist_match = re.search(r"url:\s*'([^']+)'", res3.text)

            if not (token_match and expires_match and playlist_match):
                return None

            token = token_match.group(1)
            expires = expires_match.group(1)
            playlist_url = playlist_match.group(1)

            extra_params = {}
            master_params_match = re.search(r"masterPlaylist\s*=\s*\{.*?params:\s*(\{.*?\})", res3.text, re.DOTALL)
            if master_params_match:
                try:
                    raw_p = master_params_match.group(1)
                    for pm in re.finditer(r"['\"]?([a-zA-Z0-9_]+)['\"]?\s*:\s*['\"]([^'\"]*)['\"]", raw_p):
                        if pm.group(2):
                            extra_params[pm.group(1)] = pm.group(2)
                except Exception:
                    pass

            full_m3u8 = self._build_vix_m3u8_url(playlist_url, token, expires, iframe_src=iframe_src, extra_params=extra_params)

            return {
                "type": "hls",
                "title": title_name,
                "master_m3u8": full_m3u8,
                "vix_url": iframe_src,
                "headers": {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Referer': 'https://vixcloud.co/',
                    'Origin': 'https://vixcloud.co'
                }
            }
        except Exception as ex:
            return None

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
        if any(d in url.lower() for d in ['vidsrc', 'lookmovie', 'superembed', 'autoembed', '2embed']):
            return {
                "title": "Stream HD (English)",
                "url": url,
                "master_m3u8": url,
                "vix_url": url,
                "qualities": [
                    {"quality": "1080p", "label": "1080p Full HD (ENG)", "resolution": "1920x1080", "stream_url": url},
                    {"quality": "720p", "label": "720p HD (ENG)", "resolution": "1280x720", "stream_url": url}
                ],
                "audio_tracks": [
                    {"id": 0, "name": "English", "lang": "eng", "default": True, "forced": False}
                ],
                "subtitle_tracks": []
            }

        try:
            extracted = self.extract_sc_m3u8(url)
            if not extracted:
                return {"error": "Impossibile trovare il link video. Verifica che l'URL inserito sia corretto."}

            master_m3u8 = extracted['master_m3u8']
            vix_url = extracted['vix_url']
            title = extracted['title']

            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Referer': vix_url or 'https://vixcloud.co/',
                'Origin': 'https://vixcloud.co'
            }

            r_pl = self.session.get(master_m3u8, headers=headers, timeout=8)
            qualities = []
            audio_tracks = []
            subtitle_tracks = []

            if r_pl.status_code == 200:
                lines = r_pl.text.splitlines()
                audio_seen = set()
                subs_seen = set()

                for idx, line in enumerate(lines):
                    line_str = line.strip()
                    if line_str.startswith('#EXT-X-STREAM-INF:'):
                        res_match = re.search(r'RESOLUTION=(\d+x\d+)', line_str)
                        resolution = res_match.group(1) if res_match else "HD"
                        
                        next_line = lines[idx + 1].strip() if idx + 1 < len(lines) else master_m3u8
                        abs_stream_url = urllib.parse.urljoin(master_m3u8, next_line)
                        
                        if '1080' in resolution or '1920' in resolution:
                            q_code = "1080p"
                            label = "1080p Full HD"
                        elif '720' in resolution or '1280' in resolution:
                            q_code = "720p"
                            label = "720p HD"
                        else:
                            q_code = "480p"
                            label = f"{resolution.split('x')[-1]}p SD"
                            
                        qualities.append({
                            "quality": q_code,
                            "label": label,
                            "resolution": resolution,
                            "stream_url": abs_stream_url
                        })
                    elif line_str.startswith('#EXT-X-MEDIA:'):
                        media_type = re.search(r'TYPE=([A-Z]+)', line_str)
                        m_type = media_type.group(1) if media_type else ''
                        name_match = re.search(r'NAME="([^"]+)"', line_str)
                        name = name_match.group(1) if name_match else ''
                        lang_match = re.search(r'LANGUAGE="([^"]+)"', line_str)
                        lang = lang_match.group(1) if lang_match else ''
                        default_match = re.search(r'DEFAULT=(YES|NO)', line_str)
                        is_default = (default_match.group(1) == 'YES') if default_match else False
                        forced_match = re.search(r'FORCED=(YES|NO)', line_str)
                        is_forced = (forced_match.group(1) == 'YES') if forced_match else False
                        uri_match = re.search(r'URI="([^"]+)"', line_str)
                        uri = uri_match.group(1) if uri_match else ''
                        if uri:
                            uri = urllib.parse.urljoin(master_m3u8, uri)

                        if m_type == 'AUDIO':
                            track_key = (name, lang)
                            if track_key not in audio_seen:
                                audio_seen.add(track_key)
                                audio_tracks.append({
                                    "id": len(audio_tracks),
                                    "name": name,
                                    "lang": lang,
                                    "default": is_default,
                                    "forced": is_forced,
                                    "uri": uri
                                })
                        elif m_type == 'SUBTITLES':
                            track_key = (name, lang)
                            if track_key not in subs_seen:
                                subs_seen.add(track_key)
                                subtitle_tracks.append({
                                    "id": len(subtitle_tracks),
                                    "name": name,
                                    "lang": lang,
                                    "default": is_default,
                                    "forced": is_forced,
                                    "uri": uri
                                })

            if not audio_tracks:
                audio_tracks = [{"id": 0, "name": "Italian", "lang": "ita", "default": True, "forced": False, "uri": ""}]

            if not qualities:
                qualities = [
                    {"quality": "1080p", "label": "1080p Full HD", "resolution": "1920x1080", "stream_url": master_m3u8},
                    {"quality": "720p", "label": "720p HD", "resolution": "1280x720", "stream_url": master_m3u8},
                    {"quality": "480p", "label": "480p SD", "resolution": "854x480", "stream_url": master_m3u8}
                ]

            return {
                "title": title,
                "url": url,
                "master_m3u8": master_m3u8,
                "vix_url": vix_url,
                "qualities": qualities,
                "audio_tracks": audio_tracks,
                "subtitle_tracks": subtitle_tracks
            }
        except Exception as ex:
            return {"error": f"Errore analisi link: {str(ex)[:100]}"}

    def start_download(self, url, media_type="hls", format_choice="1080p", custom_title=None, custom_headers=None, parent_folder=None):
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
            "url": url,
            "title": custom_title or safe_title,
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

            if ".m3u8" in url or "/playlist/" in url:
                master_m3u8 = url
                vix_url = (custom_headers and custom_headers.get("Referer")) or "https://vixcloud.co/"
            elif "vixcloud.co" in url:
                vix_url = url
                res = self.extract_vixcloud_details(url)
                if res and res.get("master_m3u8"):
                    master_m3u8 = res["master_m3u8"]
                    custom_title = custom_title or res.get("title")
            else:
                extracted = self.extract_sc_m3u8(url)
                if extracted and extracted.get("master_m3u8"):
                    master_m3u8 = extracted["master_m3u8"]
                    vix_url = extracted.get("vix_url") or "https://vixcloud.co/"
                    custom_title = custom_title or extracted.get("title")
                else:
                    res = self.extract_vixcloud_details(url)
                    if res and res.get("master_m3u8"):
                        master_m3u8 = res["master_m3u8"]
                        vix_url = res.get("vix_url") or "https://vixcloud.co/"
                        custom_title = custom_title or res.get("title")

            if not master_m3u8:
                raise Exception(f"Impossibile estrarre lo stream video da {url}")

            headers_to_use = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Referer': vix_url or 'https://vixcloud.co/',
                'Origin': 'https://vixcloud.co'
            }

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
                'skip_unavailable_fragments': True,
                'buffersize': 2097152,
                'http_chunk_size': 10485760,
                'socket_timeout': 15
            }

            ydl_opts['concurrent_fragment_downloads'] = 4
            if 'Referer' in headers_to_use:
                ydl_opts['referer'] = headers_to_use['Referer']
            if 'User-Agent' in headers_to_use:
                ydl_opts['user_agent'] = headers_to_use['User-Agent']
            if ffmpeg_dir:
                ydl_opts['ffmpeg_location'] = ffmpeg_dir

            h = format_choice.replace('p', '') if isinstance(format_choice, str) else '1080'
            if ffmpeg_dir:
                ydl_opts.update({
                    'format': f'bv*[height<={h}]+ba/b[height<={h}]/best[height<={h}]',
                    'merge_output_format': 'mp4',
                    'postprocessor_args': {
                        'ffmpeg': ['-c:v', 'copy', '-c:a', 'aac']
                    }
                })
            else:
                ydl_opts.update({
                    'format': f'b[height<={h}]/best[height<={h}]/best'
                })

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
                        self.downloads[download_id]["process"] = proc

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
                        raise ex

        except Exception as ex:
            if download_id in self.downloads and not self.downloads[download_id].get("cancel_requested") and download_id not in self.canceled_downloads:
                self.downloads[download_id].update({
                    "state": "error",
                    "phase": "error",
                    "error": str(ex)
                })
    def get_status(self, download_id):
        return self.downloads.get(download_id, {"state": "error", "error": "Download non trovato."})

engine = Engine()

# -------------------------------------------------------------
# FLASK ROUTES
# -------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/sc/domain', methods=['GET'])
def get_sc_domain():
    return jsonify({"domain": engine.get_active_sc_domain()})

@app.route('/api/sc/home', methods=['GET'])
def home_sc():
    return jsonify(engine.get_home_catalog())

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

DEFAULT_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

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

        # Utilizzo prioritario di modelli ultra-leggeri a minimo consumo di token
        models_to_try = [
            "gemini-flash-lite-latest",
            "gemini-2.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest"
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

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}"
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

    TMDB_API_KEY = '4e44d9029b1270a757cddc766a1bcb63'
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
    return jsonify({"success": True, "titles": titles, "results": titles})

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
            s_u = f"https://api.themoviedb.org/3/search/{m_type}?api_key=4e44d9029b1270a757cddc766a1bcb63&language=it-IT&query={urllib.parse.quote(clean_q)}"
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
            c_u = f"https://api.themoviedb.org/3/{m_type}/{tmdb_id}/credits?api_key=4e44d9029b1270a757cddc766a1bcb63&language=it-IT"
            r_c = engine.safe_get(c_u, timeout=3)
            if r_c and r_c.status_code == 200:
                c_json = r_c.json()
                for actor in (c_json.get('cast') or [])[:20]:
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
    return jsonify({"success": True, "episodes": eps, "season_number": s_num})

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
            tmdb_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}/episode/{ep_num}?api_key=4e44d9029b1270a757cddc766a1bcb63&language=it-IT"
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

@app.route('/api/vixcloud/extract', methods=['GET', 'POST', 'OPTIONS'])
def extract_vixcloud():
    if request.method == 'OPTIONS':
        return jsonify({"success": True})
    data = request.get_json(silent=True) or {}
    url = data.get('url') or request.args.get('url', '')
    title_id = data.get('titleId') or data.get('id') or request.args.get('titleId')
    ep_id = data.get('episodeId') or data.get('e') or request.args.get('episodeId')
    
    if not url and title_id:
        active_domain = engine.get_active_sc_domain()
        url = f"{active_domain}/it/watch/{title_id}"
        if ep_id:
            url += f"?e={ep_id}"

    res = engine.extract_vixcloud_details(url)
    if isinstance(res, dict):
        return jsonify(res)
    return jsonify({"master_m3u8": "", "embed_url": "", "vix_url": ""})

@app.route('/api/download/start', methods=['POST'])
def start_download():
    data = request.get_json() or {}
    return jsonify(engine.start_download(
        url=data.get('url'),
        media_type=data.get('media_type', 'hls'),
        format_choice=data.get('format_choice', '1080p'),
        custom_title=data.get('custom_title'),
        custom_headers=data.get('custom_headers'),
        parent_folder=data.get('parent_folder')
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
    d_list = list(engine.downloads.values())
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

    extracted = engine.extract_sc_m3u8(watch_url)
    if not extracted:
        return jsonify({"error": "Impossibile estrarre lo stream Vixcloud"}), 404

    master_m3u8 = extracted['master_m3u8']
    vix_url = extracted['vix_url']

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': vix_url or 'https://vixcloud.co/',
        'Origin': 'https://vixcloud.co'
    }

    try:
        r = engine.session.get(master_m3u8, headers=headers, timeout=8)
        if r.status_code != 200:
            return jsonify({"error": "Impossibile recuperare il manifest HLS"}), 500

        content = r.text
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


@app.route('/api/stream/segment', methods=['GET'])
def stream_proxy_segment():
    segment_url = request.args.get('url', '')
    ref_url = request.args.get('ref', 'https://vixcloud.co/')
    if not segment_url:
        return jsonify({"error": "Parametro URL segment mancante"}), 400

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': ref_url,
        'Origin': 'https://vixcloud.co'
    }

    try:
        r = engine.session.get(segment_url, headers=headers, timeout=12)
        if '.m3u8' in segment_url.lower() or 'playlist' in segment_url.lower():
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

            return Response("\n".join(rewritten_lines), mimetype='application/vnd.apple.mpegurl', headers={'Access-Control-Allow-Origin': '*'})
        else:
            mime = r.headers.get('content-type') or ('application/octet-stream' if 'enc.key' in segment_url or '.key' in segment_url else 'video/MP2T')
            return Response(r.content, mimetype=mime, headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Cache-Control': 'public, max-age=3600'
            })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# HISTORY PERSISTENCE ON DISK
HISTORY_FILE = os.path.expanduser("~/.streamingcommunity_history.json")
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

FAVORITES_FILE = os.path.expanduser("~/.streamingcommunity_favorites.json")
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
PROFILES_FILE = os.path.expanduser("~/.streamingcommunity_profiles.json")
AVATARS_DIR = os.path.expanduser("~/.streamingcommunity/avatars")
try:
    os.makedirs(AVATARS_DIR, exist_ok=True)
except Exception:
    pass

profiles_lock = threading.RLock()

def load_profiles_data():
    with profiles_lock:
        for path in [PROFILES_FILE, PROFILES_FILE + ".bak"]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "profiles" in data and isinstance(data["profiles"], list):
                            if len(data["profiles"]) > 0 or path == PROFILES_FILE + ".bak":
                                return data
                            # If main file has 0 profiles but backup has profiles, prefer backup
                            if path == PROFILES_FILE and os.path.exists(PROFILES_FILE + ".bak"):
                                try:
                                    with open(PROFILES_FILE + ".bak", "r", encoding="utf-8") as fb:
                                        bak_data = json.load(fb)
                                        if isinstance(bak_data, dict) and "profiles" in bak_data and len(bak_data["profiles"]) > 0:
                                            return bak_data
                                except Exception:
                                    pass
                                return data
                except Exception as e:
                    print(f"Error reading profiles data from {path}:", e)
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

# -------------------------------------------------------------
# WATCHPARTY — SYNCHRONIZED VIEWING BETWEEN PROFILES
# -------------------------------------------------------------
WATCHPARTY_FILE = os.path.expanduser("~/.streamingcommunity_watchparty.json")
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
    data["sessions"] = [s for s in data.get("sessions", []) if (now - s.get("created_at", 0)) < max_age]
    return data

@app.route('/api/watchparty/create', methods=['POST'])
def watchparty_create():
    import time as _time, uuid as _uuid
    req = request.get_json(silent=True) or {}
    host_profile_id = req.get("host_profile_id")
    guest_profile_id = req.get("guest_profile_id")
    item = req.get("item")

    if not host_profile_id or not guest_profile_id or not item:
        return jsonify({"success": False, "error": "Parametri mancanti"}), 400

    profiles_data = load_profiles_data()
    host_prof = get_profile_by_id(profiles_data, host_profile_id)
    guest_prof = get_profile_by_id(profiles_data, guest_profile_id)
    if not host_prof or not guest_prof:
        return jsonify({"success": False, "error": "Profilo non trovato"}), 404

    session_id = f"wp_{int(_time.time())}_{_uuid.uuid4().hex[:8]}"

    with WATCHPARTY_LOCK:
        data = cleanup_old_sessions(load_watchparty_data())

        # A profile can host only one live party at a time.
        for s in data["sessions"]:
            if s.get("host_profile_id") == host_profile_id and s.get("status") in ("waiting", "active"):
                s["status"] = "ended"

        initial_time = 0.0
        try:
            initial_time = float(item.get("currentTime") or item.get("current_time") or 0)
        except Exception:
            initial_time = 0.0

        session = {
            "session_id": session_id,
            "host_profile_id": host_profile_id,
            "host_name": host_prof.get("name", "Host"),
            "host_avatar": host_prof.get("avatar", ""),
            "guest_profile_id": guest_profile_id,
            "guest_name": guest_prof.get("name", "Guest"),
            "guest_avatar": guest_prof.get("avatar", ""),
            "item": item,
            "status": "waiting",
            "current_time": initial_time,
            "paused": True,
            "last_action": None,
            "last_sync": int(_time.time() * 1000),
            "created_at": int(_time.time() * 1000)
        }

        data["sessions"].append(session)
        save_watchparty_data(data)

    return jsonify({"success": True, "session_id": session_id, "session": session})

@app.route('/api/watchparty/pending', methods=['GET'])
def watchparty_pending():
    profile_id = request.args.get("profile_id")
    if not profile_id:
        return jsonify({"sessions": []})

    data = load_watchparty_data()
    data = cleanup_old_sessions(data)

    pending = [s for s in data.get("sessions", [])
               if s.get("guest_profile_id") == profile_id and s.get("status") == "waiting"]

    return jsonify({"sessions": pending})

@app.route('/api/watchparty/accept', methods=['POST'])
def watchparty_accept():
    req = request.get_json(silent=True) or {}
    session_id = req.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    with WATCHPARTY_LOCK:
        data = load_watchparty_data()
        for s in data.get("sessions", []):
            if s.get("session_id") == session_id and s.get("status") == "waiting":
                s["status"] = "active"
                s["last_sync"] = int(time.time() * 1000)
                save_watchparty_data(data)
                return jsonify({"success": True, "session": s})

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
                return jsonify({"success": True})

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
            if s.get("session_id") == session_id and s.get("status") == "active":
                if "current_time" in req:
                    s["current_time"] = max(0, float(req["current_time"]))
                if "paused" in req:
                    s["paused"] = bool(req["paused"])
                s["last_action"] = req.get("action", req.get("last_action", "sync"))
                s["last_sync"] = int(_time.time() * 1000)
                save_watchparty_data(data)
                return jsonify({"success": True, "session": s})

    return jsonify({"success": False, "error": "Sessione non trovata o non attiva"}), 404

@app.route('/api/watchparty/state', methods=['GET'])
def watchparty_state():
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id mancante"}), 400

    data = load_watchparty_data()
    for s in data.get("sessions", []):
        if s.get("session_id") == session_id:
            return jsonify({"success": True, "session": s})

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
                return jsonify({"success": True})

    return jsonify({"success": False, "error": "Sessione non trovata"}), 404

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

    raw_list.sort(key=parse_ts, reverse=True)
    return jsonify(raw_list)

@app.route('/api/favorites', methods=['GET'])
def get_favorites():
    profile_id = request.args.get('profile_id')
    profiles_data = load_profiles_data()
    target_prof = get_profile_by_id(profiles_data, profile_id) if profile_id else get_profile_by_id(profiles_data, profiles_data.get("active_profile_id"))
    if target_prof:
        return jsonify(target_prof.get("favorites", {}))
    return jsonify(load_favorites_data())

@app.route('/api/favorites/save', methods=['POST'])
def save_favorites():
    data = request.get_json(silent=True) or {}
    profile_id = request.args.get('profile_id') or (data.get('profile_id') if isinstance(data, dict) else None)
    fav_items = data.get('favorites') if (isinstance(data, dict) and 'favorites' in data) else data
    if isinstance(fav_items, dict) and 'profile_id' in fav_items:
        fav_items = {k: v for k, v in fav_items.items() if k != 'profile_id'}

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
AUTH_SESSION_FILE = os.path.expanduser("~/.streamingcommunity_auth.json")

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

@app.route('/tv')
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
        title='StreamingCommunity Downloader & Streaming',
        url=f'http://127.0.0.1:{target_port}',
        width=1280,
        height=800,
        resizable=True,
        fullscreen=True,
        min_size=(900, 600)
    )
    webview.start()
