"""Read the HLS URL exposed in the provider's public player configuration.

Decode literal script data only; no provider JavaScript is executed.
"""
import base64
import json
import re
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup


def readable_scripts(document):
    scripts = [s.string or s.get_text() for s in BeautifulSoup(document, 'html.parser').select('script')]
    readable = list(scripts)
    for script in scripts:
        for match in re.finditer(r"var k='([^']+)',d=atob\('([A-Za-z0-9+/=]+)'\)", script):
            key = match[1].encode()
            if not key:
                continue
            try:
                data = base64.b64decode(match[2], validate=True)
                readable.append(bytes(v ^ key[i % len(key)] for i, v in enumerate(data)).decode('utf-8'))
            except (ValueError, UnicodeError):
                continue
    return readable


def parse_player_source(document):
    for script in readable_scripts(document):
        match = re.search(r'(?:let|const|var)\s+currentSrc\s*=\s*("(?:[^"\\]|\\.)*")', script)
        if not match:
            continue
        url = json.loads(match[1])
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or '.m3u8' not in parsed.path:
            continue
        return url
    return None


def media_headers(referrer):
    parsed = urlsplit(referrer)
    return {'Referer': referrer, 'Origin': f'{parsed.scheme}://{parsed.netloc}',
            'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'cross-site'}


def parse_player_subtitles(document, referrer):
    tracks = []
    source = parse_player_source(document) or referrer
    parsed_source = urlsplit(source)
    origin = f"{parsed_source.scheme}://{parsed_source.netloc}"
    scripts = readable_scripts(document)
    for script in scripts:
        override = re.search(r'window\.__SUBS_ORIGIN\s*=\s*("(?:[^"\\]|\\.)*")', script)
        if override:
            candidate = json.loads(override[1])
            if urlsplit(candidate).scheme == "https":
                origin = candidate
    for script in scripts:
        match = re.search(r'window\.__EXTERNAL_SUBS\s*=\s*(\[)', script)
        if not match:
            continue
        try:
            raw, _ = json.JSONDecoder().raw_decode(script, match.start(1))
        except ValueError:
            continue
        for track in raw:
            if not isinstance(track, dict):
                continue
            value = track.get('url') or track.get('file')
            if not isinstance(value, str):
                continue
            url = urljoin(origin, value)
            if urlsplit(url).scheme != 'https':
                continue
            forced = track.get('forced') in (True, 'true', 'YES', 1)
            lang = track.get('lang') or track.get('language') or ''
            tracks.append({'lang': lang, 'name': lang + (' [Forced]' if forced else ''),
                           'forced': forced, 'uri': url, 'referrer': referrer})
    return tracks


def manifest_metadata(text,base,resource):
    audio=[];subtitles=[];qualities=[];lines=text.splitlines()
    for index,line in enumerate(lines):
        attrs={}
        for match in re.finditer(r'([A-Z-]+)=(?:"([^"]*)"|([^,]*))',line):attrs[match[1]]=match[2] if match[2] is not None else match[3]
        if line.startswith('#EXT-X-MEDIA:'):
            track={'id':len(audio) if attrs.get('TYPE')=='AUDIO' else len(subtitles), 'name':attrs.get('NAME',''),
                'lang':attrs.get('LANGUAGE',''),'default':attrs.get('DEFAULT')=='YES','forced':attrs.get('FORCED')=='YES',
                'uri':resource(urljoin(base,attrs['URI'])) if attrs.get('URI') else ''}
            if attrs.get('TYPE')=='AUDIO':audio.append(track)
            elif attrs.get('TYPE')=='SUBTITLES':subtitles.append(track)
        elif line.startswith('#EXT-X-STREAM-INF:') and index+1<len(lines):
            resolution=attrs.get('RESOLUTION','');height=resolution.split('x')[-1]
            qualities.append({'quality':height+'p','label':height+'p','height':int(height) if height.isdigit() else 0,
                'resolution':resolution,'stream_url':resource(urljoin(base,lines[index+1].strip()))})
    return audio,subtitles,qualities
