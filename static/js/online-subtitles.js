(function (root) {
  'use strict';
  root.mountOnlineSubtitles = function ({container,getItem,getRevision,onSelect}) {
    let request=null, revision=0, tracks=[];
    const header=document.createElement('div');header.className='online-subs__header';
    const search=document.createElement('button');search.type='button';search.textContent='Cerca sottotitoli online';
    const language=document.createElement('select');language.setAttribute('aria-label','Lingua dei sottotitoli online');language.hidden=true;
    const status=document.createElement('p');status.className='online-subs__status';status.setAttribute('role','status');
    const results=document.createElement('div');results.className='online-subs__results';
    header.append(search,language);container.append(header,status,results);
    const names={ita:'Italiano',eng:'English',spa:'Español',fre:'Français',fra:'Français',ger:'Deutsch',deu:'Deutsch',por:'Português',jpn:'日本語'};
    function render() {
      results.replaceChildren();
      const filtered=tracks.filter(track=>track.lang===language.value);
      for (const track of filtered) {
        const button=document.createElement('button');button.type='button';button.className='dropdown-option-item';button.textContent=track.name;
        button.onclick=async event=>{
          event.stopPropagation();const selection=++revision;const playback=getRevision();
          status.textContent='Caricamento sottotitoli…';button.disabled=true;
          try {
            const response=await fetch(track.uri,{signal:request?.signal});
            const body=await response.text();
            if(!response.ok||!body.startsWith('WEBVTT'))throw Error('Unavailable');
            if(selection!==revision||playback!==getRevision())return;
            onSelect(track, body);status.textContent='Sottotitoli attivati: '+(names[track.lang]||track.lang);
          } catch(error) {if(selection===revision&&error.name!=='AbortError')status.textContent='Questa traccia non è disponibile. Provane un’altra.';}
          finally {button.disabled=false;}
        };
        results.append(button);
      }
    }
    language.onchange=render;
    search.onclick=async event=>{
      event.stopPropagation();request?.abort();request=new AbortController();
      const selection=++revision;const playback=getRevision();
      tracks=[];results.replaceChildren();language.hidden=true;search.disabled=true;status.textContent='Cerco i sottotitoli per questo film o episodio…';
      try {
        const response=await fetch('/api/subtitles/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(getItem()||{}),signal:request.signal});
        const data=await response.json();
        if(selection!==revision||playback!==getRevision())return;
        if(!response.ok)throw Error(data.error||'Ricerca non disponibile');
        tracks=data.tracks||[];
        const langs=[...new Set(tracks.map(t=>t.lang))];language.replaceChildren();
        for(const lang of langs){const option=document.createElement('option');option.value=lang;option.textContent=names[lang]||lang;language.append(option);}
        language.value=langs.includes('ita')?'ita':langs.includes('eng')?'eng':langs[0]||'';
        language.hidden=!tracks.length;status.textContent=tracks.length?'OpenSubtitles · Scegli una lingua e una traccia.':'Nessun sottotitolo trovato per questo film o episodio.';render();
      } catch(error){if(selection===revision&&error.name!=='AbortError')status.textContent=error.message||'Ricerca non disponibile. Riprova.';}
      finally{if(selection===revision)search.disabled=false;}
    };
    return {reset(){revision++;request?.abort();tracks=[];results.replaceChildren();language.hidden=true;status.textContent='';search.disabled=false;}};
  };
})(window);
