"""On-demand public subtitle search with bounded, same-origin WebVTT delivery."""
import re
import time
import uuid
import threading
import unicodedata
from collections import OrderedDict
from urllib.parse import urlsplit, quote
import requests

ADDON = 'https://opensubtitles-v3.strem.io'
LANGUAGES = {'ita':'Italiano','eng':'English','spa':'Español','fre':'Français','fra':'Français','ger':'Deutsch','deu':'Deutsch','por':'Português','jpn':'日本語'}


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in unicodedata.normalize('NFKD', str(value or '')).casefold() if not unicodedata.combining(c)))


AMATEUR_LINE_RE = re.compile(
    r'(?:traduzi?on[ei]|sottotitol[io]|a cura di|tradott[oa]|dialoghi|revisione|adattamento|'
    r'resync|sync\b|sincronizz|timing|editing|check\b|'
    r'subs?factory|italiansubs|itasa|subspedia|subsfaction|addic7ed|opensubtitles|'
    r'italian subs addicted|iscrew|tntvillage|swsub|subscene|podnapisi|tvsubtitles|'
    r'buona visione|buon divertimento|vi aspettiamo|nostro forum|nostro sito|'
    r'unisciti a noi|canale telegram|telegram|t\.me\/|discord|facebook|instagram|twitter|'
    r'tutti i diritti|non a scopo di lucro|'
    r'\b(?:ripped|encoded|muxed|uploaded|subbed|transcribed)\s+by\b|'
    r'\b(?:downloaded|scaricato)\s+(?:from|da)\b|'
    r'\btranscript\b|'
    r'\bfansub|'
    r'support us|become vip|advertise your|contact www|'
    r'www\.[a-z0-9\-]+|'
    r'https?:\/\/|'
    r'\b[a-z0-9\.\-_]+@(?:[a-z0-9\-]+\.)+[a-z]{2,}\b|'
    r'\b[a-z0-9\-]+\.(?:com|net|org|it|me|info|io|tv|cc|ru|co|biz|sub\.it)\b)',
    re.I
)

AMATEUR_SOURCE_RE = re.compile(
    r'subs?factory|italiansubs|itasa|subspedia|subsfaction|addic7ed|'
    r'iscrew|tntvillage|fansub|traduzi?on|sub\s+by|ripped\s+by|kikka|'
    r'swsub|subscene|podnapisi|tvsubtitles|'
    r'www\.[a-z0-9\-]+|https?:\/\/|\.net\b|\.org\b|\.it\b',
    re.I
)

OFFICIAL_SOURCE_RE = re.compile(
    r'\b(?:web-?dl|web-?rip|bluray|bd-?rip|retail|official|netflix|amzn|amazon|dsnp|disney|hbo|max|itunes|apple|dvdrip)\b|'
    r'\b(?:nf|atvp)\b',
    re.I
)


def to_vtt(content):
    if len(content) > 3 * 1024 * 1024:
        raise ValueError('File di sottotitoli troppo grande')
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('cp1252')
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')
    is_webvtt = text.lstrip().startswith('WEBVTT')
    blocks = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.strip().splitlines()
        timing = next((i for i, line in enumerate(lines) if re.search(r'^\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{1,2}:\d{2}:\d{2}[,.]\d{3}', line)), None)
        if timing is None:
            continue
        stamp = lines[timing].replace(',', '.')
        caption_lines = lines[timing+1:]
        kept_lines = []
        for line in caption_lines:
            tagless = re.sub(r'<[^>]*>', '', line).strip()
            assless = re.sub(r'\{[^}]*\}', '', tagless).strip()
            if not assless:
                continue
            if AMATEUR_LINE_RE.search(assless):
                continue
            if re.fullmatch(r'\[[^\]]*(?:sub|ita|sync|traduz|release|credit)[^\]]*\]', assless, re.I):
                continue
            if re.fullmatch(r'[:=\-*~#\s]+', assless):
                continue
            kept_lines.append(tagless)
        if not kept_lines:
            continue
        caption = '\n'.join(kept_lines).replace('-->', '→')
        blocks.append(stamp + '\n' + caption)
    if not blocks:
        if is_webvtt:
            return 'WEBVTT\n\n'
        raise ValueError('Il servizio non ha restituito sottotitoli leggibili')
    return 'WEBVTT\n\n' + '\n\n'.join(blocks) + '\n'


