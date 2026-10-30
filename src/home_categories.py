"""StreamingCommunity home categories and server-rendered archive fallback."""
import json
import re
from bs4 import BeautifulSoup
from src.catalog_html import normalize_archive_items

GENRES = ['Animazione','Avventura','Azione','Commedia','Crime','Documentario','Drammatico','Famiglia','Fantascienza','Fantasy','Guerra','Horror','Mistero','Musicale','Romantico','Storico','Thriller','Western']
ALIASES = {'Dramma':'Drammatico','Storia':'Storico','Musica':'Musicale','Romance':'Romantico'}


def canonical_genre(value):
    value = ALIASES.get(str(value), str(value))
    return next((g for g in GENRES if g.casefold()==value.casefold()), None)


def home_rows(catalog):
    if catalog.get('source_format') not in ('html', 'vixcloud'): return catalog
    rows=[]
    for row in catalog.get('sliders',[]):
        if row.get('category_path') or canonical_genre(row.get('name')): continue
        name=row.get('name','');sort='updated_at'
        if catalog.get('source_format') == 'vixcloud':
            name={'trending':'I titoli del momento','latest':'Aggiunti di recente','top10':'Top 10 titoli di oggi'}.get(name,name)
        if 'momento' in name.lower():sort='moment'
        elif 'recent' in name.lower():sort='created_at'
        elif 'top 10' in name.lower():sort='popular'
        rows.append({**row,'name':name,'browse':{'sort':sort, 'upcoming':'arrivo' in name.lower()}})
    rows.extend({'name':genre,'genre':genre,'titles':[],'browse':{'genre':genre,'sort':'updated_at'}} for genre in GENRES)
    return {**catalog,'sliders':rows}


def parse_archive_state(markup, domain):
    parts=[]
    for script in BeautifulSoup(markup,'html.parser').select('script'):
        text=script.string or ''
        if 'self.__next_f.push(' not in text:continue
        try:
            value=json.loads(text[text.index('(')+1:text.rindex(')')])
            if len(value)>1 and isinstance(value[1],str):parts.append(value[1])
        except (ValueError,TypeError):pass
    payload=''.join(parts);decoder=json.JSONDecoder()
    match=re.search(r'"initial":\s*(\[)',payload)
    if not match:return None
    try:
        items,_=decoder.raw_decode(payload,match.start(1))
        count_match=re.search(r'"count":\s*(\d+)',payload)
        filter_match=re.search(r'"initialFilters":\s*(\{)',payload)
        filters=decoder.raw_decode(payload,filter_match.start(1))[0] if filter_match else {}
        opts_match=re.search(r'"opts":\s*(\{)',payload)
        opts=decoder.raw_decode(payload,opts_match.start(1))[0] if opts_match else {}
        return {'titles':normalize_archive_items(items,domain),'totalCount':int(count_match[1]) if count_match else len(items),'filters':filters,'options':opts}
    except (ValueError,TypeError):return None
