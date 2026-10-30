"""Read the public, server-rendered catalog used by newer source domains."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup


def source_origin(soup, fallback):
    canonical = soup.select_one('link[rel="canonical"]')
    if canonical and canonical.get('href'):
        parsed = urlsplit(canonical['href'])
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return fallback


def image_url(value, domain):
    if not value:
        return ''
    raw = str(value).strip()
    if '/t/p/' in raw:
        match = re.search(r'/t/p/([^/]+)/(.+)$', raw)
        if match:
            return f"https://image.tmdb.org/t/p/{match.group(1)}/{match.group(2)}"
        return f"https://image.tmdb.org/t/p/{raw.split('/t/p/')[-1]}"
    url = urlsplit(urljoin(domain, raw))
    if url.path.startswith('/t/p/'):
        return f"https://image.tmdb.org{url.path}"
    host = url.hostname or ''
    source = urlsplit(domain).hostname or ''
    if host.startswith('img.streaming-community.') and source.startswith('streaming-community.'):
        url = url._replace(netloc='img.' + source)
    return urlunsplit(url)


def parse_title_card(card, domain):
    name, identifier = card.get('data-title'), card.get('data-id')
    href = card.get('href', '')
    if not name or not identifier or not href.startswith('/titles/'):
        return None
    image = card.select_one('img.img-mobile') or card.select_one('img.poster-image') or card.select_one('img')
    poster = image_url(image.get('src', ''), domain) if image else ''
    cover = image_url(card.get('data-preview') or poster, domain)
    return {'id': identifier, 'name': name,
            'type': 'tv' if card.get('data-kind') in ('series', 'tv') else 'movie',
            'slug': urlsplit(href).path.split('/')[-1],
            'release_date': card.get('data-year', ''), 'score': card.get('data-imdb', ''),
            'poster': poster, 'backdrop': cover, 'cover': cover,
            'source_format': 'html', 'source': 'StreamingCommunity', 'lang': 'ita', 'flag': '🇮🇹',
            'plot': card.get('data-plot', ''), 'genres': card.get('data-category', ''),
            'title_url': urljoin(domain, href),
            'watch_url': urljoin(domain, href.rstrip('/') + '/watching')}


def parse_archive_catalog(document, domain):
    soup = BeautifulSoup(document, "html.parser")
    domain = source_origin(soup, domain)
    if not soup.select_one(".archive-page"):
        return None
    items, seen = [], set()
    for card in soup.select(".arch-grid a[data-title][data-id]"):
        item = parse_title_card(card, domain)
        if item and item["id"] not in seen:
            seen.add(item["id"]); items.append(item)
    return items


def parse_home_catalog(document, domain):
    soup = BeautifulSoup(document, "html.parser")
    domain = source_origin(soup, domain)

    sliders, all_titles = [], {}
    for heading in soup.select('.slider-title'):
        label_node = heading.select_one('.label')
        label = (label_node or heading).get_text(' ', strip=True)
        label = re.split(r'Sfoglia tutti|Nuova serie', label)[0].strip()
        name = ('Di Tendenza' if 'titoli del momento' in label.lower() else
                'Nuove Aggiunte' if 'aggiunti di recente' in label.lower() else label)
        items, seen = [], set()
        for card in heading.select('a[data-title][data-id]'):
            item = parse_title_card(card, domain)
            if item and item['id'] not in seen:
                seen.add(item['id']); items.append(item); all_titles[item['id']] = item
        if items:
            sliders.append({'name': label, 'titles': items})
        else:
            link = heading.select_one('.row-header a[href]')
            if link and link.get('href', '').startswith('/'):
                sliders.append({'name': label, 'titles': [], 'category_path': link['href']})
    if not sliders:
        return None
    featured = None
    hero = soup.select_one('.info-wrap a[data-id]')
    if hero:
        featured = all_titles.get(hero.get('data-id'))
    return {'success': True, 'source_format': 'html', 'domain': domain, 'featured': featured,
            'genres': [], 'sliders': sliders}


def parse_title_details(document, domain, identifier):
    import json
    soup = BeautifulSoup(document, 'html.parser')
    domain = source_origin(soup, domain)
    parts = []
    for script in soup.select('script'):
        text = script.string or ''
        if 'self.__next_f.push(' not in text:
            continue
        try:
            part = json.loads(text[text.index('(')+1:text.rindex(')')])
            if len(part) > 1 and isinstance(part[1], str):
                parts.append(part[1])
        except (ValueError, TypeError):
            continue
    payload = ''.join(parts)
    decoder = json.JSONDecoder()
    item = None
    for match in re.finditer(r'"item":\s*(\{)', payload):
        try:
            candidate, _ = decoder.raw_decode(payload, match.start(1))
            if str(candidate.get('id')) == str(identifier):
                item = candidate
                break
        except ValueError:
            continue
    if not item:
        return None
    canonical = soup.select_one('link[rel="canonical"]')
    canonical_path = urlsplit(canonical.get('href', '')).path if (canonical and canonical.get('href')) else f"/titles/{identifier}-{item.get('slug', '')}-streaming"
    if not canonical_path.startswith('/titles/'):
        canonical_path = f"/titles/{identifier}-{item.get('slug', '')}-streaming"
    title_url = urljoin(domain.rstrip('/') + '/', canonical_path.lstrip('/'))
    seasons = []
    match = re.search(r'"seasons":\s*(\[)', payload)
    if match:
        try:
            raw_seasons, _ = decoder.raw_decode(payload, match.start(1))
        except ValueError:
            raw_seasons = []
        for season in raw_seasons:
            sn = int(season['number'])
            episodes = []
            for ep in season.get('episodes', []):
                en = int(ep['number'])
                episodes.append({'id': f'{identifier}-{sn}-{en}', 'number': en,
                                 'name': ep.get('title') or f'Episodio {en}', 'plot': ep.get('plot', ''),
                                 'image': image_url(ep.get('still'), domain), 'duration': ep.get('duration'),
                                 'watch_url': title_url.rstrip('/') + f'/watching?s={sn}&e={en}'})
            seasons.append({'number': sn, 'name': season.get('name'), 'episodes_count': len(episodes), 'episodes': episodes})
    return {'id': str(identifier), 'name': item.get('title'), 'type': 'tv' if item.get('kind')=='series' else 'movie',
            'slug': urlsplit(title_url).path.split('/')[-1], 'title_url': title_url,
            'watch_url': title_url.rstrip('/')+'/watching', 'plot': item.get('plot', ''),
            'poster': image_url(item.get('posterUrl'), domain), 'cover': image_url(item.get('backdropUrl') or item.get('tileUrl'), domain),
            'backdrop': image_url(item.get('backdropUrl') or item.get('tileUrl'), domain), 'score': item.get('rating'),
            'release_date': item.get('releaseDate') or str(item.get('year') or ''),
            'genres': item.get('genres') or [], 'runtime': item.get('durationMin'),
            'imdb_id': item.get('imdbId'), 'tmdb_id': item.get('tmdbId'),
            'seasons': seasons, 'seasons_count': len(seasons),
            'episodes': seasons[0]['episodes'] if seasons else [], 'source_format': 'html'}


def normalize_archive_items(items, domain):
    """Map the current archive API to the app's shared title format."""
    results = []
    for item in items:
        if not isinstance(item, dict) or not item.get('id') or not item.get('title'):
            continue
        identifier = str(item['id'])
        slug = f"{identifier}-{item.get('slug', '')}-streaming"
        title_url = urljoin(domain, '/titles/' + slug)
        poster = image_url(item.get('posterUrl'), domain)
        cover = image_url(item.get('backdropUrl') or item.get('tileUrl'), domain) or poster
        results.append({'id': identifier, 'name': item['title'],
            'type': 'tv' if item.get('kind') in ('series', 'tv') else 'movie',
            'slug': slug, 'title_url': title_url, 'watch_url': title_url + '/watching',
            'poster': poster, 'cover': cover, 'backdrop': cover,
            'release_date': str(item.get('year') or ''), 'score': item.get('rating') or '',
            'plot': item.get('plot') or '', 'genres': item.get('genres') or [],
            'runtime': item.get('durationMin'), 'source_format': 'html',
            'source': 'StreamingCommunity', 'lang': 'ita', 'flag': '🇮🇹'})
    return results


def match_title(item, candidates):
    import unicodedata
    def normalize(value):
        return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().lower())
    name = normalize(item.get('name') or item.get('title') or '')
    kind = 'tv' if item.get('type') in ('tv', 'series') or item.get('current_episode_id') else 'movie'
    matches = [entry for entry in candidates if normalize(entry.get('name', '')) == name and entry.get('type') == kind]
    tmdb = item.get('tmdb_id')
    by_tmdb = [entry for entry in candidates if tmdb and str(entry.get('tmdb_id')) == str(tmdb) and entry.get('type') == kind]
    if len(by_tmdb) == 1: return by_tmdb[0]
    year = str(item.get('release_date') or item.get('year') or '')[:4]
    if year.isdigit():
        matching_year = [entry for entry in matches if str(entry.get('release_date', ''))[:4] == year]
        if matching_year: matches = matching_year
        elif any(entry.get('release_date') for entry in matches): return None
    return matches[0] if len(matches) == 1 else None
