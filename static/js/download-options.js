(function (root) {
  'use strict';
  let activeChoice = null;
  root.chooseDownloadOptions = function (item) {
    if (activeChoice) activeChoice();
    return new Promise(resolve => {
      const controller = new AbortController();
      const modal = document.createElement('dialog');
      modal.className = 'download-options';
      modal.setAttribute('aria-label', 'Qualità del download');
      const title = document.createElement('h2'); title.textContent = 'Scegli la qualità';
      const name = document.createElement('p'); name.className = 'download-options__name';
      name.textContent = item.download_custom_title || item.name || item.title || 'Video';
      const status = document.createElement('p'); status.className = 'download-options__status'; status.setAttribute('role','status');
      status.textContent = 'Verifico le qualità disponibili e lo stesso episodio su Guardaserie…';
      const choices = document.createElement('div'); choices.className = 'download-options__sources';
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'download-options__cancel'; cancel.textContent = 'Annulla';
      let settled = false;
      const finish = value => {
        if (settled) return;
        settled = true; controller.abort(); clearTimeout(timeout);
        window.removeEventListener('popstate', cancelForNavigation);
        modal.close(); modal.remove(); activeChoice = null; resolve(value);
      };
      const cancelForNavigation = () => finish(null);
      window.addEventListener('popstate', cancelForNavigation);
      activeChoice = () => finish(null);
      cancel.onclick = () => finish(null);
      modal.addEventListener('cancel', event => { event.preventDefault(); finish(null); });
      modal.addEventListener('click', event => { if (event.target === modal) { const rect = modal.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) finish(null); } });
      const original = {provider:item.provider === 'guardoseries' ? 'guardoseries' : 'streamingcommunity',
        label:item.provider === 'guardoseries' ? 'Guardaserie' : 'StreamingCommunity',
        url:item.current_watch_url || item.watch_url, qualities:[{value:'best',label:'Qualità originale'}]};
      function render(source) {
        choices.replaceChildren();
        {
          const section = document.createElement('section'); section.className = 'download-options__source';
          const heading = document.createElement('h3'); heading.textContent = source.label;
          const label = document.createElement('label'); label.textContent = 'Qualità';
          const select = document.createElement('select'); select.setAttribute('aria-label', `Qualità ${source.label}`);
          for (const quality of source.qualities || original.qualities) {
            const option = document.createElement('option'); option.value = quality.value; option.textContent = quality.label; select.append(option);
          }
          label.append(select);
          const download = document.createElement('button'); download.type = 'button';
          download.textContent = 'Conferma download';
          download.onclick = () => finish({url:source.url, format_choice:select.value, provider:source.provider});
          section.append(heading,label,download); choices.append(section);
        }
      }
      const timeout = setTimeout(() => { controller.abort(); if (!settled) { render(original); status.textContent = 'La verifica sta richiedendo troppo tempo. Puoi scaricare dalla fonte originale.'; } }, 45000);
      // Wait for provider matching before offering a download action.
      // Guardaserie is selected automatically when that exact episode is usable.
      modal.append(title,name,status,choices,cancel); document.body.append(modal); modal.showModal(); cancel.focus();
      fetch('/api/download/options', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(item),signal:controller.signal})
        .then(async response => { const data = await response.json(); if (!response.ok || !data.sources?.length) throw Error('Unavailable'); return data; })
        .then(data => {
          if (settled) return; clearTimeout(timeout);
          const preferred = data.sources.find(source => source.provider === 'guardoseries') ||
            data.sources.find(source => source.provider === 'streamingcommunity') || data.sources[0];
          render(preferred);
          status.textContent = preferred.provider === 'guardoseries'
            ? 'Download da Guardaserie. Scegli la qualità disponibile.'
            : 'Download da StreamingCommunity. Scegli la qualità disponibile.';
        }).catch(error => {
          if (settled || error.name === 'AbortError') return; clearTimeout(timeout);
          render(original); status.textContent = 'Non è stato possibile verificare le altre qualità. Puoi scaricare dalla fonte originale.';
        });
    });
  };
})(window);
