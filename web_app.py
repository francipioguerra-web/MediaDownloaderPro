import os
import sys
import re
import time
import json
import uuid
import shutil
import urllib.parse
import threading
import subprocess
import concurrent.futures
import requests
import html as html_module
import yt_dlp
from flask import Flask, render_template, request, jsonify, send_from_directory

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except BaseException:
    cffi_requests = None
    HAS_CURL_CFFI = False

app = Flask(__name__, template_folder='templates', static_folder='static')

# Create downloads folder inside project directory
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

class MediaDownloaderServer:
    def __init__(self):
        self._browser_headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        self._downloads = {}  # download_id -> dict of status info
        self._download_threads = {}

    def analyze_url(self, url):
        if not url or not isinstance(url, str):
            return {"error": "URL non fornito o non valido."}

        url = url.strip()
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return {"error": "URL non valido. Assicurati che inizi con http:// o https://"}

        if 'streamingcommunity' in url.lower() or 'vixcloud' in url.lower():
            res_sc = self._resolve_streamingcommunity(url)
            if res_sc and not res_sc.get('error'):
                return res_sc

        res_host = self._resolve_special_hosts(url)
        if res_host and not res_host.get('error'):
            return res_host

        path_lower = parsed.path.lower()

        if path_lower.endswith('.m3u8') or '.m3u8' in url:
            return {
                "type": "hls",
                "title": f"Flusso HLS Stream ({parsed.netloc})",
                "url": url,
                "thumbnail": None,
                "file_size": "Stream HLS (.m3u8)",
                "source": parsed.netloc,
                "duration": "HLS Playlist",
                "headers": self._browser_headers
            }

        direct_extensions = ('.mp4', '.mp3', '.mov', '.mkv', '.avi', '.webm', '.flv',
                             '.m4a', '.wav', '.flac', '.jpg', '.jpeg', '.png', '.gif',
                             '.webp', '.svg', '.pdf', '.zip', '.tar', '.gz')
        
        if any(path_lower.endswith(ext) for ext in direct_extensions):
            return self._analyze_direct_link(url)

        m3u8_found = self._scan_page_for_hls(url)
        if m3u8_found:
            page_title = m3u8_found.get('title') or f"Video Stream ({parsed.netloc})"
            return {
                "type": "hls",
                "title": page_title,
                "url": m3u8_found['m3u8_url'],
                "thumbnail": m3u8_found.get('thumbnail'),
                "file_size": "Stream HLS Rilevato",
                "source": parsed.netloc,
                "duration": "Playlist .m3u8",
                "headers": m3u8_found.get('headers')
            }

        return self._analyze_stream_link(url)

    def _resolve_special_hosts(self, url):
        url_lower = url.lower()
        parsed = urllib.parse.urlparse(url)

        # 1. Pixeldrain (pixeldrain.com/u/<id> or /l/<id>)
        if 'pixeldrain.com' in url_lower:
            pix_match = re.search(r'pixeldrain\.com/(?:u|l)/([a-zA-Z0-9_-]+)', url)
            if pix_match:
                file_id = pix_match.group(1)
                direct_url = f"https://pixeldrain.com/api/file/{file_id}?download"
                
                title = f"Pixeldrain File ({file_id})"
                size_str = "File Pixeldrain"
                try:
                    info_res = requests.get(f"https://pixeldrain.com/api/file/{file_id}/info", headers=self._browser_headers, timeout=5)
                    if info_res.status_code == 200:
                        meta = info_res.json()
                        title = meta.get('name') or title
                        if 'size' in meta:
                            size_str = self._format_size(meta['size'])
                except Exception:
                    pass

                return {
                    "type": "direct",
                    "title": title,
                    "url": direct_url,
                    "thumbnail": None,
                    "file_size": size_str,
                    "source": "Pixeldrain",
                    "duration": "File Diretto"
                }

        # 2. Bunkr (bunkr.sk, bunkr.cr, bunkr.is, bunkrr.org, bunkr.ph, bunkr.cat, bunkr.site, etc.)
        if 'bunkr' in url_lower or 'bunkrr' in url_lower:
            try:
                headers = self._browser_headers.copy()
                headers['Referer'] = url
                res = requests.get(url, headers=headers, timeout=8)
                if res.status_code == 200:
                    html_text = res.text
                    
                    t_match = re.search(r'<title>(.*?)</title>', html_text, re.IGNORECASE)
                    page_title = t_match.group(1).strip() if t_match else "Bunkr Media File"
                    page_title = re.sub(r'\s*\|\s*Bunkr.*$', '', page_title, flags=re.IGNORECASE)

                    vid_src = re.search(r'<(?:video|source)[^>]+src=["\'](https?://[^"\']+)["\']', html_text, re.IGNORECASE)
                    cdn_link = re.search(r'href=["\'](https?://[^"\']*(?:bunkr|cdn|media)[^"\']*\.(?:mp4|mkv|mov|webm|mp3|zip|rar)[^"\']*)["\']', html_text, re.IGNORECASE)

                    found_media_url = None
                    if vid_src:
                        found_media_url = vid_src.group(1)
                    elif cdn_link:
                        found_media_url = cdn_link.group(1)

                    if found_media_url:
                        return {
                            "type": "direct",
                            "title": page_title,
                            "url": found_media_url,
                            "thumbnail": None,
                            "file_size": "Media Bunkr",
                            "source": "Bunkr",
                            "duration": "Video Bunkr",
                            "headers": {
                                "User-Agent": self._browser_headers["User-Agent"],
                                "Referer": "https://bunkr.cr/"
                            }
                        }
            except Exception:
                pass

        # 3. Generic scanner for any file host (Filester, File-Upload, Doodstream, Streamtape, Mixdrop, etc.)
        try:
            res = requests.get(url, headers=self._browser_headers, timeout=6)
            if res.status_code == 200:
                html_text = res.text
                vid_src = re.search(r'<(?:video|source)[^>]+src=["\'](https?://[^"\']+\.(?:mp4|mkv|mov|webm|m4a|mp3)[^"\']*)["\']', html_text, re.IGNORECASE)
                if vid_src:
                    t_match = re.search(r'<title>(.*?)</title>', html_text, re.IGNORECASE)
                    page_title = t_match.group(1).strip() if t_match else f"Media File ({parsed.netloc})"
                    return {
                        "type": "direct",
                        "title": page_title,
                        "url": vid_src.group(1),
                        "thumbnail": None,
                        "file_size": "Media Rilevato",
                        "source": parsed.netloc,
                        "duration": "File Media",
                        "headers": {
                            "User-Agent": self._browser_headers["User-Agent"],
                            "Referer": url
                        }
                    }
        except Exception:
            pass

        return None

    def _build_vix_m3u8_url(self, playlist_url, token, expires):
        parsed = urllib.parse.urlparse(playlist_url)
        path = parsed.path
        if not path.endswith('.m3u8'):
            path = path + '.m3u8'
        
        params = urllib.parse.parse_qs(parsed.query)
        params['token'] = [token]
        params['expires'] = [expires]
        params['h'] = ['1']
        params['scz'] = ['1']
        params['lang'] = ['it']
        
        flat_params = []
        for k, v_list in params.items():
            for v in v_list:
                flat_params.append((k, v))
                
        new_query = urllib.parse.urlencode(flat_params)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, new_query, parsed.fragment))

    def _resolve_streamingcommunity(self, url):
        if 'vixcloud.co' in url.lower():
            parsed_v = urllib.parse.urlparse(url)
            embed_id_match = re.search(r'/(?:playlist|embed|iframe)/(\d+)', url)
            embed_id = embed_id_match.group(1) if embed_id_match else ""
            referer_header = f"https://vixcloud.co/embed/{embed_id}" if embed_id else "https://vixcloud.co/"
            
            new_path = parsed_v.path.replace('/embed/', '/playlist/').replace('/iframe/', '/playlist/')
            if not new_path.endswith('.m3u8'):
                new_path = new_path + '.m3u8'
            full_m3u8 = urllib.parse.urlunparse((parsed_v.scheme, parsed_v.netloc, new_path, parsed_v.params, parsed_v.query, parsed_v.fragment))

            return {
                "type": "hls",
                "title": f"Stream Vixcloud ({embed_id or parsed_v.netloc})",
                "url": full_m3u8,
                "thumbnail": None,
                "file_size": "Stream HLS (Vixcloud)",
                "source": "Vixcloud",
                "duration": "HLS Stream",
                "headers": {
                    'User-Agent': self._browser_headers['User-Agent'],
                    'Referer': referer_header,
                    'Origin': 'https://vixcloud.co'
                }
            }

        try:
            if HAS_CURL_CFFI:
                session = cffi_requests.Session(impersonate="chrome")
            else:
                session = requests.Session()
            session.headers.update(self._browser_headers)

            res1 = session.get(url, timeout=8)
            if res1.status_code != 200:
                return None

            html_text = res1.text

            # Check if this is an iframe URL directly or contains inner iframe
            iframe_match = re.search(r'<iframe[^>]+src=\"(.*?)\"', html_text) or re.search(r"<iframe[^>]+src='(.*?)'", html_text)
            if iframe_match:
                iframe_src = html_module.unescape(iframe_match.group(1))
                if not iframe_src.startswith('http'):
                    iframe_src = urllib.parse.urljoin(url, iframe_src)
                if 'vixcloud.co' in iframe_src.lower():
                    return self._resolve_streamingcommunity(iframe_src)
                session.headers['Referer'] = url
                res_sub = session.get(iframe_src, timeout=6)
                if res_sub.status_code == 200:
                    html_text = res_sub.text

            token_match = re.search(r"'token':\s*'([^']+)'", html_text) or re.search(r'token\s*=\s*["\']([^"\']+)["\']', html_text)
            expires_match = re.search(r"'expires':\s*'([^']+)'", html_text) or re.search(r'expires\s*=\s*["\']([^"\']+)["\']', html_text)
            playlist_match = re.search(r"url:\s*'([^']+)'", html_text) or re.search(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', html_text)

            if token_match and expires_match and playlist_match:
                token = token_match.group(1)
                expires = expires_match.group(1)
                playlist_url = playlist_match.group(1)
                full_m3u8 = self._build_vix_m3u8_url(playlist_url, token, expires)

                t_match = re.search(r'<title>(.*?)</title>', html_text, re.IGNORECASE)
                title_name = t_match.group(1).strip() if t_match else "Streaming Video"

                return {
                    "type": "hls",
                    "title": title_name,
                    "url": full_m3u8,
                    "thumbnail": None,
                    "file_size": "Stream HLS (StreamingCommunity / Vixcloud)",
                    "source": "StreamingCommunity",
                    "duration": "HLS Stream",
                    "headers": {
                        'User-Agent': self._browser_headers['User-Agent'],
                        'Referer': url,
                        'Origin': 'https://vixcloud.co'
                    }
                }

            inertia_match = re.search(r'data-page=\"(.*?)\"', html_text) or re.search(r"data-page='(.*?)'", html_text)

            if inertia_match:
                data_json = html_module.unescape(inertia_match.group(1))
                data = json.loads(data_json)
                props = data.get('props', {})

                embed_url = props.get('embedUrl')
                media_info = props.get('title') or props.get('media') or props.get('loadedTitle') or {}
                title_name = media_info.get('name') or media_info.get('title') or 'Film/Serie Streaming'

                if not embed_url and 'loadedTitle' in props:
                    loaded = props['loadedTitle']
                    seasons = loaded.get('seasons', [])
                    if seasons:
                        episodes = seasons[0].get('episodes', [])
                        if episodes:
                            ep_id = episodes[0].get('id')
                            title_id = loaded.get('id')
                            parsed_u = urllib.parse.urlparse(url)
                            embed_url = f"{parsed_u.scheme}://{parsed_u.netloc}/iframe/{title_id}?episode={ep_id}"

                if embed_url:
                    episode_info = props.get('episode')
                    if episode_info:
                        ep_num = episode_info.get('number')
                        ep_name = episode_info.get('name')
                        title_name = f"{title_name} - Ep. {ep_num} {ep_name}".strip()

                    res_embed = self._resolve_streamingcommunity(embed_url)
                    if res_embed and not res_embed.get('error'):
                        res_embed['title'] = title_name
                        return res_embed

        except Exception as ex:
            return {"error": f"Errore decodifica StreamingCommunity: {str(ex)[:100]}"}

        return None

    def _scan_page_for_hls(self, url):
        try:
            if HAS_CURL_CFFI:
                session = cffi_requests.Session(impersonate="chrome")
                res = session.get(url, headers=self._browser_headers, timeout=6)
            else:
                res = requests.get(url, headers=self._browser_headers, timeout=6)
            if res.status_code != 200:
                return None

            html = res.text
            m3u8_matches = re.findall(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', html)
            
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            page_title = title_match.group(1).strip() if title_match else None

            og_image = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
            thumb = og_image.group(1) if og_image else None

            if m3u8_matches:
                best_m3u8 = m3u8_matches[0]
                for match in m3u8_matches:
                    if 'master' in match.lower() or 'index' in match.lower() or 'playlist' in match.lower():
                        best_m3u8 = match
                        break

                return {
                    "m3u8_url": best_m3u8,
                    "title": page_title,
                    "thumbnail": thumb,
                    "headers": {
                        "User-Agent": self._browser_headers["User-Agent"],
                        "Referer": url
                    }
                }
            return None
        except Exception:
            return None

    def _analyze_direct_link(self, url):
        parsed = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed.path) or "file_download"
        file_size_str = "Dimensione sconosciuta"
        
        try:
            head = requests.head(url, headers=self._browser_headers, allow_redirects=True, timeout=5)
            if 'Content-Length' in head.headers:
                size_bytes = int(head.headers['Content-Length'])
                file_size_str = self._format_size(size_bytes)
        except Exception:
            pass

        return {
            "type": "direct",
            "title": urllib.parse.unquote(filename),
            "url": url,
            "thumbnail": None,
            "file_size": file_size_str,
            "source": parsed.netloc,
            "duration": "File Diretto"
        }

    def _analyze_stream_link(self, url):
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'http_headers': self._browser_headers
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Titolo sconosciuto')
                duration_sec = info.get('duration')
                duration_str = self._format_duration(duration_sec) if duration_sec else "N/D"
                thumbnail = info.get('thumbnail')
                filesize = info.get('filesize') or info.get('filesize_approx')
                filesize_str = self._format_size(filesize) if filesize else "Variabile / N/D"
                extractor = info.get('extractor_key', 'Web')

                return {
                    "type": "stream",
                    "title": title,
                    "url": url,
                    "thumbnail": thumbnail,
                    "file_size": filesize_str,
                    "source": extractor,
                    "duration": duration_str
                }
        except Exception as ex:
            return {"error": f"Impossibile analizzare l'URL: {str(ex)[:120]}"}

    def start_download(self, url, media_type, format_choice, custom_title=None, custom_headers=None):
        download_id = f"dl_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        
        self._downloads[download_id] = {
            "download_id": download_id,
            "url": url,
            "title": custom_title or "Download",
            "state": "running",
            "percent": 0.0,
            "speed": "0 B/s",
            "downloaded": "0 B",
            "total": "--",
            "filename": None,
            "download_url": None,
            "error": None
        }

        t = threading.Thread(target=self._run_download, args=(download_id, url, media_type, format_choice, custom_title, custom_headers))
        t.daemon = True
        self._download_threads[download_id] = t
        t.start()

        return {"download_id": download_id}

    def pause_download(self, download_id):
        if download_id in self._downloads:
            self._downloads[download_id]["state"] = "paused"
            self._downloads[download_id]["speed"] = "In pausa"
            return True
        return False

    def resume_download(self, download_id):
        if download_id in self._downloads:
            self._downloads[download_id]["state"] = "running"
            return True
        return False

    def cancel_download(self, download_id):
        if download_id in self._downloads:
            self._downloads[download_id]["state"] = "cancelled"
            return True
        return False

    def get_status(self, download_id):
        return self._downloads.get(download_id, {"error": "Download non trovato."})

    def _check_download_status(self, download_id):
        if download_id in self._downloads:
            state = self._downloads[download_id]["state"]
            if state == "cancelled":
                raise Exception("DOWNLOAD_CANCELLED")
            while self._downloads[download_id]["state"] == "paused":
                time.sleep(0.3)
                if self._downloads[download_id]["state"] == "cancelled":
                    raise Exception("DOWNLOAD_CANCELLED")

    def _run_download(self, download_id, url, media_type, format_choice, custom_title, custom_headers):
        try:
            # Auto-resolve webpage / iframe / streaming URLs before downloading if needed
            if 'streamingcommunity' in url.lower() or 'vixcloud' in url.lower() or '/iframe/' in url.lower() or ('.m3u8' not in url and not any(url.lower().endswith(ext) for ext in ['.mp4','.mkv','.webm','.mov','.avi','.mp3'])):
                res_analysis = self.analyze_url(url)
                if res_analysis and not res_analysis.get('error'):
                    url = res_analysis.get('url', url)
                    media_type = res_analysis.get('type', media_type)
                    custom_title = custom_title or res_analysis.get('title')
                    headers_found = res_analysis.get('headers')
                    if headers_found:
                        if not custom_headers:
                            custom_headers = {}
                        custom_headers.update(headers_found)

            if media_type == 'direct':
                self._download_direct(download_id, url, custom_title, custom_headers)
            else:
                try:
                    self._download_stream_yt(download_id, url, format_choice, custom_title, custom_headers)
                except Exception as stream_ex:
                    if '.m3u8' in url or media_type == 'hls' or 'vixcloud' in url:
                        self._download_hls_custom(download_id, url, custom_title, custom_headers)
                    else:
                        raise stream_ex
        except Exception as ex:
            err_msg = str(ex).strip() or repr(ex) or "Errore durante il download del flusso video"
            if "DOWNLOAD_CANCELLED" in err_msg:
                self._downloads[download_id]["state"] = "cancelled"
            else:
                self._downloads[download_id]["state"] = "error"
                self._downloads[download_id]["error"] = err_msg

    def _download_direct(self, download_id, url, custom_title=None, custom_headers=None):
        headers = self._browser_headers.copy()
        if custom_headers and isinstance(custom_headers, dict):
            headers.update(custom_headers)

        res = requests.get(url, headers=headers, stream=True, timeout=10)
        res.raise_for_status()

        total_size = int(res.headers.get('Content-Length', 0))
        
        parsed = urllib.parse.urlparse(url)
        ext = os.path.splitext(parsed.path)[1] or '.mp4'
        
        if custom_title:
            safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title).strip()
            filename = f"{safe_title}{ext}"
        else:
            filename = os.path.basename(parsed.path) or f"media_{int(time.time())}{ext}"
            filename = urllib.parse.unquote(filename)

        filepath = os.path.join(DOWNLOADS_DIR, filename)

        downloaded = 0
        start_time = time.time()

        with open(filepath, 'wb') as f:
            for chunk in res.iter_content(chunk_size=1048576):
                self._check_download_status(download_id)
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    elapsed = time.time() - start_time
                    speed_bps = downloaded / elapsed if elapsed > 0 else 0
                    percent = (downloaded / total_size * 100) if total_size > 0 else 0
                    
                    self._downloads[download_id].update({
                        "percent": round(percent, 1),
                        "speed": f"{self._format_size(speed_bps)}/s",
                        "downloaded": self._format_size(downloaded),
                        "total": self._format_size(total_size)
                    })

        self._downloads[download_id].update({
            "state": "completed",
            "percent": 100.0,
            "filename": filename,
            "download_url": f"/api/download/file/{urllib.parse.quote(filename)}"
        })

    def _download_hls_custom(self, download_id, m3u8_url, custom_title=None, custom_headers=None):
        headers = self._browser_headers.copy()
        if custom_headers and isinstance(custom_headers, dict):
            headers.update(custom_headers)

        if HAS_CURL_CFFI:
            session = cffi_requests.Session(impersonate="chrome")
        else:
            session = requests.Session()
        session.headers.update(headers)

        # Parse master playlist if needed to get highest quality sub-playlist
        res = session.get(m3u8_url, timeout=10)
        res.raise_for_status()
        m3u8_text = res.text

        playlist_url = m3u8_url
        if "#EXT-X-STREAM-INF" in m3u8_text:
            lines = [l.strip() for l in m3u8_text.splitlines() if l.strip() and not l.startswith('#')]
            if lines:
                sub_uri = lines[-1]
                playlist_url = urllib.parse.urljoin(m3u8_url, sub_uri)
                res_sub = session.get(playlist_url, timeout=10)
                res_sub.raise_for_status()
                m3u8_text = res_sub.text

        segment_urls = []
        for line in m3u8_text.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                segment_urls.append(urllib.parse.urljoin(playlist_url, line))

        if not segment_urls:
            raise Exception("Nessun frammento video trovato nella playlist M3U8")

        total_segments = len(segment_urls)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title).strip() if custom_title else f"video_{download_id}"
        ts_filename = f"{safe_title}_{download_id}.ts"
        mp4_filename = f"{safe_title}.mp4"
        ts_filepath = os.path.join(DOWNLOADS_DIR, ts_filename)
        mp4_filepath = os.path.join(DOWNLOADS_DIR, mp4_filename)

        downloaded_count = 0
        segments_data = [None] * total_segments

        def fetch_segment(index_url):
            idx, seg_url = index_url
            for _ in range(3):
                try:
                    s_res = session.get(seg_url, timeout=15)
                    if s_res.status_code == 200:
                        return idx, s_res.content
                except Exception:
                    pass
                time.sleep(0.5)
            return idx, b""

        start_time = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_seg = {executor.submit(fetch_segment, (i, u)): i for i, u in enumerate(segment_urls)}
            for future in concurrent.futures.as_completed(future_to_seg):
                self._check_download_status(download_id)
                idx, content = future.result()
                segments_data[idx] = content
                downloaded_count += 1

                elapsed = time.time() - start_time
                percent = round((downloaded_count / total_segments) * 85.0, 1)
                total_bytes_est = downloaded_count * 500000
                speed_bps = total_bytes_est / elapsed if elapsed > 0 else 0

                self._downloads[download_id].update({
                    "percent": percent,
                    "speed": f"{self._format_size(speed_bps)}/s",
                    "downloaded": f"{downloaded_count}/{total_segments} frammenti",
                    "total": f"{total_segments} seg"
                })

        # Concatenate all TS fragments sequentially
        valid_bytes = sum(len(b) for b in segments_data if b)
        if valid_bytes < 1000:
            if os.path.exists(ts_filepath):
                try: os.remove(ts_filepath)
                except: pass
            raise Exception("Impossibile scaricare i frammenti HLS: Risposta HTTP 403 Forbidden o token scaduto.")

        with open(ts_filepath, "wb") as f_out:
            for data in segments_data:
                if data:
                    f_out.write(data)

        if not os.path.exists(ts_filepath) or os.path.getsize(ts_filepath) < 1000:
            if os.path.exists(ts_filepath):
                try: os.remove(ts_filepath)
                except: pass
            raise Exception("Il file TS scaricato è vuoto o incompleto.")

        # Convert / Remux TS to MP4 via ffmpeg
        self._downloads[download_id].update({
            "percent": 90.0,
            "speed": "Elaborazione MP4...",
            "downloaded": "Remuxing MP4"
        })

        ffmpeg_cmd = ["ffmpeg", "-y", "-i", ts_filepath, "-c", "copy", mp4_filepath]
        try:
            subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(mp4_filepath) and os.path.getsize(mp4_filepath) > 1000:
                if os.path.exists(ts_filepath):
                    try: os.remove(ts_filepath)
                    except: pass
                final_filename = mp4_filename
            elif os.path.exists(ts_filepath) and os.path.getsize(ts_filepath) > 1000:
                final_filename = ts_filename
            else:
                raise Exception("Conversione MP4 fallita e file TS vuoto.")
        except Exception:
            if os.path.exists(ts_filepath) and os.path.getsize(ts_filepath) > 1000:
                final_filename = ts_filename
            else:
                if os.path.exists(ts_filepath):
                    try: os.remove(ts_filepath)
                    except: pass
                raise Exception("Conversione in MP4 fallita. Il flusso video potrebbe essere protetto o corrotto.")

        self._downloads[download_id].update({
            "state": "completed",
            "percent": 100.0,
            "filename": final_filename,
            "download_url": f"/api/download/file/{urllib.parse.quote(final_filename)}"
        })

    def _download_stream_yt(self, download_id, url, format_choice, custom_title=None, custom_headers=None):
        if custom_title:
            safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title).strip()
            out_tmpl = os.path.join(DOWNLOADS_DIR, f"{safe_title}.%(ext)s")
        else:
            out_tmpl = os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s')

        if "vixcloud" in url.lower():
            parsed = urllib.parse.urlparse(url)
            new_path = parsed.path.replace('/embed/', '/playlist/').replace('/iframe/', '/playlist/')
            if not new_path.endswith('.m3u8'):
                new_path = new_path + '.m3u8'
            url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, new_path, parsed.params, parsed.query, parsed.fragment))

        track_progress = {}

        def progress_hook(d):
            self._check_download_status(download_id)
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

                self._downloads[download_id].update({
                    "percent": round(overall_percent, 1),
                    "speed": f"{self._format_size(speed)}/s",
                    "downloaded": self._format_size(downloaded),
                    "total": self._format_size(total)
                })

        headers_to_use = self._browser_headers.copy()
        if custom_headers and isinstance(custom_headers, dict):
            headers_to_use.update(custom_headers)

        if 'vixcloud' in url.lower() or 'streamingcommunity' in url.lower():
            embed_id_match = re.search(r'/(?:playlist|embed|iframe)/(\d+)', url)
            embed_id = embed_id_match.group(1) if embed_id_match else ""
            if 'Referer' not in headers_to_use or not headers_to_use['Referer']:
                headers_to_use['Referer'] = f"https://vixcloud.co/embed/{embed_id}" if embed_id else "https://vixcloud.co/"
            if 'Origin' not in headers_to_use or not headers_to_use['Origin']:
                headers_to_use['Origin'] = "https://vixcloud.co"

        ffmpeg_path = None
        for p in ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']:
            if os.path.exists(p):
                ffmpeg_path = os.path.dirname(p)
                break
        if not ffmpeg_path:
            which_ff = shutil.which('ffmpeg')
            if which_ff:
                ffmpeg_path = os.path.dirname(which_ff)

        ydl_opts = {
            'outtmpl': out_tmpl,
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'http_headers': headers_to_use,
            'impersonate': 'chrome',
            'extractor_args': {'generic': ['impersonate']},
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'buffersize': 2097152,         # 2 MB buffer di lettura memoria per I/O super veloce
            'http_chunk_size': 10485760,   # 10 MB chunk HTTP
            'socket_timeout': 15
        }

        if 'vixcloud' in url.lower() or 'streamingcommunity' in url.lower():
            ydl_opts['concurrent_fragment_downloads'] = 1
        else:
            ydl_opts['concurrent_fragment_downloads'] = 4

        if 'Referer' in headers_to_use:
            ydl_opts['referer'] = headers_to_use['Referer']
        if 'User-Agent' in headers_to_use:
            ydl_opts['user_agent'] = headers_to_use['User-Agent']
        if 'Cookie' in headers_to_use:
            ydl_opts['cookie'] = headers_to_use['Cookie']

        if ffmpeg_path:
            ydl_opts['ffmpeg_location'] = ffmpeg_path

        if format_choice == 'mp3':
            ydl_opts.update({
                'format': 'bestaudio/ba/b',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        elif format_choice in ('1080', '720', '480', '360', '2160'):
            h = format_choice
            ydl_opts.update({
                'format': f'b[height<={h}]/bv*[height<={h}]+ba/best[height<={h}]/best',
                'merge_output_format': 'mp4'
            })
        else:
            ydl_opts.update({
                'format': 'b/best/bv*+ba',
                'merge_output_format': 'mp4'
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            prep_filename = ydl.prepare_filename(info)
            filename = os.path.basename(prep_filename)
            full_path = os.path.join(DOWNLOADS_DIR, filename)
            if not os.path.exists(full_path) or os.path.getsize(full_path) < 1000:
                if os.path.exists(full_path):
                    try: os.remove(full_path)
                    except: pass
                raise Exception("Il file scaricato tramite motore stream è vuoto o incompleto.")

            self._downloads[download_id].update({
                "state": "completed",
                "percent": 100.0,
                "filename": filename,
                "download_url": f"/api/download/file/{urllib.parse.quote(filename)}"
            })

    def get_active_downloads(self):
        active = []
        for dl_id, info in self._downloads.items():
            if info.get('state') in ('running', 'paused', 'starting'):
                item = dict(info)
                item['download_id'] = dl_id
                active.append(item)
        return active

    def _format_size(self, size_bytes):
        if not size_bytes or size_bytes <= 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while size_bytes >= 1024 and i < len(units) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {units[i]}"

    def _format_duration(self, seconds):
        if not seconds:
            return "00:00"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


server = MediaDownloaderServer()

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

@app.route('/api/ping', methods=['GET', 'OPTIONS'])
def ping():
    return jsonify({"status": "ok", "app": "MediaDownloader", "version": "2.0"})

@app.route('/api/download/active', methods=['GET', 'OPTIONS'])
def active_downloads():
    if request.method == 'OPTIONS':
        return '', 200
    return jsonify({"downloads": server.get_active_downloads()})

# Flask Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    if request.method == 'OPTIONS':
        return '', 200
    data = request.get_json() or {}
    url = data.get('url')
    res = server.analyze_url(url)
    return jsonify(res)

@app.route('/api/download/start', methods=['POST', 'OPTIONS'])
def start_download():
    if request.method == 'OPTIONS':
        return '', 200
    data = request.get_json() or {}
    url = data.get('url')
    media_type = data.get('media_type', 'stream')
    format_choice = data.get('format_choice', 'mp4')
    custom_title = data.get('custom_title')
    custom_headers = data.get('custom_headers')
    
    res = server.start_download(url, media_type, format_choice, custom_title, custom_headers)
    return jsonify(res)

@app.route('/api/download/status/<download_id>', methods=['GET', 'OPTIONS'])
def status(download_id):
    if request.method == 'OPTIONS':
        return '', 200
    res = server.get_status(download_id)
    return jsonify(res)

@app.route('/api/download/pause/<download_id>', methods=['POST', 'OPTIONS'])
def pause(download_id):
    if request.method == 'OPTIONS':
        return '', 200
    ok = server.pause_download(download_id)
    return jsonify({"success": ok})

@app.route('/api/download/resume/<download_id>', methods=['POST', 'OPTIONS'])
def resume(download_id):
    if request.method == 'OPTIONS':
        return '', 200
    ok = server.resume_download(download_id)
    return jsonify({"success": ok})

@app.route('/api/download/cancel/<download_id>', methods=['POST', 'OPTIONS'])
def cancel(download_id):
    if request.method == 'OPTIONS':
        return '', 200
    ok = server.cancel_download(download_id)
    return jsonify({"success": ok})

@app.route('/api/download/file/<filename>')
def download_file(filename):
    unquoted = urllib.parse.unquote(filename)
    return send_from_directory(DOWNLOADS_DIR, unquoted, as_attachment=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print("=" * 60)
    print(" 🚀 MEDIA DOWNLOADER WEB APPLICATION SERVER STARTED!")
    print(f" 🌐 Local URL: http://localhost:{port}")
    print(f" 📱 Network URL: http://0.0.0.0:{port}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)