class OnlineSubtitles:
    def __init__(self, engine, tmdb_key='', get=requests.get):
        self.engine=engine; self.tmdb_key=tmdb_key; self.get=get
        self.cache=OrderedDict(); self.files=OrderedDict(); self.loaded=OrderedDict(); self.lock=threading.Lock()

    def tmdb(self, path, **params):
        if not self.tmdb_key:
            raise ValueError('Identificativo del titolo non disponibile')
        response=self.get('https://api.themoviedb.org/3/'+path,params={**params,'api_key':self.tmdb_key},timeout=10)
        response.raise_for_status()
        return response.json()

    def identity(self, item):
        kind='series' if item.get('type') in ('tv','series') or item.get('current_episode_id') else 'movie'
        imdb=item.get('imdb_id') or ''
        tmdb=item.get('tmdb_id')
        if not re.fullmatch(r'tt\d{5,12}',str(imdb)) and not tmdb and item.get('id'):
            details=self.engine.get_title_details(str(item['id']),item.get('slug') or '')
            imdb=details.get('imdb_id') or '';tmdb=details.get('tmdb_id')
        media='tv' if kind=='series' else 'movie'
        if not re.fullmatch(r'tt\d{5,12}',str(imdb)):
            if not tmdb:
                name=item.get('name') or item.get('title') or ''
                if not name: raise ValueError('Titolo non disponibile per la ricerca')
                results=self.tmdb('search/'+media,query=name,language='it-IT').get('results',[])
                matches=[r for r in results if normalize(name) in {normalize(r.get(k)) for k in ('name','title','original_name','original_title')}]
                year=str(item.get('release_date') or item.get('year') or '')[:4]
                if year.isdigit():matches=[r for r in matches if str(r.get('first_air_date') or r.get('release_date') or '').startswith(year)]
                if len(matches)!=1: raise ValueError('Non riesco a identificare questo titolo con certezza')
                tmdb=matches[0]['id']
            if not str(tmdb).isdigit():raise ValueError('Identificativo del titolo non valido')
            imdb=self.tmdb(f'{media}/{tmdb}/external_ids').get('imdb_id')
        if not re.fullmatch(r'tt\d{5,12}',str(imdb or '')):raise ValueError('Identificativo IMDb non disponibile')
        if kind=='series':
            season=int(item.get('current_season_number') or 0);episode=int(item.get('current_episode_number') or 0)
            if season<1 or episode<1:raise ValueError('Avvia un episodio per cercarne i sottotitoli')
            return kind,f'{imdb}:{season}:{episode}'
        return kind,imdb

    @staticmethod
    def allowed(url):
        parsed=urlsplit(url)
        return (parsed.scheme=='https' and parsed.port in (None,443) and not parsed.username and not parsed.password
                and bool(re.fullmatch(r'subs\d*\.strem\.io|dl\.opensubtitles\.org',parsed.hostname or '')))

    def search(self, item):
        kind,identifier=self.identity(item);key=(kind,identifier)
        with self.lock:
            cached=self.cache.get(key)
            if cached and time.monotonic()-cached[0]<300:return cached[1]
        response=self.get(f'{ADDON}/subtitles/{kind}/{quote(identifier,safe=":")}.json',timeout=18)
        response.raise_for_status()
        subtitles=response.json().get('subtitles',[])

        def subtitle_tier(s):
            name = str(s.get('label') or s.get('movieReleaseName') or '')
            is_amateur = bool(AMATEUR_SOURCE_RE.search(name))
            is_official = bool(OFFICIAL_SOURCE_RE.search(name))
            if is_official and not is_amateur:
                return 0
            if not is_amateur:
                return 1
            return 2

        by_lang = {}
        for sub in subtitles:
            lang = sub.get('lang') or 'und'
            by_lang.setdefault(lang, []).append(sub)

        filtered_subtitles = []
        for lang, subs in by_lang.items():
            tier0 = [s for s in subs if subtitle_tier(s) == 0]
            tier1 = [s for s in subs if subtitle_tier(s) == 1]
            if tier0:
                filtered_subtitles.extend(tier0)
            elif tier1:
                filtered_subtitles.extend(tier1)
            else:
                filtered_subtitles.extend(subs)

        filtered_subtitles.sort(key=lambda s: (
            0 if s.get('lang') == 'ita' else (1 if s.get('lang') == 'eng' else 2),
            subtitle_tier(s)
        ))

        tracks = []; counts = {}; seen = set()
        with self.lock:
            for sub in filtered_subtitles:
                lang = sub.get('lang') or 'und'
                url = sub.get('url') or ''
                if not self.allowed(url) or url in seen or counts.get(lang, 0) >= 3:
                    continue
                seen.add(url)
                counts[lang] = counts.get(lang, 0) + 1
                token = uuid.uuid4().hex
                self.files[token] = {'url': url, 'vtt': None}
                tier = subtitle_tier(sub)
                lang_name = LANGUAGES.get(lang, lang)
                if tier == 0:
                    label = f"{lang_name} (Originale)" if counts[lang] == 1 else f"{lang_name} (Originale {counts[lang]})"
                else:
                    label = f"{lang_name} · Traccia {counts[lang]}"
                tracks.append({'name': label, 'lang': lang, 'uri': f'/api/subtitles/file/{token}.vtt', 'format': 'vtt', 'onlineSource': True})
            tracks.sort(key=lambda t: ({'ita': 0, 'eng': 1}.get(t['lang'], 2), t['lang']))
            tracks = tracks[:100]
            self.cache[key] = (time.monotonic(), tracks)
            while len(self.cache) > 64: self.cache.popitem(last=False)
            while len(self.files) > 10000: self.files.popitem(last=False)
        return tracks

    def load(self, token):
        with self.lock:entry=self.files.get(token)
        if not entry:raise KeyError(token)
        if entry['vtt'] is not None:return entry['vtt']
        url=entry['url']
        for _ in range(4):
            if not self.allowed(url):raise ValueError('Fonte dei sottotitoli non valida')
            with self.get(url,timeout=15,stream=True,allow_redirects=False) as response:
                if response.status_code in (301,302,303,307,308):
                    from urllib.parse import urljoin
                    url=urljoin(url,response.headers.get('Location',''));continue
                response.raise_for_status();chunks=[];size=0
                for chunk in response.iter_content(64*1024):
                    size+=len(chunk)
                    if size>3*1024*1024:raise ValueError('File di sottotitoli troppo grande')
                    chunks.append(chunk)
                vtt=to_vtt(b''.join(chunks))
                with self.lock:
                    entry['vtt']=vtt;self.loaded[token]=entry
                    while len(self.loaded)>24:
                        _,old=self.loaded.popitem(last=False);old['vtt']=None
                return vtt
        raise ValueError('File di sottotitoli non disponibile')
