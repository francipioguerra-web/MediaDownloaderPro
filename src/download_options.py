"""Only offer another provider after matching the series and exact episode."""
import re
import unicodedata
from urllib.parse import urlsplit


def normalized_title(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def matching_episode(catalog, item):
    name = normalized_title(item.get('name') or item.get('title'))
    if not name:
        return None
    results = catalog.search(item.get('name') or item.get('title'))
    matches = {entry['id']: entry for entry in results
               if entry.get('type') == 'tv' and normalized_title(entry.get('name') or entry.get('title')) == name}
    if len(matches) != 1:
        return None
    series = next(iter(matches.values()))
    details = catalog.details(series['id'])
    season_number = int(item.get('current_season_number') or 0)
    episode_number = int(item.get('current_episode_number') or 0)
    if season_number < 1 or episode_number < 1:
        return None
    season = next((s for s in details.get('seasons', []) if int(s.get('number', 0)) == season_number), {})
    episode = next((e for e in season.get('episodes', []) if int(e.get('number', 0)) == episode_number), None)
    return episode.get('watch_url') if episode else None


def quality_choices(metadata):
    heights = sorted({int(q.get('height') or 0) for q in metadata.get('qualities', []) if int(q.get('height') or 0) > 0}, reverse=True)
    return [{'value': f'{height}p', 'label': f'{height}p'} for height in heights] or [{'value': 'best', 'label': 'Qualità originale'}]


def download_options(engine, catalog, item):
    url = item.get('current_watch_url') or item.get('watch_url') or ''
    if not url:
        raise ValueError('Seleziona un episodio o un film dal catalogo')
    alternate = urlsplit(url).hostname in ('guardoseries.click', 'vixsrc.to')
    original = {'provider': 'guardoseries' if alternate else 'streamingcommunity',
                'label': 'Guardaserie' if alternate else 'StreamingCommunity', 'url': url}
    def inspect(source):
        try:
            metadata = engine.get_stream_qualities(source['url'])
            if metadata.get('error'):
                if source is not original:
                    return None
                metadata = {}
            return {**source, 'qualities': quality_choices(metadata)}
        except Exception:
            return {**source, 'qualities': quality_choices({})} if source is original else None
    def other_source():
        if alternate or item.get('type') not in ('tv', 'series'):
            return None
        try:
            match = matching_episode(catalog, item)
            return inspect({'provider': 'guardoseries', 'label': 'Guardaserie', 'url': match}) if match else None
        except Exception:
            return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as executor:
        primary = executor.submit(inspect, original)
        other = executor.submit(other_source)
        return [source for source in (primary.result(), other.result()) if source]
