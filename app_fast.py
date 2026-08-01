import os
import sys
import re
import json
import time
import urllib.parse
import urllib.request
import subprocess
import threading
import concurrent.futures
import html as html_module
import webview
import requests
import yt_dlp

class MediaDownloaderAPI:
    def __init__(self):
        self._window = None
        self._default_download_dir = os.path.expanduser("~/Downloads")
        self._browser_headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        self._last_progress_time = {}
        self._download_states = {}

    def pause_download(self, download_id):
        if download_id in self._download_states and self._download_states[download_id] == 'running':
            self._download_states[download_id] = 'paused'
            self._notify_state_change(download_id, 'paused')
            return True
        return False

    def resume_download(self, download_id):
        if download_id in self._download_states and self._download_states[download_id] == 'paused':
            self._download_states[download_id] = 'running'
            self._notify_state_change(download_id, 'running')
            return True
        return False

    def cancel_download(self, download_id):
        if download_id in self._download_states:
            self._download_states[download_id] = 'cancelled'
            self._notify_state_change(download_id, 'cancelled')
            return True
        return False

    def _notify_state_change(self, download_id, state):
        if not self._window:
            return
        data = {"download_id": download_id, "state": state}
        js_code = f"if (window.onDownloadStateChanged) window.onDownloadStateChanged({json.dumps(data)});"
        self._window.evaluate_js(js_code)

    def _check_download_status(self, download_id):
        while True:
            state = self._download_states.get(download_id, 'running')
            if state == 'cancelled':
                raise Exception("DOWNLOAD_CANCELLED")
            elif state == 'paused':
                time.sleep(0.2)
            else:
                break

    def set_window(self, window):
        self._window = window

    def get_default_folder(self):
        return self._default_download_dir

    def select_folder(self):
        if not self._window:
            return self._default_download_dir
        
        result = self._window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=self._default_download_dir
        )
        if result and len(result) > 0:
            return result[0]
        return None

    def read_clipboard(self):
        try:
            p = subprocess.Popen(['pbpaste'], stdout=subprocess.PIPE)
            p.wait()
            text = p.stdout.read().decode('utf-8').strip()
            if text.startswith('http://') or text.startswith('https://'):
                return text
        except Exception:
            pass
        return ""

    def get_pending_url(self):
        temp_file = "/tmp/mediadownloader_last_url.txt"
        if os.path.exists(temp_file):
            try:
                with open(temp_file, "r", encoding="utf-8") as f:
                    url = f.read().strip()
                try: os.remove(temp_file)
                except: pass
                if url.startswith("http://") or url.startswith("https://"):
                    return url
            except Exception:
                pass
        
        for arg in sys.argv[1:]:
            if "mediadownloader://" in arg:
                match = re.search(r'url=([^&]+)', arg)
                if match:
                    return urllib.parse.unquote(match.group(1))
            elif arg.startswith("http://") or arg.startswith("https://"):
                return arg

        return ""

    def analyze_url(self, url):
        url = url.strip()
        if not url:
            return {"error": "URL vuoto."}

        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return {"error": "URL non valido. Assicurati che inizi con http:// o https://"}

        try:
            import socket
            socket.setdefaulttimeout(6)
        except Exception:
            pass

        try:
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

            res_stream = self._analyze_stream_link(url)
            if res_stream and not res_stream.get('error'):
                return res_stream
        except Exception as ex:
            print("Fast fallback analysis trigger:", ex)

        return {
            "type": "hls" if (".m3u8" in url.lower() or "streamingcommunity" in url.lower() or "vixcloud" in url.lower()) else "stream",
            "title": f"Video Stream ({parsed.netloc})",
            "url": url,
            "thumbnail": None,
            "file_size": "Contenuto Rilevato",
            "source": parsed.netloc,
            "duration": "N/D",
            "headers": self._browser_headers
        }

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

    def copy_to_clipboard(self, text):
        if not text:
            return False
        try:
            p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            p.communicate(input=text.encode('utf-8'))
            return True
        except Exception:
            return False

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
        # Handle direct Vixcloud URLs (playlist, embed, iframe)
        if 'vixcloud.co' in url.lower():
            parsed_v = urllib.parse.urlparse(url)
            embed_id_match = re.search(r'/(?:playlist|embed|iframe)/(\d+)', url)
            embed_id = embed_id_match.group(1) if embed_id_match else ""
            referer_header = f"https://vixcloud.co/embed/{embed_id}" if embed_id else "https://vixcloud.co/"
            
            full_m3u8 = url
            if 'playlist' in url and '.m3u8' not in parsed_v.path:
                if not parsed_v.path.endswith('.m3u8'):
                    new_path = parsed_v.path + '.m3u8'
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
            session = requests.Session()
            session.headers.update(self._browser_headers)

            res1 = session.get(url, timeout=6)
            if res1.status_code != 200:
                return None

            inertia_match = re.search(r'data-page=\"(.*?)\"', res1.text)
            if not inertia_match:
                inertia_match = re.search(r"data-page='(.*?)'", res1.text)

            if not inertia_match:
                return None

            data_json = html_module.unescape(inertia_match.group(1))
            data = json.loads(data_json)
            props = data.get('props', {})

            embed_url = props.get('embedUrl')
            media_info = props.get('title') or props.get('media') or props.get('loadedTitle') or {}
            title_name = media_info.get('name') or media_info.get('title') or 'Film/Serie Streaming'

            # Parse requested episode ID or season/ep numbers from query parameters
            parsed_input = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_input.query)

            req_ep_id = None
            if 'e' in query_params:
                req_ep_id = query_params['e'][0]
            elif 'episode' in query_params:
                req_ep_id = query_params['episode'][0]

            req_season_num = int(query_params.get('s', ['0'])[0]) if 's' in query_params else None
            req_ep_num = int(query_params.get('ep', ['0'])[0]) if 'ep' in query_params else None

            if not embed_url and 'loadedTitle' in props:
                loaded = props['loadedTitle']
                title_id = loaded.get('id')
                seasons = loaded.get('seasons', [])
                
                selected_ep = None
                
                # 1. Match by explicit episode ID
                if req_ep_id:
                    for s in seasons:
                        for ep in s.get('episodes', []):
                            if str(ep.get('id')) == str(req_ep_id) or str(ep.get('number')) == str(req_ep_id):
                                selected_ep = ep
                                break
                        if selected_ep: break

                # 2. Match by season & episode number
                if not selected_ep and req_season_num and req_ep_num:
                    for s in seasons:
                        if s.get('number') == req_season_num:
                            for ep in s.get('episodes', []):
                                if ep.get('number') == req_ep_num:
                                    selected_ep = ep
                                    break
                            if selected_ep: break

                # 3. Fallback to first episode if no match
                if not selected_ep and seasons and seasons[0].get('episodes'):
                    selected_ep = seasons[0]['episodes'][0]

                if selected_ep:
                    ep_id = selected_ep.get('id')
                    ep_num = selected_ep.get('number')
                    s_num = selected_ep.get('season_number', 1)
                    ep_name = selected_ep.get('name', '')
                    title_name = f"{title_name} - S{s_num}E{ep_num} {ep_name}".strip()
                    embed_url = f"https://streamingcommunity.computer/iframe/{title_id}?episode={ep_id}"

            if not embed_url:
                return None

            episode_info = props.get('episode')
            if episode_info:
                ep_num = episode_info.get('number')
                ep_name = episode_info.get('name')
                title_name = f"{title_name} - Ep. {ep_num} {ep_name}".strip()

            session.headers['Referer'] = url
            res2 = session.get(embed_url, timeout=6)

            iframe_match = re.search(r'<iframe[^>]+src=\"(.*?)\"', res2.text)
            if not iframe_match:
                iframe_match = re.search(r"<iframe[^>]+src='(.*?)'", res2.text)

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

            full_m3u8 = self._build_vix_m3u8_url(playlist_url, token, expires)

            return {
                "type": "hls",
                "title": title_name,
                "url": full_m3u8,
                "thumbnail": media_info.get('poster') or media_info.get('cover'),
                "file_size": "Stream HLS (StreamingCommunity / Vixcloud)",
                "source": "StreamingCommunity",
                "duration": f"{media_info.get('runtime', 'N/D')} min",
                "headers": {
                    'User-Agent': self._browser_headers['User-Agent'],
                    'Referer': iframe_src,
                    'Origin': 'https://vixcloud.co'
                }
            }
        except Exception as ex:
            return {"error": f"Errore decodifica StreamingCommunity: {str(ex)[:100]}"}

    def _scan_page_for_hls(self, url):
        try:
            res = requests.get(url, headers=self._browser_headers, timeout=6)
            if res.status_code != 200:
                return None

            html = res.text
            m3u8_matches = re.findall(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', html)
            
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            page_title = title_match.group(1).strip() if title_match else None

            if m3u8_matches:
                return {
                    'm3u8_url': m3u8_matches[0],
                    'title': page_title,
                    'headers': {'User-Agent': self._browser_headers['User-Agent'], 'Referer': url}
                }

            iframes = re.findall(r'<iframe[^>]+src=["\'](.*?)["\']', html, re.IGNORECASE)
            for iframe_src in iframes:
                if not iframe_src.startswith('http'):
                    iframe_src = urllib.parse.urljoin(url, iframe_src)
                try:
                    iframe_res = requests.get(iframe_src, headers=self._browser_headers, timeout=5)
                    if iframe_res.status_code == 200:
                        sub_matches = re.findall(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', iframe_res.text)
                        if sub_matches:
                            return {
                                'm3u8_url': sub_matches[0],
                                'title': page_title,
                                'headers': {'User-Agent': self._browser_headers['User-Agent'], 'Referer': iframe_src}
                            }
                except Exception:
                    continue

        except Exception:
            pass
        return None

    def _analyze_direct_link(self, url, content_type=""):
        filename = os.path.basename(urllib.parse.urlparse(url).path)
        if not filename:
            filename = "media_download"
        
        file_size_str = "Dimensione sconosciuta"
        try:
            res = requests.head(url, allow_redirects=True, headers=self._browser_headers, timeout=5)
            cl = res.headers.get('content-length')
            if cl and cl.isdigit():
                size_bytes = int(cl)
                file_size_str = self._format_size(size_bytes)
        except Exception:
            pass

        return {
            "type": "direct",
            "title": filename,
            "url": url,
            "thumbnail": None,
            "file_size": file_size_str,
            "source": urllib.parse.urlparse(url).netloc,
            "duration": None
        }

    def _analyze_stream_link(self, url):
        parsed = urllib.parse.urlparse(url)
        headers_to_use = self._browser_headers.copy()
        
        if 'vixcloud.co' in url.lower() or 'playlist' in url.lower():
            embed_id_match = re.search(r'/(?:playlist|embed|iframe)/(\d+)', url)
            embed_id = embed_id_match.group(1) if embed_id_match else ""
            if embed_id:
                headers_to_use['Referer'] = f"https://vixcloud.co/embed/{embed_id}"
                headers_to_use['Origin'] = "https://vixcloud.co"

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'allow_unplayable_formats': True,
            'http_headers': headers_to_use
        }
        if 'Referer' in headers_to_use:
            ydl_opts['referer'] = headers_to_use['Referer']

        if ('vixcloud' in url or 'playlist' in url) and '.m3u8' not in parsed.path:
            if not parsed.path.endswith('.m3u8'):
                new_path = parsed.path + '.m3u8'
                url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, new_path, parsed.params, parsed.query, parsed.fragment))

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if 'entries' in info:
                    info = info['entries'][0]

                title = info.get('title', 'Contenuto Multimediale Web')
                thumbnail = info.get('thumbnail')
                duration_sec = info.get('duration')
                duration_str = self._format_duration(duration_sec) if duration_sec else "Stream Web"
                uploader = info.get('uploader') or info.get('extractor_key') or parsed.netloc
                file_size_est = info.get('filesize') or info.get('filesize_approx')
                size_str = self._format_size(file_size_est) if file_size_est else "Dimensione stimata N/D"

                return {
                    "type": "hls" if (".m3u8" in url or "playlist" in url) else "stream",
                    "title": title,
                    "url": url,
                    "thumbnail": thumbnail,
                    "duration": duration_str,
                    "source": uploader,
                    "file_size": size_str,
                    "headers": headers_to_use
                }
        except Exception as ex:
            err_msg = str(ex)
            if "Unsupported URL" in err_msg or "403" in err_msg:
                return self._analyze_direct_link(url)
            return {"error": f"Impossibile analizzare la pagina web: {err_msg[:120]}"}

    def start_download(self, url, media_type, format_choice, output_dir, custom_title=None, custom_headers=None):
        if not output_dir or not os.path.exists(output_dir):
            output_dir = self._default_download_dir

        download_id = f"dl_{int(time.time() * 1000)}"
        self._download_states[download_id] = 'running'

        thread = threading.Thread(
            target=self._run_download,
            args=(download_id, url, media_type, format_choice, output_dir, custom_title, custom_headers),
            daemon=True
        )
        thread.start()

        return {"download_id": download_id, "status": "started"}

    def _run_download(self, download_id, url, media_type, format_choice, output_dir, custom_title=None, custom_headers=None):
        if media_type == "direct":
            self._download_direct_file(download_id, url, output_dir)
        else:
            self._download_stream_yt(download_id, url, format_choice, output_dir, custom_title, custom_headers)

    def _download_direct_file(self, download_id, url, output_dir):
        filepath = None
        try:
            filename = os.path.basename(urllib.parse.urlparse(url).path)
            if not filename or '.' not in filename:
                filename = f"media_{download_id}.mp4"

            filepath = os.path.join(output_dir, filename)

            # Controlla se il server supporta download multi-thread (HTTP Range)
            total_size = 0
            accept_ranges = False
            try:
                head_res = requests.head(url, allow_redirects=True, headers=self._browser_headers, timeout=6)
                if head_res.status_code == 200:
                    cl = head_res.headers.get('content-length')
                    if cl and cl.isdigit():
                        total_size = int(cl)
                    accept_ranges = head_res.headers.get('accept-ranges', '').lower() == 'bytes'
            except Exception:
                pass

            # Usa multi-threading per file grandi (>10MB) che supportano Range
            if accept_ranges and total_size > 10 * 1024 * 1024:
                self._download_direct_multithread(download_id, url, filepath, total_size, num_threads=4)
            else:
                self._download_direct_singlethread(download_id, url, filepath, total_size)

            self._check_download_status(download_id)
            self._notify_progress(download_id, 100.0, 0, total_size, total_size, force=True)
            self._notify_complete(download_id, filepath, filename)
        except Exception as ex:
            if "DOWNLOAD_CANCELLED" in str(ex) or self._download_states.get(download_id) == 'cancelled':
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                self._notify_state_change(download_id, 'cancelled')
            else:
                self._notify_error(download_id, str(ex))

    def _download_direct_multithread(self, download_id, url, filepath, total_size, num_threads=4):
        part_size = total_size // num_threads
        ranges = []
        for i in range(num_threads):
            start = i * part_size
            end = (start + part_size - 1) if i < num_threads - 1 else (total_size - 1)
            ranges.append((start, end))

        downloaded_bytes = 0
        downloaded_lock = threading.Lock()
        start_time = time.time()

        # Pre-alloca il file della dimensione finale
        with open(filepath, 'wb') as f:
            f.truncate(total_size)

        def download_chunk(start, end):
            nonlocal downloaded_bytes
            headers = self._browser_headers.copy()
            headers['Range'] = f'bytes={start}-{end}'
            res = requests.get(url, stream=True, headers=headers, timeout=15)
            res.raise_for_status()

            with open(filepath, 'r+b') as f:
                f.seek(start)
                for chunk in res.iter_content(chunk_size=1048576):
                    self._check_download_status(download_id)
                    if chunk:
                        f.write(chunk)
                        with downloaded_lock:
                            downloaded_bytes += len(chunk)
                            current_downloaded = downloaded_bytes
                        
                        elapsed = time.time() - start_time
                        speed = current_downloaded / elapsed if elapsed > 0 else 0
                        percent = (current_downloaded / total_size * 100) if total_size > 0 else 0
                        self._notify_progress(download_id, percent, speed, current_downloaded, total_size)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(download_chunk, start, end) for start, end in ranges]
            for future in concurrent.futures.as_completed(futures):
                future.result()

    def _download_direct_singlethread(self, download_id, url, filepath, total_size=0):
        res = requests.get(url, stream=True, headers=self._browser_headers, timeout=15)
        res.raise_for_status()

        if not total_size:
            cl = res.headers.get('content-length')
            if cl and cl.isdigit():
                total_size = int(cl)

        downloaded = 0
        start_time = time.time()

        with open(filepath, 'wb') as f:
            for chunk in res.iter_content(chunk_size=1048576):
                self._check_download_status(download_id)
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    elapsed = time.time() - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    percent = (downloaded / total_size * 100) if total_size > 0 else 0
                    
                    self._notify_progress(download_id, percent, speed, downloaded, total_size)

    def _download_stream_yt(self, download_id, url, format_choice, output_dir, custom_title=None, custom_headers=None):
        if custom_title:
            safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title).strip()
            out_tmpl = os.path.join(output_dir, f"{safe_title}.%(ext)s")
        else:
            out_tmpl = os.path.join(output_dir, '%(title)s.%(ext)s')

        if ("playlist" in url or "vixcloud" in url) and ".m3u8" not in url:
            parsed = urllib.parse.urlparse(url)
            if not parsed.path.endswith('.m3u8'):
                new_path = parsed.path + '.m3u8'
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

                self._notify_progress(download_id, overall_percent, speed, downloaded, total)

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
            import shutil
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
            if ffmpeg_path:
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
        else:
            if ffmpeg_path:
                ydl_opts.update({
                    'format': 'bv*+ba/b/best',
                    'merge_output_format': 'mp4',
                    'postprocessor_args': {
                        'ffmpeg': ['-c:v', 'copy', '-c:a', 'aac']
                    }
                })
            else:
                ydl_opts.update({
                    'format': 'b/best'
                })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    base, _ = os.path.splitext(filename)
                    if os.path.exists(base + '.mp4'):
                        filename = base + '.mp4'
                    elif os.path.exists(base + '.mkv'):
                        filename = base + '.mkv'
                    elif os.path.exists(base + '.mp3'):
                        filename = base + '.mp3'
                self._notify_progress(download_id, 100.0, 0, 0, 0, force=True)
                self._notify_complete(download_id, filename, os.path.basename(filename))
        except Exception as ex:
            if "DOWNLOAD_CANCELLED" in str(ex) or self._download_states.get(download_id) == 'cancelled':
                self._notify_state_change(download_id, 'cancelled')
            else:
                self._notify_error(download_id, str(ex))

    def _notify_progress(self, download_id, percent, speed_bytes, downloaded_bytes, total_bytes, force=False):
        if not self._window:
            return
        
        now = time.time()
        last_time = self._last_progress_time.get(download_id, 0)
        # Throttling notifiche GUI: invia l'aggiornamento JS al massimo ogni 100ms (10 Hz)
        if not force and (now - last_time < 0.1) and percent < 100:
            return
        self._last_progress_time[download_id] = now
        
        speed_str = f"{self._format_size(speed_bytes)}/s"
        downloaded_str = self._format_size(downloaded_bytes)
        total_str = self._format_size(total_bytes) if total_bytes > 0 else "N/D"

        data = {
            "download_id": download_id,
            "percent": round(percent, 1),
            "speed": speed_str,
            "downloaded": downloaded_str,
            "total": total_str
        }

        js_code = f"if (window.onProgressUpdate) window.onProgressUpdate({json.dumps(data)});"
        self._window.evaluate_js(js_code)

    def _notify_complete(self, download_id, filepath, filename):
        if not self._window:
            return

        data = {
            "download_id": download_id,
            "filepath": filepath,
            "filename": filename
        }

        js_code = f"if (window.onDownloadFinished) window.onDownloadFinished({json.dumps(data)});"
        self._window.evaluate_js(js_code)

    def _notify_error(self, download_id, err_msg):
        if not self._window:
            return

        data = {
            "download_id": download_id,
            "error": err_msg
        }

        js_code = f"if (window.onDownloadError) window.onDownloadError({json.dumps(data)});"
        self._window.evaluate_js(js_code)

    def open_in_finder(self, filepath):
        if filepath and os.path.exists(filepath):
            subprocess.run(["open", "-R", filepath])
            return True
        return False

    def open_file(self, filepath):
        if filepath and os.path.exists(filepath):
            subprocess.run(["open", filepath])
            return True
        return False

    def _format_size(self, size_bytes):
        if not size_bytes or size_bytes <= 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while size_bytes >= 1024 and i < len(units) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.2f} {units[i]}"

    def _format_duration(self, seconds):
        if not seconds:
            return "00:00"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def main():
    api = MediaDownloaderAPI()
    
    html_path = get_resource_path('index.html')
    css_path = get_resource_path('styles.css')
    js_path = get_resource_path('script.js')
    
    html_content = None
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        if os.path.exists(css_path):
            with open(css_path, 'r', encoding='utf-8') as f:
                css_content = f.read()
            html_content = html_content.replace('<link rel="stylesheet" href="styles.css">', f'<style>\n{css_content}\n</style>')
        if os.path.exists(js_path):
            with open(js_path, 'r', encoding='utf-8') as f:
                js_content = f.read()
            html_content = html_content.replace('<script src="script.js"></script>', f'<script>\n{js_content}\n</script>')

    if html_content:
        window = webview.create_window(
            title='Media Downloader Pro (Fast Mode)',
            html=html_content,
            width=1000,
            height=720,
            resizable=True,
            min_size=(800, 600),
            js_api=api,
            background_color='#0F172A'
        )
    else:
        window = webview.create_window(
            title='Media Downloader Pro (Fast Mode)',
            url=f'file://{html_path}',
            width=1000,
            height=720,
            resizable=True,
            min_size=(800, 600),
            js_api=api,
            background_color='#0F172A'
        )
    
    api.set_window(window)
    webview.start(debug=False)

if __name__ == '__main__':
    main()
