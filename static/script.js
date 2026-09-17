document.addEventListener('DOMContentLoaded', () => {
  const urlInput = document.getElementById('url-input');
  const btnPaste = document.getElementById('btn-paste');
  const btnAnalyze = document.getElementById('btn-analyze');
  const analyzeSpinner = document.getElementById('analyze-spinner');
  const alertBanner = document.getElementById('alert-banner');
  
  const activeList = document.getElementById('active-downloads-list');
  const emptyDownloadsPlaceholder = document.getElementById('empty-downloads-placeholder');
  const downloadsCountText = document.getElementById('downloads-count-text');
  const navDownloadsBadge = document.getElementById('nav-downloads-badge');
  
  // Navigation Tabs (Floating Navbar)
  const navTabDownloader = document.getElementById('nav-tab-downloader');
  const navTabScPortal = document.getElementById('nav-tab-sc-portal');
  const navTabVixcloud = document.getElementById('nav-tab-vixcloud');
  const navTabDownloads = document.getElementById('nav-tab-downloads');

  const downloaderView = document.getElementById('downloader-view');
  const scPortalView = document.getElementById('sc-portal-view');
  const vixcloudExtractorView = document.getElementById('vixcloud-extractor-view');
  const downloadsManagerView = document.getElementById('downloads-manager-view');

  // Vixcloud Extractor Elements
  const vixUrlInput = document.getElementById('vix-url-input');
  const btnVixPaste = document.getElementById('btn-vix-paste');
  const btnVixExtract = document.getElementById('btn-vix-extract');
  const vixExtractSpinner = document.getElementById('vix-extract-spinner');
  const vixExtractText = document.getElementById('vix-extract-text');
  const vixResultsSection = document.getElementById('vix-results-section');
  const vixResultTitle = document.getElementById('vix-result-title');
  const vixEmbedOutput = document.getElementById('vix-embed-output');
  const vixM3u8Output = document.getElementById('vix-m3u8-output');
  const btnCopyVixEmbed = document.getElementById('btn-copy-vix-embed');
  const btnOpenVixEmbed = document.getElementById('btn-open-vix-embed');
  const btnCopyVixM3u8 = document.getElementById('btn-copy-vix-m3u8');
  const vixQualitiesList = document.getElementById('vix-qualities-list');
  const btnVixDownloadDirect = document.getElementById('btn-vix-download-direct');

  // Portal Elements
  const scDomainBadge = document.getElementById('sc-domain-badge');
  const btnRefreshDomain = document.getElementById('btn-refresh-domain');
  const scSearchInput = document.getElementById('sc-search-input');
  const scSearchBtn = document.getElementById('sc-search-btn');
  const scCatalogContainer = document.getElementById('sc-catalog-container');
  const scCatalogGrid = document.getElementById('sc-catalog-grid');
  const scResultsTitle = document.getElementById('sc-results-title');
  const scDetailsModal = document.getElementById('sc-details-modal');
  const btnCloseDetailsModal = document.getElementById('btn-close-details-modal');
  const scDetailsTypeBadge = document.getElementById('sc-details-type-badge');
  const scDetailsCard = document.getElementById('sc-details-card');
  const scSeasonsSection = document.getElementById('sc-seasons-section');
  const scSeasonsTabs = document.getElementById('sc-seasons-tabs');
  const scEpisodesGrid = document.getElementById('sc-episodes-grid');

  // Modal Popup Elements
  const qualityModal = document.getElementById('quality-modal');
  const modalMediaTitle = document.getElementById('modal-media-title');
  const modalQualityOptions = document.getElementById('modal-quality-options');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnCancelModal = document.getElementById('btn-cancel-modal');
  const btnConfirmDownload = document.getElementById('btn-confirm-download');

  let currentScDomain = "https://streamingcommunityz.luxe";
  let modalSelectedTarget = null;
  let currentExtractedData = null;
  let activeDownloadsCount = 0;

  // TAB SWITCHING
  function switchTab(tabName) {
    [navTabScPortal, navTabDownloader, navTabVixcloud, navTabDownloads].forEach(tab => {
      if (tab) tab.classList.remove('active');
    });

    [scPortalView, downloaderView, vixcloudExtractorView, downloadsManagerView].forEach(view => {
      if (view) view.classList.add('hidden');
    });

    if (tabName === 'downloader') {
      if (navTabDownloader) navTabDownloader.classList.add('active');
      if (downloaderView) downloaderView.classList.remove('hidden');
    } else if (tabName === 'vixcloud') {
      if (navTabVixcloud) navTabVixcloud.classList.add('active');
      if (vixcloudExtractorView) vixcloudExtractorView.classList.remove('hidden');
    } else if (tabName === 'downloads') {
      if (navTabDownloads) navTabDownloads.classList.add('active');
      if (downloadsManagerView) downloadsManagerView.classList.remove('hidden');
    } else {
      if (navTabScPortal) navTabScPortal.classList.add('active');
      if (scPortalView) scPortalView.classList.remove('hidden');
      initScPortal();
    }
  }

  if (navTabDownloader) navTabDownloader.addEventListener('click', () => switchTab('downloader'));
  if (navTabScPortal) navTabScPortal.addEventListener('click', () => switchTab('sc-portal'));
  if (navTabVixcloud) navTabVixcloud.addEventListener('click', () => switchTab('vixcloud'));
  if (navTabDownloads) navTabDownloads.addEventListener('click', () => switchTab('downloads'));

  // PASTE URL LOGIC
  if (btnPaste && urlInput) {
    btnPaste.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) urlInput.value = text;
      } catch (e) {}
    });
  }

  if (btnVixPaste && vixUrlInput) {
    btnVixPaste.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) vixUrlInput.value = text;
      } catch (e) {}
    });
  }

  if (btnAnalyze) {
    btnAnalyze.addEventListener('click', () => {
      const u = urlInput ? urlInput.value.trim() : '';
      if (!u) {
        showAlert("Per favore incolla un URL valido prima di analizzare.");
        return;
      }
      openQualityModal({ title: "Video da URL Diretto", url: u });
    });
  }

  // PORTAL LOGIC: LOAD HOME ON STARTUP
  let portalInitialized = false;
  async function initScPortal() {
    if (portalInitialized) return;
    portalInitialized = true;
    renderContinueWatchingSection();
    await refreshActiveDomain();
    loadHomeCatalog();
  }

  async function refreshActiveDomain() {
    if (scDomainBadge) scDomainBadge.textContent = "Verifica dominio attivo in corso...";
    try {
      const res = await fetch('/api/sc/domain');
      const data = await res.json();
      if (data.domain) {
        currentScDomain = data.domain;
        const cleanHost = data.domain.replace(/^https?:\/\//, '');
        if (scDomainBadge) scDomainBadge.textContent = `Dominio Attivo: ${cleanHost}`;
      }
    } catch (e) {
      if (scDomainBadge) scDomainBadge.textContent = "Connessione al sito in corso...";
    }
  }

  if (btnRefreshDomain) {
    btnRefreshDomain.addEventListener('click', async () => {
      portalInitialized = false;
      await refreshActiveDomain();
      showAlert("Riconnessione al dominio completata!");
      setTimeout(hideAlert, 2500);
    });
  }

  // SEARCH & HOME SLIDERS LOGIC
  const scHomeSlidersContainer = document.getElementById('sc-home-sliders-container');
  let searchDebounceTimer = null;

  if (scSearchInput) {
    scSearchInput.addEventListener('input', () => {
      if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => {
        const q = scSearchInput.value.trim();
        if (q.length >= 2) {
          searchCatalog(q);
        } else if (q.length === 0) {
          loadHomeCatalog();
        }
      }, 200);
    });

    scSearchInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        const q = scSearchInput.value.trim();
        if (q) searchCatalog(q);
        else loadHomeCatalog();
      }
    });
  }

  if (scSearchBtn) {
    scSearchBtn.addEventListener('click', () => {
      const q = scSearchInput ? scSearchInput.value.trim() : '';
      if (q) searchCatalog(q);
      else loadHomeCatalog();
    });
  }

  async function loadHomeCatalog() {
    if (!scHomeSlidersContainer) return;
    scHomeSlidersContainer.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:center; gap:12px; padding:60px 0;">
        <div class="spinner"></div>
        <span>Caricamento Home Page StreamingCommunity in corso...</span>
      </div>
    `;

    try {
      const r = await fetch('/api/sc/home');
      const data = await r.json();
      renderHomeSliders(data.sliders || []);
    } catch (e) {
      if (scHomeSlidersContainer) {
        scHomeSlidersContainer.innerHTML = `<div style="color: var(--text-muted); padding: 40px; text-align: center;">Errore nel caricamento della Home Page.</div>`;
      }
    }
  }

  async function searchCatalog(query) {
    if (!scHomeSlidersContainer) return;
    scHomeSlidersContainer.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:center; gap:12px; padding:60px 0;">
        <div class="spinner"></div>
        <span>Ricerca in corso su StreamingCommunity per "${escapeHtml(query)}"...</span>
      </div>
    `;

    try {
      const r = await fetch('/api/sc/search', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ query: query })
      });
      const data = await r.json();
      const results = data.results || [];

      scHomeSlidersContainer.innerHTML = "";
      const sec = document.createElement('div');
      sec.className = 'slider-section';

      const header = document.createElement('div');
      header.className = 'slider-header';
      header.innerHTML = `<h3 class="slider-title">🔍 Risultati della ricerca per "${escapeHtml(query)}" (${results.length})</h3>`;
      sec.appendChild(header);

      if (results.length === 0) {
        const noRes = document.createElement('div');
        noRes.style.cssText = 'color: var(--text-muted); padding: 30px 0;';
        noRes.textContent = 'Nessun risultato trovato.';
        sec.appendChild(noRes);
      } else {
        const grid = document.createElement('div');
        grid.className = 'sc-grid';
        results.forEach(item => {
          const cardEl = createCardElement(item);
          cardEl.addEventListener('click', () => showMediaDetailsModal(item));
          grid.appendChild(cardEl);
        });
        sec.appendChild(grid);
      }

      scHomeSlidersContainer.appendChild(sec);
    } catch (e) {
      if (scHomeSlidersContainer) {
        scHomeSlidersContainer.innerHTML = `<div style="color: var(--text-muted); padding: 40px; text-align: center;">Errore durante la ricerca.</div>`;
      }
    }
  }

  // CARD FOOTER & ACTION BAR HELPERS
  function createCardFooterHtml(item) {
    const flag = item.flag || (item.lang === 'eng' ? '🇬🇧' : '🇮🇹');
    const sourceLabel = item.source || 'StreamingCommunity';

    return `
      <div class="card-footer-info">
        <div class="card-footer-title">${escapeHtml(item.name)}</div>
        <div class="card-footer-meta">
          <span class="lang-flag-badge">${flag}</span>
          <span class="source-tag-label">${escapeHtml(sourceLabel)}</span>
        </div>
        <div class="card-action-btns">
          <button class="card-action-icon play-btn btn-action-play" title="Riproduci Streaming (${flag})">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
          </button>
          <button class="card-action-icon icon-btn btn-action-download" title="Scarica MP4 (${flag})">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          </button>
          <button class="card-action-icon icon-btn btn-action-info" title="Dettagli e Puntate">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
          </button>
        </div>
      </div>
    `;
  }

  function bindCardActionEvents(containerEl, item) {
    if (!containerEl || !item) return;

    const playBtn = containerEl.querySelector('.btn-action-play');
    const downloadBtn = containerEl.querySelector('.btn-action-download');
    const infoBtn = containerEl.querySelector('.btn-action-info');

    const watchUrl = item.watch_url || `${currentScDomain}/it/watch/${item.id}`;

    if (playBtn) {
      playBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openStreamPlayerModal({
          title: item.name,
          url: watchUrl
        });
      });
    }

    if (downloadBtn) {
      downloadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openQualityModal({
          title: item.name,
          url: watchUrl
        });
      });
    }

    if (infoBtn) {
      infoBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        loadTitleDetails(item);
      });
    }
  }

  function renderHomeSliders(sliders) {
    if (!scHomeSlidersContainer) return;
    scHomeSlidersContainer.innerHTML = "";

    if (!sliders || sliders.length === 0) {
      scHomeSlidersContainer.innerHTML = `<div style="color: var(--text-muted); padding: 40px; text-align: center;">Nessuna categoria disponibile al momento.</div>`;
      return;
    }

    sliders.forEach(slider => {
      if (!slider.items || slider.items.length === 0) return;

      const sec = document.createElement('div');
      sec.className = 'slider-section';
      sec.id = `slider-${slider.id}`;

      const header = document.createElement('div');
      header.className = 'slider-header';
      header.innerHTML = `
        <h3 class="slider-title">${escapeHtml(slider.title)}</h3>
        <div class="slider-nav">
          <button class="slider-nav-btn slider-prev-btn" title="Scorri a sinistra">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"></polyline></svg>
          </button>
          <button class="slider-nav-btn slider-next-btn" title="Scorri a destra">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>
          </button>
        </div>
      `;

      const row = document.createElement('div');
      row.className = 'slider-row';

      if (slider.is_top10) {
        slider.items.slice(0, 10).forEach((item, idx) => {
          const itemWrap = document.createElement('div');
          itemWrap.className = 'top10-item-wrapper';
          itemWrap.innerHTML = `
            <div class="top10-rank-num">${idx + 1}</div>
            <div class="sc-card top10-card">
              <div class="sc-card-poster-wrap">
                <img src="${item.poster || 'https://via.placeholder.com/200x300?text=No+Cover'}" alt="${escapeAttr(item.name)}" class="sc-card-poster" />
              </div>
              ${createCardFooterHtml(item)}
            </div>
          `;
          itemWrap.addEventListener('click', () => loadTitleDetails(item));
          bindCardActionEvents(itemWrap, item);
          row.appendChild(itemWrap);
        });
      } else {
        slider.items.forEach(item => {
          const cardEl = createCardElement(item);
          cardEl.addEventListener('click', () => loadTitleDetails(item));
          bindCardActionEvents(cardEl, item);
          row.appendChild(cardEl);
        });
      }

      sec.appendChild(header);
      sec.appendChild(row);
      scHomeSlidersContainer.appendChild(sec);

      // Scroll handlers
      const prevBtn = header.querySelector('.slider-prev-btn');
      const nextBtn = header.querySelector('.slider-next-btn');
      if (prevBtn && nextBtn) {
        prevBtn.addEventListener('click', () => {
          row.scrollBy({ left: -480, behavior: 'smooth' });
        });
        nextBtn.addEventListener('click', () => {
          row.scrollBy({ left: 480, behavior: 'smooth' });
        });
      }
    });
  }

  function createCardElement(item) {
    const card = document.createElement('div');
    card.className = 'sc-card';
    card.innerHTML = `
      <div class="sc-card-poster-wrap">
        <img src="${item.poster || 'https://via.placeholder.com/200x300?text=No+Cover'}" alt="${escapeAttr(item.name)}" class="sc-card-poster" />
      </div>
      ${createCardFooterHtml(item)}
    `;
    return card;
  }

  function renderCatalogCards(results) {
    if (!scCatalogGrid) return;
    scCatalogGrid.innerHTML = "";

    if (!results || results.length === 0) {
      const msg = "Nessun risultato trovato per la ricerca.";
      scCatalogGrid.innerHTML = `<div style="grid-column: 1/-1; color: var(--text-muted); text-align: center; padding: 40px 0;">${msg}</div>`;
      return;
    }

    results.forEach(item => {
      const cardEl = createCardElement(item);
      cardEl.addEventListener('click', () => loadTitleDetails(item));
      bindCardActionEvents(cardEl, item);
      scCatalogGrid.appendChild(cardEl);
    });
  }

  function closeDetailsModal() {
    if (scDetailsModal) scDetailsModal.classList.add('hidden');
  }

  if (scDetailsModal) {
    scDetailsModal.addEventListener('click', (e) => {
      if (e.target === scDetailsModal) {
        closeDetailsModal();
      }
    });
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && scDetailsModal && !scDetailsModal.classList.contains('hidden')) {
      closeDetailsModal();
    }
  });

  function showMediaDetailsModal(item) {
    if (!item) return;
    loadTitleDetails(item);
  }

  async function loadTitleDetails(itemOrId, maybeSlug) {
    let titleId = null;
    let slug = '';
    let itemObj = null;

    if (typeof itemOrId === 'object' && itemOrId !== null) {
      itemObj = itemOrId;
      titleId = itemObj.id;
      slug = itemObj.slug || '';
    } else {
      titleId = itemOrId;
      slug = maybeSlug || '';
    }

    if (!titleId) return;

    if (scDetailsModal) scDetailsModal.classList.remove('hidden');

    const isMovieInitial = itemObj ? (itemObj.type === 'movie') : false;
    if (scDetailsTypeBadge) scDetailsTypeBadge.textContent = isMovieInitial ? 'Film' : 'Media';

    let activeFlag = (itemObj && itemObj.flag) ? itemObj.flag : (itemObj && itemObj.lang === 'eng' ? '🇬🇧' : '🇮🇹');
    let activeSource = (itemObj && itemObj.source) ? itemObj.source : 'StreamingCommunity';
    let currentWatchUrl = itemObj ? (itemObj.watch_url || `${currentScDomain}/it/watch/${titleId}`) : `${currentScDomain}/it/watch/${titleId}`;

    function renderLangSelectorHtml(det) {
      const allSources = [];
      // 1. Italian source
      const hasIta = det ? (det.dub_ita !== false) : true;
      if (hasIta) {
        allSources.push({
          id: 'sc-ita',
          name: 'Italiano (Doppiato)',
          flag: '🇮🇹',
          url: (det && det.domain) ? `${det.domain}/it/watch/${titleId}` : `${currentScDomain}/it/watch/${titleId}`
        });
      }
      // 2. Original audio on SC
      if (det && det.audio_orig) {
        allSources.push({
          id: 'sc-orig',
          name: 'Audio Originale (ENG)',
          flag: '🇬🇧',
          url: `${(det && det.domain) || currentScDomain}/it/watch/${titleId}?audio=orig`
        });
      }
      // 3. Alternate sources (like TMDB / VidSrc / LookMovie)
      const alts = (det && det.alt_sources && det.alt_sources.length > 0) ? det.alt_sources : (itemObj && itemObj.alt_sources ? itemObj.alt_sources : []);
      alts.forEach((alt, idx) => {
        allSources.push({
          id: `alt-${idx}`,
          name: alt.lang === 'eng' ? 'English HD (VidSrc/LookMovie)' : alt.name,
          flag: alt.flag || '🇬🇧',
          url: alt.watch_url
        });
      });

      if (allSources.length <= 1 && (!det || !det.sub_ita)) return '';

      let html = `
        <div class="modal-lang-selector" style="margin-top: 10px;">
          <span style="font-size:0.78rem; color:var(--text-dim); font-weight:600;">Lingua Audio:</span>
          <div class="lang-switch-group">
      `;

      allSources.forEach((src, idx) => {
        html += `
          <button class="lang-switch-btn ${idx === 0 ? 'active' : ''}" data-url="${escapeAttr(src.url)}" data-flag="${src.flag}">
            ${src.flag} ${escapeHtml(src.name)}
          </button>
        `;
      });

      html += `</div></div>`;

      // Subtitles selector
      if (det && det.sub_ita) {
        html += `
          <div class="modal-lang-selector" style="margin-top: 6px;">
            <span style="font-size:0.78rem; color:var(--text-dim); font-weight:600;">Sottotitoli:</span>
            <div class="lang-switch-group">
              <button class="lang-switch-btn active sub-toggle-btn" data-sub="off">🚫 Disattivati</button>
              <button class="lang-switch-btn sub-toggle-btn" data-sub="it">💬 Italiano</button>
            </div>
          </div>
        `;
      }

      return html;
    }

    function bindLangSelectorEvents(containerEl) {
      if (!containerEl) return;
      const btns = containerEl.querySelectorAll('.lang-switch-btn:not(.sub-toggle-btn)');
      btns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          btns.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');

          const newUrl = btn.getAttribute('data-url');
          const newFlag = btn.getAttribute('data-flag') || '🇮🇹';
          if (newUrl) {
            currentWatchUrl = newUrl;
            activeFlag = newFlag;
          }

          // Update buttons text
          const streamBtn = containerEl.querySelector('#btn-stream-modal-quick') || containerEl.querySelector('#btn-stream-movie');
          const dlBtn = containerEl.querySelector('#btn-download-modal-quick') || containerEl.querySelector('#btn-download-movie');
          if (streamBtn) streamBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Guarda in Streaming (${activeFlag})`;
          if (dlBtn) dlBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg> Scarica in MP4 (${activeFlag})`;
        });
      });

      const subBtns = containerEl.querySelectorAll('.sub-toggle-btn');
      subBtns.forEach(sb => {
        sb.addEventListener('click', (e) => {
          e.stopPropagation();
          subBtns.forEach(b => b.classList.remove('active'));
          sb.classList.add('active');
          const subType = sb.getAttribute('data-sub');
          if (subType === 'it') {
            showToast("💬 Sottotitoli Italiano attivati");
            if (!currentWatchUrl.includes('sub=it')) {
              currentWatchUrl += (currentWatchUrl.includes('?') ? '&' : '?') + 'sub=it';
            }
          } else {
            showToast("🚫 Sottotitoli disattivati");
            currentWatchUrl = currentWatchUrl.replace('&sub=it', '').replace('?sub=it', '');
          }
        });
      });
    }

    // 1. Instant optimistic render if itemObj exists
    if (itemObj && scDetailsCard) {
      scDetailsCard.innerHTML = `
        <img src="${itemObj.poster || itemObj.cover || 'https://via.placeholder.com/200x300'}" alt="Poster" class="sc-hero-poster">
        <div class="sc-hero-info">
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <span class="sc-card-type">${isMovieInitial ? 'Film' : 'Serie TV'}</span>
            <span class="lang-flag-badge">${activeFlag}</span>
            <span class="source-tag-label" style="font-size:0.75rem;">${escapeHtml(activeSource)}</span>
            <span id="sc-modal-seasons-badge" style="font-size:0.8rem; color: var(--text-dim);">${itemObj.release_date || ''}</span>
          </div>
          <h2 class="sc-hero-title">${escapeHtml(itemObj.name || 'Titolo')}</h2>
          <p id="sc-modal-plot" class="sc-hero-plot">${escapeHtml(itemObj.plot || 'Caricamento trama e informazioni...')}</p>

          ${renderLangSelectorHtml(null)}

          <div style="margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
            <button id="btn-stream-modal-quick" class="btn-secondary btn-large" style="background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4);">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
              Guarda in Streaming (${activeFlag})
            </button>
            <button id="btn-download-modal-quick" class="btn-primary btn-large">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
              Scarica in MP4 (${activeFlag})
            </button>
          </div>
        </div>
      `;

      bindLangSelectorEvents(scDetailsCard);

      const btnStreamQuick = document.getElementById('btn-stream-modal-quick');
      if (btnStreamQuick) {
        btnStreamQuick.onclick = () => {
          closeDetailsModal();
          openStreamPlayerModal({
            title: itemObj.name,
            url: currentWatchUrl
          });
        };
      }

      const btnDownloadQuick = document.getElementById('btn-download-modal-quick');
      if (btnDownloadQuick) {
        btnDownloadQuick.onclick = () => {
          openQualityModal({
            title: itemObj.name,
            url: currentWatchUrl
          });
        };
      }
    } else if (scDetailsCard) {
      scDetailsCard.innerHTML = `
        <div style="display:flex; align-items:center; justify-content:center; gap:12px; padding:30px 0; width:100%;">
          <div class="spinner"></div>
          <span>Caricamento informazioni e puntate...</span>
        </div>
      `;
    }

    if (scSeasonsSection) {
      if (isMovieInitial) {
        scSeasonsSection.classList.add('hidden');
      } else {
        scSeasonsSection.classList.remove('hidden');
        if (scEpisodesGrid) {
          scEpisodesGrid.innerHTML = `
            <div style="grid-column:1/-1; display:flex; align-items:center; justify-content:center; gap:12px; padding:25px 0;">
              <div class="spinner"></div>
              <span>Caricamento stagioni ed episodi...</span>
            </div>
          `;
        }
      }
    }

    // 2. Fetch full backend details
    try {
      const r = await fetch('/api/sc/details', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id: titleId, slug })
      });
      const details = await r.json();

      if (details && !details.error) {
        const isMovie = details.type === 'movie' || details.seasons_count === 0;
        if (scDetailsTypeBadge) scDetailsTypeBadge.textContent = isMovie ? 'Film' : 'Serie TV';

        activeFlag = details.flag || (details.lang === 'eng' ? '🇬🇧' : '🇮🇹');
        activeSource = details.source || activeSource;
        currentWatchUrl = details.watch_url || (itemObj ? itemObj.watch_url : null) || `${currentScDomain}/it/watch/${details.id || titleId}`;

        if (scDetailsCard) {
          scDetailsCard.innerHTML = `
            <img src="${details.poster || details.cover || (itemObj ? (itemObj.poster || itemObj.cover) : 'https://via.placeholder.com/200x300')}" alt="Poster" class="sc-hero-poster">
            <div class="sc-hero-info">
              <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                <span class="sc-card-type">${isMovie ? 'Film' : 'Serie TV'}</span>
                <span class="lang-flag-badge">${activeFlag}</span>
                <span class="source-tag-label" style="font-size:0.75rem;">${escapeHtml(activeSource)}</span>
                <span style="font-size:0.8rem; color: var(--text-dim);">${details.seasons_count ? details.seasons_count + ' Stagioni' : ''}</span>
              </div>
              <h2 class="sc-hero-title">${escapeHtml(details.name || (itemObj ? itemObj.name : 'Titolo'))}</h2>
              <p class="sc-hero-plot">${escapeHtml(details.plot || (itemObj ? itemObj.plot : 'Nessuna trama disponibile.'))}</p>

              ${renderLangSelectorHtml(details)}

              <div style="margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                <button id="btn-stream-movie" class="btn-secondary btn-large" style="background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4);">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                  Guarda in Streaming (${activeFlag})
                </button>
                <button id="btn-download-movie" class="btn-primary btn-large">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                  Scarica in MP4 (${activeFlag})
                </button>
              </div>
            </div>
          `;

          bindLangSelectorEvents(scDetailsCard);

          const btnStreamMovie = document.getElementById('btn-stream-movie');
          if (btnStreamMovie) {
            btnStreamMovie.onclick = () => {
              closeDetailsModal();
              openStreamPlayerModal({
                title: details.name || (itemObj ? itemObj.name : 'Streaming'),
                url: currentWatchUrl
              });
            };
          }

          const btnMovie = document.getElementById('btn-download-movie');
          if (btnMovie) {
            btnMovie.onclick = () => {
              openQualityModal({
                title: details.name || (itemObj ? itemObj.name : 'Download'),
                url: currentWatchUrl
              });
            };
          }
        }

        if (isMovie) {
          if (scSeasonsSection) scSeasonsSection.classList.add('hidden');
        } else {
          if (scSeasonsSection) scSeasonsSection.classList.remove('hidden');
          renderSeasonsTabs(details);
          renderEpisodesGrid(details.episodes, details.name || (itemObj ? itemObj.name : ''));
        }
      } else if (!itemObj) {
        if (scDetailsCard) scDetailsCard.innerHTML = `<div style="color: #EF4444; padding: 20px;">Errore caricamento dettagli: ${details ? details.error : 'Errore connessione'}</div>`;
      }
    } catch (e) {
      if (!itemObj && scDetailsCard) {
        scDetailsCard.innerHTML = `<div style="color: #EF4444; padding: 20px;">Errore caricamento dettagli titolo.</div>`;
      }
    }
  }

  function renderSeasonsTabs(details) {
    if (!scSeasonsTabs) return;
    scSeasonsTabs.innerHTML = "";
    const seasonsCount = details.seasons_count || (Array.isArray(details.seasons) ? details.seasons.length : 1);
    for (let i = 1; i <= seasonsCount; i++) {
      const btn = document.createElement('button');
      btn.className = `season-btn ${i === 1 ? 'active' : ''}`;
      btn.textContent = `Stagione ${i}`;
      btn.addEventListener('click', async () => {
        document.querySelectorAll('.season-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (scEpisodesGrid) scEpisodesGrid.innerHTML = `<div style="grid-column:1/-1; display:flex; align-items:center; justify-content:center; gap:12px; padding:30px 0;"><div class="spinner"></div><span>Caricamento Episodi Stagione ${i}...</span></div>`;
        
        try {
          const r = await fetch('/api/sc/season', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: details.id, slug: details.slug, season: i })
          });
          const seasonData = await r.json();
          if (seasonData && seasonData.episodes) {
            renderEpisodesGrid(seasonData.episodes, details.name, i);
          }
        } catch (e) {}
      });
      scSeasonsTabs.appendChild(btn);
    }
  }

  function renderEpisodesGrid(episodes, seriesTitle, seasonNumber = 1) {
    if (!scEpisodesGrid) return;
    scEpisodesGrid.innerHTML = "";
    if (!episodes || episodes.length === 0) {
      scEpisodesGrid.innerHTML = `<div style="grid-column:1/-1; color:var(--text-muted); padding:20px 0;">Nessun episodio trovato per questa stagione.</div>`;
      return;
    }

    episodes.forEach(ep => {
      const card = document.createElement('div');
      card.className = 'episode-card';
      const epTitleFormatted = `${seriesTitle} - S${String(seasonNumber).padStart(2,'0')}E${String(ep.number).padStart(2,'0')} ${ep.name || ''}`.trim();
      
      card.innerHTML = `
        <div>
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span class="ep-num-badge">S${seasonNumber} E${ep.number}</span>
            <span style="font-size:0.75rem; color:var(--text-dim);">${ep.duration ? ep.duration + ' min' : ''}</span>
          </div>
          <h4 class="ep-title" style="margin-top:6px;">${escapeHtml(ep.name || 'Episodio ' + ep.number)}</h4>
          <p class="ep-plot" style="margin-top:4px;">${escapeHtml(ep.plot || 'Guarda in streaming o scarica l\'episodio in MP4.')}</p>
        </div>
        <div style="margin-top:12px; display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
          <button class="btn-ep-stream btn-secondary" data-url="${escapeAttr(ep.watch_url)}" data-title="${escapeAttr(epTitleFormatted)}" style="background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4); font-size:0.82rem; padding:8px 12px; border-radius:8px; white-space:nowrap;">
            ▶ Streaming
          </button>
          <button class="btn-ep-download btn-primary" data-url="${escapeAttr(ep.watch_url)}" data-title="${escapeAttr(epTitleFormatted)}" style="flex:1; min-width:110px; font-size:0.82rem; padding:8px 12px; border-radius:8px; white-space:nowrap;">
            Scarica MP4
          </button>
          <button class="btn-ep-extract btn-secondary" data-url="${escapeAttr(ep.watch_url)}" title="Estrai Link Vixcloud" style="font-size:0.82rem; padding:8px 12px; border-radius:8px; white-space:nowrap;">
            Estrai Link
          </button>
        </div>
      `;

      const streamBtn = card.querySelector('.btn-ep-stream');
      const dlBtn = card.querySelector('.btn-ep-download');

      if (streamBtn) {
        streamBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const watchUrl = streamBtn.getAttribute('data-url');
          const titleFormatted = streamBtn.getAttribute('data-title');
          closeDetailsModal();
          openStreamPlayerModal({ title: titleFormatted, url: watchUrl });
        });
      }

      if (dlBtn) {
        dlBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const watchUrl = dlBtn.getAttribute('data-url');
          const titleFormatted = dlBtn.getAttribute('data-title');
          openQualityModal({ title: titleFormatted, url: watchUrl });
        });
      }

      card.querySelector('.btn-ep-extract').addEventListener('click', (e) => {
        const watchUrl = e.currentTarget.getAttribute('data-url');
        switchTab('vixcloud');
        if (vixUrlInput) vixUrlInput.value = watchUrl;
        performVixcloudExtraction(watchUrl);
      });

      scEpisodesGrid.appendChild(card);
    });
  }

  // PASTE LINK & DIRECT URL HANDLER
  if (btnPaste) {
    btnPaste.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text && urlInput) {
          urlInput.value = text.trim();
          showAlert("Link incollato dagli appunti!");
          setTimeout(hideAlert, 2000);
        }
      } catch (e) {
        showAlert("Incolla manualmente il link nel campo di testo.");
        setTimeout(hideAlert, 3000);
      }
    });
  }

  if (btnAnalyze) {
    btnAnalyze.addEventListener('click', () => {
      const url = urlInput ? urlInput.value.trim() : "";
      if (url) {
        openQualityModal({ title: "Media da Link Incollato", url: url });
      } else {
        showAlert("Inserisci un link prima di procedere con il download.");
        setTimeout(hideAlert, 3000);
      }
    });
  }

  // VIXCLOUD EXTRACTOR HANDLERS & LOGIC
  if (btnVixPaste) {
    btnVixPaste.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text && vixUrlInput) {
          vixUrlInput.value = text.trim();
          showAlert("Link incollato dagli appunti!");
          setTimeout(hideAlert, 2000);
        }
      } catch (e) {
        showAlert("Incolla manualmente il link nel campo di testo.");
        setTimeout(hideAlert, 3000);
      }
    });
  }

  if (btnVixExtract) {
    btnVixExtract.addEventListener('click', () => {
      const u = vixUrlInput ? vixUrlInput.value.trim() : "";
      performVixcloudExtraction(u);
    });
  }

  if (vixUrlInput) {
    vixUrlInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        const u = vixUrlInput.value.trim();
        performVixcloudExtraction(u);
      }
    });
  }

  function copyToClipboard(text, successMsg) {
    if (!text || text === "Non disponibile") return;
    navigator.clipboard.writeText(text).then(() => {
      showAlert(successMsg || "Copiato negli appunti!");
      setTimeout(hideAlert, 2500);
    }).catch(() => {
      showAlert("Impossibile copiare negli appunti.");
      setTimeout(hideAlert, 2500);
    });
  }

  if (btnCopyVixEmbed) {
    btnCopyVixEmbed.addEventListener('click', () => {
      const val = vixEmbedOutput ? vixEmbedOutput.value : "";
      copyToClipboard(val, "Link Embed Vixcloud copiato negli appunti!");
    });
  }

  if (btnOpenVixEmbed) {
    btnOpenVixEmbed.addEventListener('click', () => {
      const val = vixEmbedOutput ? vixEmbedOutput.value : "";
      if (val && val.startsWith('http')) {
        window.open(val, '_blank');
      } else {
        showAlert("Nessun link embed VixCloud disponibile da aprire.");
        setTimeout(hideAlert, 2500);
      }
    });
  }

  if (btnCopyVixM3u8) {
    btnCopyVixM3u8.addEventListener('click', () => {
      const val = vixM3u8Output ? vixM3u8Output.value : "";
      copyToClipboard(val, "Link Master M3U8 copiato negli appunti!");
    });
  }

  if (btnVixDownloadDirect) {
    btnVixDownloadDirect.addEventListener('click', () => {
      if (currentExtractedData && currentExtractedData.original_url) {
        openQualityModal({
          title: currentExtractedData.title || "Download Video",
          url: currentExtractedData.original_url
        });
      }
    });
  }

  async function performVixcloudExtraction(targetUrl) {
    if (!targetUrl) {
      showAlert("Inserisci un link prima di procedere con l'estrazione.");
      setTimeout(hideAlert, 3000);
      return;
    }

    if (vixExtractSpinner) vixExtractSpinner.classList.remove('hidden');
    if (vixExtractText) vixExtractText.textContent = "Estrazione in corso...";
    if (btnVixExtract) btnVixExtract.disabled = true;

    try {
      const r = await fetch('/api/vixcloud/extract', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ url: targetUrl })
      });
      const data = await r.json();

      if (!data || data.error) {
        showAlert(data ? data.error : "Errore durante l'estrazione VixCloud.");
        setTimeout(hideAlert, 4000);
        return;
      }

      currentExtractedData = data;

      if (vixResultTitle) vixResultTitle.textContent = data.title || "Contenuto Estratto";
      if (vixEmbedOutput) vixEmbedOutput.value = data.vix_url || "Non disponibile";
      if (vixM3u8Output) vixM3u8Output.value = data.master_m3u8 || "Non disponibile";

      if (vixQualitiesList) {
        vixQualitiesList.innerHTML = "";
        const qualities = data.qualities || [];
        if (qualities.length === 0) {
          vixQualitiesList.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding:8px 0;">Master M3U8 unico disponibile.</div>`;
        } else {
          qualities.forEach(q => {
            const row = document.createElement('div');
            row.className = 'vix-quality-row';
            row.style.cssText = 'display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); border:1px solid var(--panel-border); padding:10px 14px; border-radius:var(--radius-sm);';
            row.innerHTML = `
              <div>
                <span style="font-weight:700; color:white; font-size:0.9rem;">${escapeHtml(q.label || q.quality)}</span>
                <span style="font-size:0.78rem; color:var(--text-dim); margin-left:8px;">${escapeHtml(q.resolution || '')}</span>
              </div>
              <div style="display:flex; gap:8px;">
                <button class="btn-secondary btn-sm btn-copy-q" data-url="${escapeAttr(q.stream_url)}">Copia Stream</button>
              </div>
            `;
            row.querySelector('.btn-copy-q').addEventListener('click', (e) => {
              const u = e.currentTarget.getAttribute('data-url');
              copyToClipboard(u, `Link stream ${q.label} copiato negli appunti!`);
            });
            vixQualitiesList.appendChild(row);
          });
        }
      }

      if (vixResultsSection) vixResultsSection.classList.remove('hidden');
      showAlert("Estrazione VixCloud completata con successo!");
      setTimeout(hideAlert, 3000);

    } catch (e) {
      showAlert("Errore di rete durante l'estrazione dei link VixCloud.");
      setTimeout(hideAlert, 4000);
    } finally {
      if (vixExtractSpinner) vixExtractSpinner.classList.add('hidden');
      if (vixExtractText) vixExtractText.textContent = "Estrai Link Vixcloud";
      if (btnVixExtract) btnVixExtract.disabled = false;
    }
  }

  // QUALITY SELECTION MODAL LOGIC
  async function openQualityModal(mediaData) {
    modalSelectedTarget = { ...mediaData, selectedQuality: '1080', streamUrl: mediaData.url };
    if (modalMediaTitle) modalMediaTitle.textContent = mediaData.title || "Download Video";
    
    if (qualityModal) qualityModal.classList.remove('hidden');

    if (modalQualityOptions) {
      modalQualityOptions.innerHTML = `
        <div style="display:flex; align-items:center; justify-content:center; gap:12px; padding:20px 0;">
          <div class="spinner"></div>
          <span>Analisi link e risoluzioni disponibili...</span>
        </div>
      `;
    }

    try {
      const r = await fetch('/api/sc/qualities', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ url: mediaData.url })
      });
      const qualitiesRes = await r.json();

      if (qualitiesRes && qualitiesRes.title) {
        if (modalMediaTitle) modalMediaTitle.textContent = qualitiesRes.title;
        modalSelectedTarget.title = qualitiesRes.title;
      }

      if (!qualitiesRes || qualitiesRes.error || !qualitiesRes.qualities) {
        if (modalQualityOptions) {
          modalQualityOptions.innerHTML = `
            <div class="quality-option-pill selected" data-quality="1080" data-url="${escapeAttr(mediaData.url)}">
              <span class="quality-pill-title">Qualità Predefinita MP4</span>
              <span class="quality-pill-bw">Alta Definizione</span>
            </div>
          `;
        }
        return;
      }

      if (modalQualityOptions) {
        modalQualityOptions.innerHTML = "";
        qualitiesRes.qualities.forEach((q, idx) => {
          const pill = document.createElement('div');
          const isSelected = idx === 0 || q.quality === '1080';
          pill.className = `quality-option-pill ${isSelected ? 'selected' : ''}`;
          pill.setAttribute('data-quality', q.quality);
          pill.setAttribute('data-url', q.stream_url || qualitiesRes.master_m3u8);

          pill.innerHTML = `
            <span class="quality-pill-title">${escapeHtml(q.label)}</span>
            <span class="quality-pill-bw">${escapeHtml(q.resolution || q.bandwidth)}</span>
          `;

          if (isSelected) {
            modalSelectedTarget.selectedQuality = q.quality;
            modalSelectedTarget.streamUrl = q.stream_url || qualitiesRes.master_m3u8;
          }

          pill.addEventListener('click', () => {
            document.querySelectorAll('.quality-option-pill').forEach(p => p.classList.remove('selected'));
            pill.classList.add('selected');
            modalSelectedTarget.selectedQuality = pill.getAttribute('data-quality');
            modalSelectedTarget.streamUrl = pill.getAttribute('data-url');
          });

          modalQualityOptions.appendChild(pill);
        });
      }
    } catch (e) {}
  }

  function closeModal() {
    if (qualityModal) qualityModal.classList.add('hidden');
  }

  if (btnCloseModal) btnCloseModal.addEventListener('click', closeModal);
  if (btnCancelModal) btnCancelModal.addEventListener('click', closeModal);

  if (btnConfirmDownload) {
    btnConfirmDownload.addEventListener('click', () => {
      if (!modalSelectedTarget) return;
      closeModal();
      switchTab('downloads');
      startTargetDownload(modalSelectedTarget.url || modalSelectedTarget.streamUrl, modalSelectedTarget.selectedQuality || "1080p", modalSelectedTarget.title || "Media Download");
    });
  }

  function startTargetDownload(targetUrl, formatChoice, customTitle) {
    showAlert(`Download avviato per "${customTitle}"!`);
    setTimeout(hideAlert, 3500);

    switchTab('downloads');

    fetch('/api/download/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        url: targetUrl,
        media_type: "hls",
        format_choice: formatChoice,
        custom_title: customTitle
      })
    })
    .then(r => r.json())
    .then(res => {
      if (res && res.download_id) {
        createDownloadItem(res.download_id, customTitle);
      }
    });
  }

  // DOWNLOAD TRACKER & CONTROL UI
  function createDownloadItem(downloadId, title) {
    if (emptyDownloadsPlaceholder) emptyDownloadsPlaceholder.style.display = 'none';

    activeDownloadsCount++;
    updateDownloadsBadge();

    const item = document.createElement('div');
    item.className = 'download-item-card';
    item.id = `download-card-${downloadId}`;
    item.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <span style="font-weight:700; color:white; display:block;">${escapeHtml(title)}</span>
          <span id="phase-badge-${downloadId}" style="font-size:0.75rem; font-weight:600; color:var(--primary);">Analisi e download segmenti...</span>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <button id="btn-pause-${downloadId}" class="btn-secondary btn-icon" title="Pausa">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
          </button>
          <button id="btn-cancel-${downloadId}" class="btn-secondary btn-icon" title="Interrompi">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
      </div>
      <div class="progress-bar-bg">
        <div class="progress-bar-fill" id="progress-fill-${downloadId}"></div>
      </div>
      <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.8rem; color:var(--text-muted);">
        <span id="progress-text-${downloadId}">0% • Inizializzazione...</span>
        <span id="speed-text-${downloadId}">0 MB/s</span>
      </div>
    `;

    if (activeList) activeList.prepend(item);

    const btnPause = document.getElementById(`btn-pause-${downloadId}`);
    const btnCancel = document.getElementById(`btn-cancel-${downloadId}`);

    if (btnPause) {
      btnPause.addEventListener('click', () => {
        const isPaused = item.classList.contains('paused');
        const action = isPaused ? 'resume' : 'pause';
        fetch(`/api/download/${action}/${downloadId}`, { method: 'POST' })
          .then(r => r.json())
          .then(res => {
            if (res.success) {
              if (action === 'pause') {
                item.classList.add('paused');
                btnPause.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`;
                btnPause.title = "Riprendi";
                const pb = document.getElementById(`phase-badge-${downloadId}`);
                if (pb) pb.textContent = "Download in Pausa";
              } else {
                item.classList.remove('paused');
                btnPause.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>`;
                btnPause.title = "Pausa";
                const pb = document.getElementById(`phase-badge-${downloadId}`);
                if (pb) pb.textContent = "Download segmenti in corso...";
              }
            }
          });
      });
    }

    if (btnCancel) {
      btnCancel.addEventListener('click', () => {
        fetch(`/api/download/cancel/${downloadId}`, { method: 'POST' });
      });
    }

    pollDownloadStatus(downloadId);
  }

  function updateDownloadsBadge() {
    if (downloadsCountText) downloadsCountText.textContent = `${activeDownloadsCount} download in corso`;
    if (navDownloadsBadge) {
      if (activeDownloadsCount > 0) {
        navDownloadsBadge.textContent = activeDownloadsCount;
        navDownloadsBadge.classList.remove('hidden');
      } else {
        navDownloadsBadge.classList.add('hidden');
      }
    }
  }

  function pollDownloadStatus(downloadId) {
    const interval = setInterval(() => {
      fetch(`/api/download/status/${downloadId}`)
        .then(r => r.json())
        .then(status => {
          if (!status) return;
          const card = document.getElementById(`download-card-${downloadId}`);
          const fill = document.getElementById(`progress-fill-${downloadId}`);
          const text = document.getElementById(`progress-text-${downloadId}`);
          const speedText = document.getElementById(`speed-text-${downloadId}`);
          const phaseBadge = document.getElementById(`phase-badge-${downloadId}`);

          if (status.state === 'running') {
            const pct = (status.percent || 0).toFixed(1);
            if (fill) fill.style.width = `${pct}%`;
            if (text) text.textContent = `${pct}% • Scaricati: ${status.downloaded || '0 MB'}`;
            if (speedText) speedText.textContent = status.speed || '0 MB/s';

            if (status.phase === 'merging') {
              if (card) card.classList.add('merging');
              if (phaseBadge) {
                phaseBadge.style.color = '#F59E0B';
                phaseBadge.textContent = '⚡ Unione file MP4 ed audio in corso...';
              }
            } else if (phaseBadge && !card || (card && !card.classList.contains('paused'))) {
              phaseBadge.style.color = 'var(--primary)';
              phaseBadge.textContent = 'Download segmenti velocizzato in corso...';
            }

          } else if (status.state === 'completed') {
            clearInterval(interval);
            if (card) {
              card.classList.remove('merging', 'paused');
              card.classList.add('completed');
            }
            if (fill) fill.style.width = '100%';
            if (phaseBadge) {
              phaseBadge.style.color = '#34D399';
              phaseBadge.textContent = '✓ Download completato!';
            }
            if (text) {
              text.style.color = '#34D399';
              text.innerHTML = `File salvato in <strong>Downloads</strong> (${status.filename || 'File MP4'})`;
            }
            if (speedText) speedText.textContent = '';
            
            if (activeDownloadsCount > 0) activeDownloadsCount--;
            updateDownloadsBadge();
            showAlert(`Download completato con successo!`);
            setTimeout(hideAlert, 4000);

          } else if (status.state === 'canceled') {
            clearInterval(interval);
            if (card) card.remove();
            if (activeDownloadsCount > 0) activeDownloadsCount--;
            updateDownloadsBadge();
            if (activeList && activeList.children.length === 0 && emptyDownloadsPlaceholder) {
              emptyDownloadsPlaceholder.style.display = 'block';
            }

          } else if (status.state === 'error') {
            clearInterval(interval);
            if (card) card.classList.remove('merging');
            if (fill) fill.style.backgroundColor = '#EF4444';
            if (phaseBadge) {
              phaseBadge.style.color = '#F87171';
              phaseBadge.textContent = '❌ Download Interrotto o Errore';
            }
            if (text) {
              text.style.color = '#F87171';
              text.textContent = `Errore: ${status.error || 'Impossibile completare'}`;
            }
            if (activeDownloadsCount > 0) activeDownloadsCount--;
            updateDownloadsBadge();
          }
        })
        .catch(() => clearInterval(interval));
    }, 500);
  }

  // UTILS
  function showAlert(msg) {
    if (alertBanner) {
      alertBanner.textContent = msg;
      alertBanner.classList.remove('hidden');
    }
  }

  function hideAlert() {
    if (alertBanner) alertBanner.classList.add('hidden');
  }

  function escapeHtml(str) {
    return str ? String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") : "";
  }

  function escapeAttr(str) {
    return str ? String(str).replace(/"/g, "&quot;") : "";
  }

  // CONTINUA A GUARDARE (CONTINUE WATCHING) STATE & LOGIC
  let currentActiveMedia = null;
  let lastSaveTime = 0;

  function formatTime(seconds) {
    if (!seconds || isNaN(seconds)) return "00:00";
    const s = Math.floor(seconds);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    const h = Math.floor(m / 60);
    const min = m % 60;
    if (h > 0) {
      return `${h}:${min < 10 ? '0' : ''}${min}:${sec < 10 ? '0' : ''}${sec}`;
    }
    return `${min}:${sec < 10 ? '0' : ''}${sec}`;
  }

  function captureVideoFrame(videoEl) {
    try {
      if (!videoEl || videoEl.videoWidth === 0 || videoEl.currentTime < 2) return null;
      const canvas = document.createElement('canvas');
      canvas.width = 320;
      canvas.height = 180;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', 0.82);
    } catch (e) {
      return null;
    }
  }

  async function getContinueWatchingList() {
    try {
      const res = await fetch('/api/history');
      if (res.ok) return await res.json();
    } catch (e) {}
    try {
      return JSON.parse(localStorage.getItem('sc_continue_watching') || '[]');
    } catch (e) {
      return [];
    }
  }

  async function saveContinueWatchingProgress() {
    if (!currentActiveMedia || !scStreamVideo) return;
    const ct = scStreamVideo.currentTime;
    const dur = scStreamVideo.duration;

    if (!dur || dur < 10 || ct < 3) return;

    const frameSnapshot = captureVideoFrame(scStreamVideo);
    const mediaId = currentActiveMedia.url || currentActiveMedia.title;

    const item = {
      id: mediaId,
      title: currentActiveMedia.title || "Media",
      poster: currentActiveMedia.poster || "",
      frameThumbnail: frameSnapshot || currentActiveMedia.frameThumbnail || "",
      url: currentActiveMedia.url,
      currentTime: ct,
      duration: dur,
      percent: Math.round((ct / dur) * 100),
      updatedAt: Date.now()
    };

    // Save to localStorage as backup
    try {
      let list = JSON.parse(localStorage.getItem('sc_continue_watching') || '[]');
      list = list.filter(i => i.id !== mediaId && i.url !== item.url);
      if (ct / dur < 0.95) list.unshift(item);
      localStorage.setItem('sc_continue_watching', JSON.stringify(list.slice(0, 15)));
    } catch (e) {}

    // Save to persistent file on disk via backend
    try {
      await fetch('/api/history/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(item)
      });
    } catch (e) {}

    renderContinueWatchingSection();
  }

  async function removeContinueWatchingItem(mediaId) {
    try {
      await fetch('/api/history/remove', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id: mediaId })
      });
    } catch (e) {}
    try {
      let list = JSON.parse(localStorage.getItem('sc_continue_watching') || '[]');
      list = list.filter(i => i.id !== mediaId && i.url !== mediaId);
      localStorage.setItem('sc_continue_watching', JSON.stringify(list));
    } catch (e) {}
    renderContinueWatchingSection();
  }

  async function renderContinueWatchingSection() {
    const section = document.getElementById('sc-continue-watching-section');
    const grid = document.getElementById('sc-continue-watching-grid');
    if (!section || !grid) return;

    const list = await getContinueWatchingList();
    if (!list || list.length === 0) {
      section.classList.add('hidden');
      grid.innerHTML = "";
      return;
    }

    section.classList.remove('hidden');
    grid.innerHTML = "";

    list.forEach(item => {
      const card = document.createElement('div');
      card.className = 'cw-card';
      const posterSrc = item.frameThumbnail || item.poster || 'https://via.placeholder.com/300x169?text=Continua+a+Guardare';
      const pct = Math.min(100, Math.max(0, item.percent || 0));

      card.innerHTML = `
        <div class="cw-poster-wrapper">
          <img src="${escapeAttr(posterSrc)}" alt="${escapeAttr(item.title)}" class="cw-poster" />
          <div class="cw-play-overlay">
            <div class="cw-play-btn">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            </div>
          </div>
          <button class="cw-btn-remove" title="Rimuovi da Continua a Guardare">&times;</button>
          <div class="cw-progress-bg">
            <div class="cw-progress-fill" style="width: ${pct}%;"></div>
          </div>
        </div>
        <div class="cw-body">
          <div class="cw-title">${escapeHtml(item.title)}</div>
          <div class="cw-meta">
            <span>Riprendi da ${formatTime(item.currentTime)}</span>
            <span style="color: var(--primary); font-weight:600;">${pct}%</span>
          </div>
        </div>
      `;

      card.addEventListener('click', (e) => {
        if (e.target.closest('.cw-btn-remove')) {
          e.stopPropagation();
          removeContinueWatchingItem(item.id);
          return;
        }
        openStreamPlayerModal({
          title: item.title,
          url: item.url,
          poster: item.poster,
          frameThumbnail: item.frameThumbnail,
          resumeTime: item.currentTime
        });
      });

      grid.appendChild(card);
    });
  }

  const btnClearCw = document.getElementById('btn-clear-continue-watching');
  if (btnClearCw) {
    btnClearCw.addEventListener('click', async () => {
      try {
        await fetch('/api/history/clear', { method: 'POST' });
      } catch (e) {}
      try {
        localStorage.removeItem('sc_continue_watching');
      } catch (e) {}
      renderContinueWatchingSection();
    });
  }

  // STREAM PLAYER MODAL, FLOAT-BLUR CONTROLS & ROTELLA SETTINGS LOGIC
  const streamPlayerModal = document.getElementById('stream-player-modal');
  const streamMediaTitle = document.getElementById('stream-media-title');
  const floatPlayerTitle = document.getElementById('float-player-title');
  const scStreamVideo = document.getElementById('sc-stream-video');
  const videoContainerBox = document.getElementById('video-container-box');
  const btnFullscreenStream = document.getElementById('btn-fullscreen-stream');
  const btnCloseStreamModal = document.getElementById('btn-close-stream-modal');
  const btnFloatClose = document.getElementById('btn-float-close');
  const btnPipStream = document.getElementById('btn-pip-stream');
  const videoShortcutToast = document.getElementById('video-shortcut-toast');

  // Float Controls
  const floatBigPlayOverlay = document.getElementById('float-big-play-overlay');
  const btnFloatPlay = document.getElementById('btn-float-play');
  const iconFloatPlay = document.getElementById('icon-float-play');
  const iconFloatPause = document.getElementById('icon-float-pause');
  const btnFloatRewind = document.getElementById('btn-float-rewind');
  const btnFloatForward = document.getElementById('btn-float-forward');
  const btnFloatMute = document.getElementById('btn-float-mute');
  const iconVolHigh = document.getElementById('icon-vol-high');
  const iconVolMute = document.getElementById('icon-vol-mute');
  const floatVolumeSlider = document.getElementById('float-volume-slider');
  const floatCurrentTime = document.getElementById('float-current-time');
  const floatDurationTime = document.getElementById('float-duration-time');
  const btnFloatSettings = document.getElementById('btn-float-settings');
  const btnFloatFullscreen = document.getElementById('btn-float-fullscreen');

  // Progress Scrubber
  const floatProgressContainer = document.getElementById('float-progress-container');
  const floatProgressBuffer = document.getElementById('float-progress-buffer');
  const floatProgressFill = document.getElementById('float-progress-fill');
  const floatProgressHandle = document.getElementById('float-progress-handle');
  const floatHoverTooltip = document.getElementById('float-hover-tooltip');

  // Settings Menu Popover (Rotella)
  const floatSettingsMenu = document.getElementById('float-settings-menu');
  const settingsMenuMain = document.getElementById('settings-menu-main');
  const settingsMenuQuality = document.getElementById('settings-menu-quality');
  const settingsMenuSubtitles = document.getElementById('settings-menu-subtitles');
  const settingsMenuAudio = document.getElementById('settings-menu-audio');
  const settingsMenuSpeed = document.getElementById('settings-menu-speed');

  const settingOptQuality = document.getElementById('setting-opt-quality');
  const settingOptSubtitles = document.getElementById('setting-opt-subtitles');
  const settingOptAudio = document.getElementById('setting-opt-audio');
  const settingOptSpeed = document.getElementById('setting-opt-speed');

  const settingLblQuality = document.getElementById('setting-lbl-quality');
  const settingLblSubtitles = document.getElementById('setting-lbl-subtitles');
  const settingLblAudio = document.getElementById('setting-lbl-audio');
  const settingLblSpeed = document.getElementById('setting-lbl-speed');

  const settingsListQuality = document.getElementById('settings-list-quality');
  const settingsListSubtitles = document.getElementById('settings-list-subtitles');
  const settingsListAudio = document.getElementById('settings-list-audio');

  const settingsBackQuality = document.getElementById('settings-back-quality');
  const settingsBackSubtitles = document.getElementById('settings-back-subtitles');
  const settingsBackAudio = document.getElementById('settings-back-audio');
  const settingsBackSpeed = document.getElementById('settings-back-speed');

  let currentHls = null;
  let toastTimeout = null;
  let controlsHideTimer = null;

  function showToast(msg) {
    if (!videoShortcutToast) return;
    videoShortcutToast.textContent = msg;
    videoShortcutToast.classList.remove('hidden');
    videoShortcutToast.style.opacity = '1';

    if (toastTimeout) clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => {
      videoShortcutToast.style.opacity = '0';
      setTimeout(() => videoShortcutToast.classList.add('hidden'), 300);
    }, 1200);
  }

  let volumePopupTimer = null;
  function showVolumePopup(vol) {
    const volumePopup = document.getElementById('volume-popup');
    const volumePopupFill = document.getElementById('volume-popup-fill');
    if (!volumePopup || !volumePopupFill) return;
    
    const clampedVol = Math.max(0, Math.min(1, vol));
    volumePopup.classList.remove('hidden');
    volumePopup.classList.add('active');
    volumePopupFill.style.width = `${clampedVol * 100}%`;
    
    if (volumePopupTimer) clearTimeout(volumePopupTimer);
    volumePopupTimer = setTimeout(() => {
      volumePopup.classList.remove('active');
      setTimeout(() => volumePopup.classList.add('hidden'), 250);
    }, 1200);
  }

  function formatPlayerTime(sec) {
    if (!sec || isNaN(sec)) return "00:00";
    sec = Math.floor(sec);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) {
      return `${h}:${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
    }
    return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
  }

  function toggleFullscreen() {
    if (!streamPlayerModal || !scStreamVideo) return;

    const isFS = streamPlayerModal.classList.contains('is-fullscreen') || !!document.fullscreenElement || !!document.webkitFullscreenElement;

    if (!isFS) {
      streamPlayerModal.classList.add('is-fullscreen');
      if (typeof scStreamVideo.webkitEnterFullscreen === 'function') {
        try { scStreamVideo.webkitEnterFullscreen(); } catch (e) {}
      } else if (videoContainerBox && videoContainerBox.requestFullscreen) {
        videoContainerBox.requestFullscreen().catch(() => {});
      } else if (scStreamVideo.requestFullscreen) {
        scStreamVideo.requestFullscreen().catch(() => {});
      }
      showToast("⛶ Schermo Intero");
    } else {
      streamPlayerModal.classList.remove('is-fullscreen');
      if (typeof scStreamVideo.webkitExitFullscreen === 'function') {
        try { scStreamVideo.webkitExitFullscreen(); } catch (e) {}
      }
      if (document.exitFullscreen) document.exitFullscreen().catch(() => {});
      else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
      showToast("🗗 Finestra");
    }
  }

  if (btnFullscreenStream) btnFullscreenStream.addEventListener('click', toggleFullscreen);
  if (btnFloatFullscreen) btnFloatFullscreen.addEventListener('click', toggleFullscreen);

  // PIP support
  if (btnPipStream) {
    btnPipStream.addEventListener('click', async () => {
      if (!scStreamVideo) return;
      try {
        if (document.pictureInPictureElement) {
          await document.exitPictureInPicture();
        } else if (document.pictureInPictureEnabled) {
          await scStreamVideo.requestPictureInPicture();
        }
      } catch (e) {}
    });
  }

  // PLAY / PAUSE LOGIC & UI SYNC
  function updatePlayPauseUI() {
    if (!scStreamVideo || !videoContainerBox) return;
    if (scStreamVideo.paused) {
      videoContainerBox.classList.add('is-paused');
      if (iconFloatPlay) iconFloatPlay.classList.remove('hidden');
      if (iconFloatPause) iconFloatPause.classList.add('hidden');
    } else {
      videoContainerBox.classList.remove('is-paused');
      if (iconFloatPlay) iconFloatPlay.classList.add('hidden');
      if (iconFloatPause) iconFloatPause.classList.remove('hidden');
    }
  }

  function togglePlayPause() {
    if (!scStreamVideo) return;
    if (scStreamVideo.paused) {
      scStreamVideo.play().catch(() => {});
      showToast("▶ Riproduci");
    } else {
      scStreamVideo.pause();
      showToast("⏸ Pausa");
    }
  }

  if (btnFloatPlay) btnFloatPlay.addEventListener('click', togglePlayPause);
  if (floatBigPlayOverlay) floatBigPlayOverlay.addEventListener('click', togglePlayPause);

  if (scStreamVideo) {
    scStreamVideo.addEventListener('play', updatePlayPauseUI);
    scStreamVideo.addEventListener('pause', () => {
      updatePlayPauseUI();
      saveContinueWatchingProgress();
    });

    scStreamVideo.addEventListener('dblclick', (e) => {
      e.preventDefault();
      toggleFullscreen();
    });

    scStreamVideo.addEventListener('timeupdate', () => {
      if (!scStreamVideo.duration) return;
      const cur = scStreamVideo.currentTime;
      const dur = scStreamVideo.duration;
      const pct = (cur / dur) * 100;

      if (floatCurrentTime) floatCurrentTime.textContent = formatPlayerTime(cur);
      if (floatDurationTime) floatDurationTime.textContent = formatPlayerTime(dur);
      if (floatProgressFill) floatProgressFill.style.width = `${pct}%`;
      if (floatProgressHandle) floatProgressHandle.style.left = `${pct}%`;

      // Buffer bar update
      if (floatProgressBuffer && scStreamVideo.buffered.length > 0) {
        let bufEnd = 0;
        for (let i = 0; i < scStreamVideo.buffered.length; i++) {
          if (scStreamVideo.buffered.start(i) <= cur && scStreamVideo.buffered.end(i) >= cur) {
            bufEnd = scStreamVideo.buffered.end(i);
            break;
          }
        }
        const bufPct = (bufEnd / dur) * 100;
        floatProgressBuffer.style.width = `${bufPct}%`;
      }

      const now = Date.now();
      if (now - lastSaveTime > 3000) {
        lastSaveTime = now;
        saveContinueWatchingProgress();
      }
    });
  }

  // REWIND / FORWARD 10S
  if (btnFloatRewind) {
    btnFloatRewind.addEventListener('click', () => {
      if (scStreamVideo) {
        scStreamVideo.currentTime = Math.max(0, scStreamVideo.currentTime - 10);
        showToast("⏪ -10 sec");
      }
    });
  }

  if (btnFloatForward) {
    btnFloatForward.addEventListener('click', () => {
      if (scStreamVideo) {
        scStreamVideo.currentTime = Math.min(scStreamVideo.duration || 0, scStreamVideo.currentTime + 10);
        showToast("⏩ +10 sec");
      }
    });
  }

  // SCRUBBER TIMELINE INTERACTION
  let isSeeking = false;

  function handleScrubberSeek(e) {
    if (!scStreamVideo || !scStreamVideo.duration || !floatProgressContainer) return;
    const rect = floatProgressContainer.getBoundingClientRect();
    const clickX = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    const pct = clickX / rect.width;
    scStreamVideo.currentTime = pct * scStreamVideo.duration;
  }

  if (floatProgressContainer) {
    floatProgressContainer.addEventListener('mousemove', (e) => {
      if (!scStreamVideo || !scStreamVideo.duration) return;
      const rect = floatProgressContainer.getBoundingClientRect();
      const hoverX = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
      const hoverPct = hoverX / rect.width;
      const hoverTime = hoverPct * scStreamVideo.duration;

      if (floatHoverTooltip) {
        floatHoverTooltip.textContent = formatPlayerTime(hoverTime);
        floatHoverTooltip.style.left = `${hoverX}px`;
      }

      if (isSeeking) handleScrubberSeek(e);
    });

    floatProgressContainer.addEventListener('mousedown', (e) => {
      isSeeking = true;
      handleScrubberSeek(e);
    });

    document.addEventListener('mouseup', () => {
      if (isSeeking) isSeeking = false;
    });
  }

  // VOLUME & MUTE LOGIC
  if (floatVolumeSlider && scStreamVideo) {
    floatVolumeSlider.addEventListener('input', () => {
      scStreamVideo.volume = parseFloat(floatVolumeSlider.value);
      scStreamVideo.muted = (scStreamVideo.volume === 0);
      updateVolumeIcons();
    });
  }

  function updateVolumeIcons() {
    if (!scStreamVideo) return;
    if (scStreamVideo.muted || scStreamVideo.volume === 0) {
      if (iconVolHigh) iconVolHigh.classList.add('hidden');
      if (iconVolMute) iconVolMute.classList.remove('hidden');
    } else {
      if (iconVolHigh) iconVolHigh.classList.remove('hidden');
      if (iconVolMute) iconVolMute.classList.add('hidden');
    }
  }

  if (btnFloatMute) {
    btnFloatMute.addEventListener('click', () => {
      if (!scStreamVideo) return;
      scStreamVideo.muted = !scStreamVideo.muted;
      if (floatVolumeSlider) floatVolumeSlider.value = scStreamVideo.muted ? 0 : scStreamVideo.volume;
      updateVolumeIcons();
      showToast(scStreamVideo.muted ? "🔇 Muto" : "🔊 Audio Attivo");
    });
  }

  // AUTO-HIDE CONTROLS ON INACTIVITY
  function resetControlsHideTimer() {
    if (!videoContainerBox) return;
    videoContainerBox.classList.remove('hide-controls');

    if (controlsHideTimer) clearTimeout(controlsHideTimer);

    // Only hide if video is playing AND settings menu is closed
    if (scStreamVideo && !scStreamVideo.paused && floatSettingsMenu && floatSettingsMenu.classList.contains('hidden')) {
      controlsHideTimer = setTimeout(() => {
        if (scStreamVideo && !scStreamVideo.paused && floatSettingsMenu && floatSettingsMenu.classList.contains('hidden')) {
          videoContainerBox.classList.add('hide-controls');
        }
      }, 2500);
    }
  }

  if (videoContainerBox) {
    videoContainerBox.addEventListener('mousemove', resetControlsHideTimer);
    videoContainerBox.addEventListener('mouseleave', () => {
      if (scStreamVideo && !scStreamVideo.paused && floatSettingsMenu && floatSettingsMenu.classList.contains('hidden')) {
        videoContainerBox.classList.add('hide-controls');
      }
    });
  }

  // ROTELLA SETTINGS POPOVER MENU LOGIC
  function hideAllSettingsViews() {
    if (settingsMenuMain) settingsMenuMain.classList.add('hidden');
    if (settingsMenuQuality) settingsMenuQuality.classList.add('hidden');
    if (settingsMenuSubtitles) settingsMenuSubtitles.classList.add('hidden');
    if (settingsMenuAudio) settingsMenuAudio.classList.add('hidden');
    if (settingsMenuSpeed) settingsMenuSpeed.classList.add('hidden');
  }

  function openSettingsMain() {
    hideAllSettingsViews();
    if (settingsMenuMain) settingsMenuMain.classList.remove('hidden');
  }

  if (btnFloatSettings) {
    btnFloatSettings.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!floatSettingsMenu) return;
      const isHidden = floatSettingsMenu.classList.contains('hidden');
      if (isHidden) {
        openSettingsMain();
        floatSettingsMenu.classList.remove('hidden');
        resetControlsHideTimer();
      } else {
        floatSettingsMenu.classList.add('hidden');
      }
    });
  }

  // Submenu Switchers
  if (settingOptQuality) {
    settingOptQuality.addEventListener('click', () => {
      hideAllSettingsViews();
      if (settingsMenuQuality) settingsMenuQuality.classList.remove('hidden');
    });
  }

  if (settingOptSubtitles) {
    settingOptSubtitles.addEventListener('click', () => {
      hideAllSettingsViews();
      if (settingsMenuSubtitles) settingsMenuSubtitles.classList.remove('hidden');
    });
  }

  if (settingOptAudio) {
    settingOptAudio.addEventListener('click', () => {
      hideAllSettingsViews();
      if (settingsMenuAudio) settingsMenuAudio.classList.remove('hidden');
    });
  }

  if (settingOptSpeed) {
    settingOptSpeed.addEventListener('click', () => {
      hideAllSettingsViews();
      if (settingsMenuSpeed) settingsMenuSpeed.classList.remove('hidden');
    });
  }

  // Submenu Back Buttons
  if (settingsBackQuality) settingsBackQuality.addEventListener('click', openSettingsMain);
  if (settingsBackSubtitles) settingsBackSubtitles.addEventListener('click', openSettingsMain);
  if (settingsBackAudio) settingsBackAudio.addEventListener('click', openSettingsMain);
  if (settingsBackSpeed) settingsBackSpeed.addEventListener('click', openSettingsMain);

  // Close Settings Menu when clicking outside
  document.addEventListener('click', (e) => {
    if (floatSettingsMenu && !floatSettingsMenu.classList.contains('hidden')) {
      if (!floatSettingsMenu.contains(e.target) && !btnFloatSettings.contains(e.target)) {
        floatSettingsMenu.classList.add('hidden');
      }
    }
  });

  // POPULATE DYNAMIC HLS SETTINGS MENUS
  function setupHlsSettings() {
    // 1. QUALITÀ (QUALITY)
    if (settingsListQuality) {
      settingsListQuality.innerHTML = '';
      if (currentHls && currentHls.levels && currentHls.levels.length > 0) {
        // Auto Level Option
        const autoOpt = document.createElement('div');
        autoOpt.className = `settings-option ${currentHls.currentLevel === -1 ? 'active' : ''}`;
        autoOpt.textContent = 'Auto (Consigliata)';
        autoOpt.addEventListener('click', () => {
          currentHls.currentLevel = -1;
          if (settingLblQuality) settingLblQuality.textContent = 'Auto';
          setupHlsSettings();
          showToast("📶 Qualità: Auto");
        });
        settingsListQuality.appendChild(autoOpt);

        // Quality Levels
        currentHls.levels.forEach((lvl, idx) => {
          const opt = document.createElement('div');
          const height = lvl.height ? `${lvl.height}p` : `${Math.round((lvl.bitrate || 0)/1000)}k`;
          opt.className = `settings-option ${currentHls.currentLevel === idx ? 'active' : ''}`;
          opt.textContent = height;
          opt.addEventListener('click', () => {
            currentHls.currentLevel = idx;
            if (settingLblQuality) settingLblQuality.textContent = height;
            setupHlsSettings();
            showToast(`📶 Qualità: ${height}`);
          });
          settingsListQuality.appendChild(opt);
        });
      } else {
        settingsListQuality.innerHTML = '<div class="settings-option active">Auto</div>';
      }
    }

    // 2. SOTTOTITOLI (SUBTITLES)
    if (settingsListSubtitles) {
      settingsListSubtitles.innerHTML = '';
      
      const offOpt = document.createElement('div');
      const isSubOff = !currentHls || currentHls.subtitleTrack === -1;
      offOpt.className = `settings-option ${isSubOff ? 'active' : ''}`;
      offOpt.textContent = 'Disattivati';
      offOpt.addEventListener('click', () => {
        if (currentHls) currentHls.subtitleTrack = -1;
        if (scStreamVideo && scStreamVideo.textTracks) {
          for (let i = 0; i < scStreamVideo.textTracks.length; i++) {
            scStreamVideo.textTracks[i].mode = 'disabled';
          }
        }
        if (settingLblSubtitles) settingLblSubtitles.textContent = 'Disattivati';
        setupHlsSettings();
        showToast("💬 Sottotitoli: Disattivati");
      });
      settingsListSubtitles.appendChild(offOpt);

      if (currentHls && currentHls.subtitleTracks && currentHls.subtitleTracks.length > 0) {
        currentHls.subtitleTracks.forEach((track, idx) => {
          const opt = document.createElement('div');
          const name = track.name || track.lang || `Sottotitolo ${idx + 1}`;
          opt.className = `settings-option ${currentHls.subtitleTrack === idx ? 'active' : ''}`;
          opt.textContent = name;
          opt.addEventListener('click', () => {
            currentHls.subtitleTrack = idx;
            if (settingLblSubtitles) settingLblSubtitles.textContent = name;
            setupHlsSettings();
            showToast(`💬 Sottotitoli: ${name}`);
          });
          settingsListSubtitles.appendChild(opt);
        });
      }
    }

    // 3. AUDIO TRACKS
    if (settingsListAudio) {
      settingsListAudio.innerHTML = '';
      if (currentHls && currentHls.audioTracks && currentHls.audioTracks.length > 0) {
        currentHls.audioTracks.forEach((track, idx) => {
          const opt = document.createElement('div');
          const name = track.name || track.lang || `Audio ${idx + 1}`;
          opt.className = `settings-option ${currentHls.audioTrack === idx ? 'active' : ''}`;
          opt.textContent = name;
          opt.addEventListener('click', () => {
            currentHls.audioTrack = idx;
            if (settingLblAudio) settingLblAudio.textContent = name;
            setupHlsSettings();
            showToast(`🎧 Audio: ${name}`);
          });
          settingsListAudio.appendChild(opt);
        });
      } else {
        settingsListAudio.innerHTML = '<div class="settings-option active">Predefinita (Italiano)</div>';
      }
    }

    // 4. SPEED SELECTION LISTENERS
    const speedOpts = document.querySelectorAll('#settings-list-speed .settings-option');
    speedOpts.forEach(opt => {
      opt.addEventListener('click', () => {
        const speedVal = parseFloat(opt.getAttribute('data-speed'));
        if (scStreamVideo) scStreamVideo.playbackRate = speedVal;
        if (settingLblSpeed) settingLblSpeed.textContent = `${speedVal}x`;
        speedOpts.forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        showToast(`⚡ Velocità: ${speedVal}x`);
      });
    });
  }

  // OPEN PLAYER MODAL FUNCTION
  function openStreamPlayerModal(mediaInfo) {
    if (!streamPlayerModal) return;
    currentActiveMedia = mediaInfo;
    const titleText = mediaInfo.title || "Riproduzione Streaming";
    if (streamMediaTitle) streamMediaTitle.textContent = titleText;
    if (floatPlayerTitle) floatPlayerTitle.textContent = titleText;
    
    streamPlayerModal.classList.remove('hidden');
    streamPlayerModal.classList.add('is-fullscreen');
    streamPlayerModal.classList.remove('netflix-opening');
    void streamPlayerModal.offsetWidth;
    streamPlayerModal.classList.add('netflix-opening');
    if (floatSettingsMenu) floatSettingsMenu.classList.add('hidden');

    const targetUrl = mediaInfo.url || '';
    const isEmbedUrl = targetUrl.includes('vidsrc') || targetUrl.includes('embed') || targetUrl.includes('lookmovie') || targetUrl.includes('superembed') || targetUrl.includes('autoembed') || targetUrl.includes('animeworld.ac/play');

    const videoContainer = document.getElementById('sc-stream-video-container') || (scStreamVideo ? scStreamVideo.parentElement : null);
    const floatControls = document.querySelector('.float-controls-panel');
    let embedIframe = document.getElementById('sc-stream-embed-iframe');

    if (currentHls) {
      currentHls.destroy();
      currentHls = null;
    }

    if (isEmbedUrl) {
      // Show clean interactive embed player for English/International sources
      if (scStreamVideo) {
        scStreamVideo.style.display = 'none';
        scStreamVideo.pause();
      }
      if (floatControls) floatControls.style.display = 'none';

      if (!embedIframe && videoContainer) {
        embedIframe = document.createElement('iframe');
        embedIframe.id = 'sc-stream-embed-iframe';
        embedIframe.allow = "autoplay; fullscreen; encrypted-media; picture-in-picture";
        embedIframe.style.cssText = "width: 100%; height: 100%; border: none; position: absolute; inset: 0; z-index: 2; background: #000;";
        videoContainer.appendChild(embedIframe);
      }
      if (embedIframe) {
        embedIframe.style.display = 'block';
        embedIframe.src = targetUrl;
      }
      return;
    }

    // Direct HLS / StreamingCommunity Video Stream
    if (embedIframe) {
      embedIframe.style.display = 'none';
      embedIframe.src = 'about:blank';
    }
    if (scStreamVideo) scStreamVideo.style.display = 'block';
    if (floatControls) floatControls.style.display = 'flex';

    const proxyManifestUrl = `/api/stream/proxy?url=${encodeURIComponent(targetUrl)}`;

    const onMediaReady = () => {
      if (scStreamVideo) {
        scStreamVideo.play().catch(() => {});
        updatePlayPauseUI();
        setupHlsSettings();
        resetControlsHideTimer();
        if (mediaInfo.resumeTime && mediaInfo.resumeTime > 0) {
          scStreamVideo.currentTime = mediaInfo.resumeTime;
          showToast(`▶ Ripresa visione da ${formatPlayerTime(mediaInfo.resumeTime)}`);
        }
      }
    };

    if (typeof Hls !== 'undefined' && Hls.isSupported() && scStreamVideo) {
      currentHls = new Hls({
        debug: false,
        enableWorker: true,
        lowLatencyMode: true,
      });
      currentHls.loadSource(proxyManifestUrl);
      currentHls.attachMedia(scStreamVideo);
      currentHls.on(Hls.Events.MANIFEST_PARSED, onMediaReady);
      currentHls.on(Hls.Events.LEVEL_SWITCHED, (event, data) => {
        if (currentHls.currentLevel === -1 && settingLblQuality && currentHls.levels[data.level]) {
          const h = currentHls.levels[data.level].height;
          settingLblQuality.textContent = h ? `Auto (${h}p)` : 'Auto';
        }
      });
    } else if (scStreamVideo && scStreamVideo.canPlayType('application/vnd.apple.mpegurl')) {
      scStreamVideo.src = proxyManifestUrl;
      onMediaReady();
    } else {
      showAlert("Formato streaming non supportato su questo dispositivo.");
    }
  }

  function closeStreamPlayerModal() {
    saveContinueWatchingProgress();
    if (controlsHideTimer) clearTimeout(controlsHideTimer);
    if (streamPlayerModal) {
      streamPlayerModal.classList.remove('is-fullscreen');
      streamPlayerModal.classList.remove('netflix-opening');
      streamPlayerModal.classList.add('hidden');
    }
    if (floatSettingsMenu) floatSettingsMenu.classList.add('hidden');

    const embedIframe = document.getElementById('sc-stream-embed-iframe');
    if (embedIframe) {
      embedIframe.style.display = 'none';
      embedIframe.src = 'about:blank';
    }

    if (scStreamVideo) {
      scStreamVideo.pause();
      scStreamVideo.src = '';
    }
    if (currentHls) {
      currentHls.destroy();
      currentHls = null;
    }
    currentActiveMedia = null;
  }

  if (btnCloseStreamModal) btnCloseStreamModal.addEventListener('click', closeStreamPlayerModal);
  if (btnFloatClose) btnFloatClose.addEventListener('click', closeStreamPlayerModal);

  // YOUTUBE KEYBOARD SHORTCUTS LOGIC
  function handlePlayerKeydown(e) {
    if (!streamPlayerModal || streamPlayerModal.classList.contains('hidden') || !scStreamVideo) return;
    
    const activeEl = document.activeElement;
    if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) return;

    const key = e.key ? e.key.toLowerCase() : '';
    const code = e.code || '';

    // Reset auto-hide timer on keyboard activity
    resetControlsHideTimer();

    // Space or K -> Play/Pause
    if (code === 'Space' || code === 'KeyK' || key === 'k' || key === ' ') {
      e.preventDefault();
      togglePlayPause();
    }
    // F -> Fullscreen
    else if (code === 'KeyF' || key === 'f') {
      e.preventDefault();
      toggleFullscreen();
    }
    // J -> -10s
    else if (code === 'KeyJ') {
      e.preventDefault();
      scStreamVideo.currentTime = Math.max(0, scStreamVideo.currentTime - 10);
      showToast("⏪ -10 sec");
    }
    // L -> +10s
    else if (code === 'KeyL') {
      e.preventDefault();
      scStreamVideo.currentTime = Math.min(scStreamVideo.duration || 0, scStreamVideo.currentTime + 10);
      showToast("⏩ +10 sec");
    }
    // Left Arrow -> -5s
    else if (code === 'ArrowLeft') {
      e.preventDefault();
      scStreamVideo.currentTime = Math.max(0, scStreamVideo.currentTime - 5);
      showToast("◀ -5 sec");
    }
    // Right Arrow -> +5s
    else if (code === 'ArrowRight') {
      e.preventDefault();
      scStreamVideo.currentTime = Math.min(scStreamVideo.duration || 0, scStreamVideo.currentTime + 5);
      showToast("▶ +5 sec");
    }
    // Up Arrow -> Volume +5%
    else if (code === 'ArrowUp') {
      e.preventDefault();
      scStreamVideo.volume = Math.min(1, scStreamVideo.volume + 0.05);
      if (floatVolumeSlider) floatVolumeSlider.value = scStreamVideo.volume;
      updateVolumeIcons();
      showVolumePopup(scStreamVideo.volume);
    }
    // Down Arrow -> Volume -5%
    else if (code === 'ArrowDown') {
      e.preventDefault();
      scStreamVideo.volume = Math.max(0, scStreamVideo.volume - 0.05);
      if (floatVolumeSlider) floatVolumeSlider.value = scStreamVideo.volume;
      updateVolumeIcons();
      showVolumePopup(scStreamVideo.volume);
    }
    // M -> Mute
    else if (code === 'KeyM') {
      e.preventDefault();
      scStreamVideo.muted = !scStreamVideo.muted;
      if (floatVolumeSlider) floatVolumeSlider.value = scStreamVideo.muted ? 0 : scStreamVideo.volume;
      updateVolumeIcons();
      showToast(scStreamVideo.muted ? "🔇 Muto" : "🔊 Audio Attivo");
    }
    // 0-9 -> Jump 0% to 90%
    else if (/^Digit[0-9]$/.test(code)) {
      e.preventDefault();
      const num = parseInt(code.replace('Digit', ''));
      if (scStreamVideo.duration) {
        scStreamVideo.currentTime = (num / 10) * scStreamVideo.duration;
        showToast(`⏱ ${num * 10}%`);
      }
    }
    // < or Shift+, -> Speed -0.25x
    else if (key === '<' || (e.shiftKey && code === 'Comma')) {
      e.preventDefault();
      scStreamVideo.playbackRate = Math.max(0.25, scStreamVideo.playbackRate - 0.25);
      if (settingLblSpeed) settingLblSpeed.textContent = `${scStreamVideo.playbackRate}x`;
      showToast(`⚡ Velocità ${scStreamVideo.playbackRate}x`);
    }
    // > or Shift+. -> Speed +0.25x
    else if (key === '>' || (e.shiftKey && code === 'Period')) {
      e.preventDefault();
      scStreamVideo.playbackRate = Math.min(2.5, scStreamVideo.playbackRate + 0.25);
      if (settingLblSpeed) settingLblSpeed.textContent = `${scStreamVideo.playbackRate}x`;
      showToast(`⚡ Velocità ${scStreamVideo.playbackRate}x`);
    }
    // Escape -> Close player modal if not fullscreen
    else if (code === 'Escape') {
      if (!document.fullscreenElement && !document.webkitFullscreenElement) {
        closeStreamPlayerModal();
      }
    }
  }

  document.addEventListener('keydown', handlePlayerKeydown);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' || e.code === 'Escape') {
      if (scDetailsModal && !scDetailsModal.classList.contains('hidden')) {
        closeDetailsModal();
      } else if (qualityModal && !qualityModal.classList.contains('hidden')) {
        closeModal();
      }
    }
  });

  // ==========================================
  // GOOGLE AUTHENTICATION & PROFILE ENGINE
  // ==========================================
  let currentUser = JSON.parse(localStorage.getItem('sc_google_user') || 'null');
  let authPollInterval = null;

  const btnGoogleLogin = document.getElementById('btn-google-login');
  const googleUserProfile = document.getElementById('google-user-profile');
  const userAvatarImg = document.getElementById('user-avatar-img');
  const userDisplayName = document.getElementById('user-display-name');
  const btnUserLogout = document.getElementById('btn-user-logout');
  const googleLoginModal = document.getElementById('google-login-modal');
  const btnCloseGoogleModal = document.getElementById('btn-close-google-modal');
  const btnDoGoogleOAuthBrowser = document.getElementById('btn-do-google-oauth-browser');
  const inputGoogleEmail = document.getElementById('input-google-email');
  const inputGoogleName = document.getElementById('input-google-name');
  const btnDoCustomLogin = document.getElementById('btn-do-custom-login');

  function updateAuthUI() {
    if (currentUser && currentUser.email) {
      if (btnGoogleLogin) btnGoogleLogin.classList.add('hidden');
      if (googleUserProfile) {
        googleUserProfile.classList.remove('hidden');
        userAvatarImg.src = currentUser.avatar || `https://ui-avatars.com/api/?name=${encodeURIComponent(currentUser.name || 'User')}&background=6366f1&color=fff&size=128`;
        userDisplayName.textContent = currentUser.name || currentUser.email.split('@')[0];
      }
    } else {
      if (btnGoogleLogin) btnGoogleLogin.classList.remove('hidden');
      if (googleUserProfile) googleUserProfile.classList.add('hidden');
    }
  }

  // Check backend auth status on boot
  async function syncBackendAuthStatus() {
    try {
      const res = await fetch('/api/auth/status');
      if (res.ok) {
        const data = await res.json();
        if (data.authenticated && data.user) {
          currentUser = data.user;
          localStorage.setItem('sc_google_user', JSON.stringify(currentUser));
          updateAuthUI();
        } else if (!currentUser) {
          updateAuthUI();
        }
      }
    } catch (e) {
      updateAuthUI();
    }
  }
  syncBackendAuthStatus();

  if (btnGoogleLogin) {
    btnGoogleLogin.addEventListener('click', () => {
      if (googleLoginModal) googleLoginModal.classList.remove('hidden');
    });
  }

  if (btnCloseGoogleModal) {
    btnCloseGoogleModal.addEventListener('click', () => {
      if (googleLoginModal) googleLoginModal.classList.add('hidden');
      if (authPollInterval) {
        clearInterval(authPollInterval);
        authPollInterval = null;
      }
      if (btnDoGoogleOAuthBrowser) {
        btnDoGoogleOAuthBrowser.disabled = false;
        btnDoGoogleOAuthBrowser.innerHTML = `
          <svg width="22" height="22" viewBox="0 0 24 24"><path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"/><path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.35 24 12 24z"/><path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 9.99 0 12s.45 3.82 1.25 5.42l4.03-3.15z"/><path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.35 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/></svg>
          <span>Accedi con Google</span>
        `;
      }
    });
  }

  // 1. REAL GOOGLE OAUTH IN SYSTEM BROWSER
  if (btnDoGoogleOAuthBrowser) {
    btnDoGoogleOAuthBrowser.addEventListener('click', async () => {
      showToast("Apertura di Google nel browser predefinito...");
      btnDoGoogleOAuthBrowser.disabled = true;
      btnDoGoogleOAuthBrowser.innerHTML = `
        <span style="display:inline-block; width:16px; height:16px; border:2px solid rgba(255,255,255,0.3); border-top-color:#fff; border-radius:50%; animation: spin 0.8s linear infinite; margin-right:8px;"></span>
        <span>In attesa di autorizzazione nel browser...</span>
      `;

      try {
        const res = await fetch('/api/auth/google/login');
        const data = await res.json();
        
        if (authPollInterval) clearInterval(authPollInterval);
        
        let pollCount = 0;
        authPollInterval = setInterval(async () => {
          pollCount++;
          if (pollCount > 120) { // 2 minutes timeout
            clearInterval(authPollInterval);
            authPollInterval = null;
            btnDoGoogleOAuthBrowser.disabled = false;
            btnDoGoogleOAuthBrowser.innerHTML = `
              <svg width="22" height="22" viewBox="0 0 24 24"><path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"/><path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.35 24 12 24z"/><path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 9.99 0 12s.45 3.82 1.25 5.42l4.03-3.15z"/><path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.35 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/></svg>
              <span>Accedi con Google</span>
            `;
            return;
          }

          try {
            const statusRes = await fetch('/api/auth/status');
            if (statusRes.ok) {
              const statusData = await statusRes.json();
              if (statusData.authenticated && statusData.user) {
                clearInterval(authPollInterval);
                authPollInterval = null;
                currentUser = statusData.user;
                localStorage.setItem('sc_google_user', JSON.stringify(currentUser));
                updateAuthUI();
                if (googleLoginModal) googleLoginModal.classList.add('hidden');
                btnDoGoogleOAuthBrowser.disabled = false;
                btnDoGoogleOAuthBrowser.innerHTML = `
                  <svg width="22" height="22" viewBox="0 0 24 24"><path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"/><path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.35 24 12 24z"/><path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 9.99 0 12s.45 3.82 1.25 5.42l4.03-3.15z"/><path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.35 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/></svg>
                  <span>Accedi con Google</span>
                `;
                showToast(`🎉 Accesso Google completato: ${currentUser.name}!`);
              }
            }
          } catch (err) {}
        }, 1000);

      } catch (err) {
        showToast("Impossibile avviare il login Google.");
        btnDoGoogleOAuthBrowser.disabled = false;
        btnDoGoogleOAuthBrowser.innerHTML = `
          <svg width="22" height="22" viewBox="0 0 24 24"><path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"/><path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.35 24 12 24z"/><path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 9.99 0 12s.45 3.82 1.25 5.42l4.03-3.15z"/><path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.35 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/></svg>
          <span>Accedi con Google</span>
        `;
      }
    });
  }

  // 2. DIRECT CUSTOM PROFILE LINK
  if (btnDoCustomLogin) {
    btnDoCustomLogin.addEventListener('click', () => {
      const email = (inputGoogleEmail.value || '').trim();
      let name = (inputGoogleName.value || '').trim();

      if (!email || !email.includes('@')) {
        showToast('Inserisci un indirizzo email Google valido (es. nome@gmail.com)');
        return;
      }

      if (!name) {
        const prefix = email.split('@')[0];
        name = prefix.charAt(0).toUpperCase() + prefix.slice(1);
      }

      const avatarUrl = `https://ui-avatars.com/api/?name=${encodeURIComponent(name)}&background=6366f1&color=fff&size=128&bold=true`;

      currentUser = {
        id: `g_${Date.now()}`,
        name: name,
        email: email,
        avatar: avatarUrl
      };

      localStorage.setItem('sc_google_user', JSON.stringify(currentUser));
      updateAuthUI();
      if (googleLoginModal) googleLoginModal.classList.add('hidden');
      showToast(`🎉 Account collegato con successo: ${name} (${email})`);
    });
  }

  if (btnUserLogout) {
    btnUserLogout.addEventListener('click', async () => {
      currentUser = null;
      localStorage.removeItem('sc_google_user');
      try {
        await fetch('/api/auth/logout', { method: 'POST' });
      } catch(e) {}
      updateAuthUI();
      showToast('Disconnessione effettuata.');
    });
  }

  updateAuthUI();

  // SMART TV & MIRACAST CASTING HUB
  const smartCastModal = document.getElementById('smart-cast-modal');
  const btnCastStream = document.getElementById('btn-cast-stream');
  const btnFloatCast = document.getElementById('btn-float-cast');
  const btnCloseCastModal = document.getElementById('btn-close-cast-modal');
  const castTvUrlTxt = document.getElementById('cast-tv-url-txt');
  const castQrImg = document.getElementById('cast-qr-img');
  const btnCopyTvUrl = document.getElementById('btn-copy-tv-url');
  const btnDoNativeCast = document.getElementById('btn-do-native-cast');

  async function openSmartCastHub() {
    if (!smartCastModal) return;
    smartCastModal.classList.remove('hidden');

    try {
      // Sync current film state to backend for TV
      if (currentActiveMedia && currentActiveMedia.url) {
        fetch('/api/cast/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: currentActiveMedia.title || 'Streaming',
            url: currentActiveMedia.url,
            time: scStreamVideo ? scStreamVideo.currentTime : 0,
            isPlaying: scStreamVideo ? !scStreamVideo.paused : true
          })
        }).catch(() => {});
      }

      const res = await fetch('/api/cast/info');
      if (res.ok) {
        const data = await res.json();
        const tvUrl = data.tv_url || `http://${window.location.hostname}:5555/tv`;
        if (castTvUrlTxt) castTvUrlTxt.textContent = tvUrl;
        if (castQrImg) {
          castQrImg.src = `https://api.qrserver.com/v1/create-qr-code/?data=${encodeURIComponent(tvUrl)}&size=200x200&margin=2`;
        }
      }
    } catch (e) {
      console.warn("Cast info fetch error:", e);
    }
  }

  if (btnCastStream) btnCastStream.addEventListener('click', openSmartCastHub);
  if (btnFloatCast) btnFloatCast.addEventListener('click', openSmartCastHub);
  if (btnCloseCastModal) {
    btnCloseCastModal.addEventListener('click', () => {
      if (smartCastModal) smartCastModal.classList.add('hidden');
    });
  }

  if (btnCopyTvUrl) {
    btnCopyTvUrl.addEventListener('click', () => {
      const txt = castTvUrlTxt ? castTvUrlTxt.textContent : '';
      if (txt) {
        navigator.clipboard.writeText(txt);
        showToast('Link per la TV copiato!');
      }
    });
  }

  // ==========================================
  // 🎲 RANDOM MOVIE DISCOVERY ENGINE
  // ==========================================
  let currentRandomMovie = null;
  const btnRandomMovie = document.getElementById('btn-random-movie');
  const scRandomModal = document.getElementById('sc-random-modal');
  const btnCloseRandomModal = document.getElementById('btn-close-random-modal');
  const btnRandomReroll = document.getElementById('btn-random-reroll');
  const btnRandomWatch = document.getElementById('btn-random-watch');
  const btnRandomDetails = document.getElementById('btn-random-details');
  const scRandomHeroContainer = document.getElementById('sc-random-hero-container');
  const scRandomTypeBadge = document.getElementById('sc-random-type-badge');

  async function fetchAndShowRandomMovie() {
    if (!scRandomModal) return;
    scRandomModal.classList.remove('hidden');

    if (btnRandomReroll) btnRandomReroll.classList.add('loading');
    if (scRandomHeroContainer) {
      scRandomHeroContainer.innerHTML = `
        <div style="text-align: center; padding: 40px 20px; width: 100%;">
          <div class="dice-spin-icon" style="font-size: 2.8rem; margin-bottom: 12px; animation: diceRollAnimation 0.8s linear infinite;">🎲</div>
          <h3 style="color: #fff; font-size: 1.15rem; margin-bottom: 6px;">Estrazione Film Casuale...</h3>
          <p style="color: var(--text-muted); font-size: 0.85rem;">Sto cercando un titolo speciale tra le migliaia di film su StreamingCommunity...</p>
        </div>
      `;
    }

    try {
      const res = await fetch('/api/sc/random');
      const data = await res.json();

      if (btnRandomReroll) btnRandomReroll.classList.remove('loading');

      if (!data || !data.success || !data.movie) {
        if (scRandomHeroContainer) {
          scRandomHeroContainer.innerHTML = `
            <div style="text-align: center; padding: 30px 20px; width: 100%;">
              <p style="color: #ef4444; font-weight: 700; margin-bottom: 10px;">Impossibile estrarre un film in questo momento.</p>
              <button class="btn-primary btn-sm" onclick="fetchAndShowRandomMovie()">Riprova Estrazione</button>
            </div>
          `;
        }
        return;
      }

      currentRandomMovie = data.movie;
      renderRandomMovieCard(currentRandomMovie);
    } catch (e) {
      console.error("Random movie fetch error:", e);
      if (btnRandomReroll) btnRandomReroll.classList.remove('loading');
      if (scRandomHeroContainer) {
        scRandomHeroContainer.innerHTML = `
          <div style="text-align: center; padding: 30px 20px; width: 100%;">
            <p style="color: #ef4444; margin-bottom: 10px;">Errore di connessione durante l'estrazione.</p>
            <button class="btn-secondary btn-sm" onclick="fetchAndShowRandomMovie()">Riprova</button>
          </div>
        `;
      }
    }
  }

  function renderRandomMovieCard(item) {
    if (!scRandomHeroContainer || !item) return;

    if (scRandomTypeBadge) {
      scRandomTypeBadge.textContent = item.type === 'tv' ? 'Serie TV' : 'Film';
    }

    const title = escapeHtml(item.name || 'Titolo Sconosciuto');
    const plot = item.plot ? escapeHtml(item.plot) : 'Nessuna descrizione disponibile per questo titolo. Clicca su Guarda Ora per iniziare la riproduzione streaming in alta qualità.';
    const year = item.release_date || 'N/D';
    const poster = item.poster || item.cover || 'https://via.placeholder.com/200x300?text=No+Poster';
    
    let genresHtml = '';
    if (Array.isArray(item.genres) && item.genres.length > 0) {
      genresHtml = item.genres.slice(0, 4).map(g => `<span class="sc-genre-badge">${escapeHtml(g)}</span>`).join('');
    }

    let scoreHtml = '';
    if (item.score) {
      scoreHtml = `<span class="sc-random-meta-tag sc-random-score">★ ${escapeHtml(String(item.score))}</span>`;
    }

    let durationHtml = '';
    if (item.runtime) {
      durationHtml = `<span class="sc-random-meta-tag">⏱️ ${escapeHtml(String(item.runtime))} min</span>`;
    }

    scRandomHeroContainer.innerHTML = `
      <div class="sc-random-poster-box">
        <img src="${escapeAttr(poster)}" alt="${escapeAttr(title)}" onerror="this.src='https://via.placeholder.com/200x300?text=No+Poster'" />
      </div>
      <div class="sc-random-info-box">
        <h3 class="sc-random-title">${title}</h3>
        <div class="sc-random-meta">
          <span class="sc-random-meta-tag">📅 ${escapeHtml(String(year))}</span>
          ${scoreHtml}
          ${durationHtml}
        </div>
        ${genresHtml ? `<div class="sc-random-genres">${genresHtml}</div>` : ''}
        <div class="sc-random-plot">
          ${plot}
        </div>
      </div>
    `;
  }

  if (btnRandomMovie) btnRandomMovie.addEventListener('click', fetchAndShowRandomMovie);
  if (btnRandomReroll) btnRandomReroll.addEventListener('click', fetchAndShowRandomMovie);
  if (btnCloseRandomModal) {
    btnCloseRandomModal.addEventListener('click', () => {
      if (scRandomModal) scRandomModal.classList.add('hidden');
    });
  }

  if (btnRandomDetails) {
    btnRandomDetails.addEventListener('click', () => {
      if (scRandomModal) scRandomModal.classList.add('hidden');
      if (currentRandomMovie && currentRandomMovie.id) {
        loadTitleDetails(currentRandomMovie.id, currentRandomMovie.slug || '');
      }
    });
  }

  if (btnRandomWatch) {
    btnRandomWatch.addEventListener('click', async () => {
      if (scRandomModal) scRandomModal.classList.add('hidden');
      if (currentRandomMovie && currentRandomMovie.id) {
        showToast(`Caricamento di "${currentRandomMovie.name}" in corso...`);
        try {
          loadTitleDetails(currentRandomMovie.id, currentRandomMovie.slug || '');
        } catch (e) {
          console.error("Watch trigger error:", e);
        }
      }
    });
  }

  // ==========================================
  // ✨ CINEBOT AI CHATBOT ENGINE (GOOGLE GEMINI)
  // ==========================================
  const DEFAULT_GEMINI_KEY = atob("QVEuQWI4Uk42S3FvMEZBci1MQkJPTndXWUR0dTZwVUJLUHhHSkpPMmFOOV9Ka29GUlVnc0E=");
  if ((!localStorage.getItem('sc_gemini_api_key') || !localStorage.getItem('sc_gemini_api_key').trim()) && DEFAULT_GEMINI_KEY) {
    localStorage.setItem('sc_gemini_api_key', DEFAULT_GEMINI_KEY);
  }

  let aiConversationHistory = [];
  const btnHeaderAiChat = document.getElementById('btn-header-ai-chat');
  const btnHomeAiBot = document.getElementById('btn-home-ai-bot');
  const btnFloatAiChat = document.getElementById('btn-float-ai-chat');
  const aiChatModal = document.getElementById('ai-chat-modal');
  const btnCloseAiChat = document.getElementById('btn-close-ai-chat');
  const btnAiToggleSettings = document.getElementById('btn-ai-toggle-settings');
  const aiSettingsDrawer = document.getElementById('ai-settings-drawer');
  const inputGeminiKey = document.getElementById('input-gemini-key');
  const btnSaveGeminiKey = document.getElementById('btn-save-gemini-key');
  const aiKeyStatusText = document.getElementById('ai-key-status-text');
  const aiChatMessages = document.getElementById('ai-chat-messages');
  const aiChatForm = document.getElementById('ai-chat-form');
  const inputAiChatMsg = document.getElementById('input-ai-chat-msg');
  const btnSendAiChat = document.getElementById('btn-send-ai-chat');

  function getStoredGeminiKey() {
    return (localStorage.getItem('sc_gemini_api_key') || DEFAULT_GEMINI_KEY).trim();
  }

  function updateApiKeyStatusUI() {
    const key = getStoredGeminiKey();
    const dot = document.querySelector('.status-indicator-dot');
    if (inputGeminiKey && key) {
      inputGeminiKey.value = key;
    }

    if (key) {
      if (aiKeyStatusText) aiKeyStatusText.textContent = 'Chiave Gemini integrata e attiva';
      if (dot) {
        dot.className = 'status-indicator-dot active';
      }
    } else {
      if (aiKeyStatusText) aiKeyStatusText.textContent = 'Nessuna API Key inserita (clicca per configurarla)';
      if (dot) {
        dot.className = 'status-indicator-dot error';
      }
    }
  }

  function openAiChatModal() {
    if (!aiChatModal) return;
    aiChatModal.classList.remove('hidden');
    updateApiKeyStatusUI();

    setTimeout(() => {
      if (inputAiChatMsg) inputAiChatMsg.focus();
    }, 150);
  }

  if (btnHeaderAiChat) btnHeaderAiChat.addEventListener('click', openAiChatModal);
  if (btnHomeAiBot) btnHomeAiBot.addEventListener('click', openAiChatModal);
  if (btnFloatAiChat) btnFloatAiChat.addEventListener('click', openAiChatModal);
  if (btnCloseAiChat) {
    btnCloseAiChat.addEventListener('click', () => {
      if (aiChatModal) aiChatModal.classList.add('hidden');
    });
  }

  if (btnAiToggleSettings) {
    btnAiToggleSettings.addEventListener('click', () => {
      if (aiSettingsDrawer) {
        aiSettingsDrawer.classList.toggle('hidden');
      }
    });
  }

  if (btnSaveGeminiKey) {
    btnSaveGeminiKey.addEventListener('click', async () => {
      const key = (inputGeminiKey.value || '').trim();
      if (!key) {
        showToast('⚠️ Inserisci una chiave API valida.');
        return;
      }

      btnSaveGeminiKey.textContent = 'Verifica in corso...';
      btnSaveGeminiKey.disabled = true;

      try {
        const res = await fetch('/api/ai/test-key', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ apiKey: key })
        });
        const data = await res.json();

        btnSaveGeminiKey.textContent = 'Salva e Testa';
        btnSaveGeminiKey.disabled = false;

        if (data && data.success) {
          localStorage.setItem('sc_gemini_api_key', key);
          updateApiKeyStatusUI();
          showToast('✅ API Key di Gemini salvata e verificata con successo!');
          if (aiSettingsDrawer) aiSettingsDrawer.classList.add('hidden');
        } else {
          showToast(`❌ Verifica fallita: ${data.error || 'Chiave non valida'}`);
        }
      } catch (err) {
        btnSaveGeminiKey.textContent = 'Salva e Testa';
        btnSaveGeminiKey.disabled = false;
        // Even if local network check fails, save key
        localStorage.setItem('sc_gemini_api_key', key);
        updateApiKeyStatusUI();
        showToast('Chiave salvata localmente.');
      }
    });
  }

  function formatAiMarkdown(text) {
    if (!text) return '';
    let formatted = escapeHtml(text);
    
    // Bold: **text**
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    
    // Highlighted titles [[Title]]
    formatted = formatted.replace(/\[\[(.*?)\]\]/g, '<span style="color: #38bdf8; font-weight: 700; text-decoration: underline; cursor: pointer;" onclick="searchAndShowFromChat(\'$1\')">$1</span>');
    
    // Bullet points
    formatted = formatted.replace(/^\* (.*$)/gim, '<li>$1</li>');
    formatted = formatted.replace(/^- (.*$)/gim, '<li>$1</li>');
    formatted = formatted.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
    
    // Paragraphs
    formatted = formatted.replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>');
    return `<p>${formatted}</p>`;
  }

  window.searchAndShowFromChat = function(titleName) {
    if (!titleName) return;
    if (aiChatModal) aiChatModal.classList.add('hidden');
    switchTab('sc-portal');
    const searchInput = document.getElementById('sc-search-input');
    if (searchInput) {
      searchInput.value = titleName;
      searchCatalog(titleName);
    }
  };

  async function handleSendAiMessage(msgText) {
    const text = (msgText || (inputAiChatMsg ? inputAiChatMsg.value : '')).trim();
    if (!text) return;

    const apiKey = getStoredGeminiKey();
    if (!apiKey) {
      if (aiSettingsDrawer) aiSettingsDrawer.classList.remove('hidden');
      showToast('⚠️ Inserisci prima la tua API Key di Gemini nelle impostazioni in alto.');
      return;
    }

    if (inputAiChatMsg) inputAiChatMsg.value = '';

    // Append User Message
    const userMsgEl = document.createElement('div');
    userMsgEl.className = 'ai-msg ai-msg-user';
    userMsgEl.innerHTML = `
      <div class="ai-msg-avatar">👤</div>
      <div class="ai-msg-content">${escapeHtml(text)}</div>
    `;
    if (aiChatMessages) {
      aiChatMessages.appendChild(userMsgEl);
      aiChatMessages.scrollTop = aiChatMessages.scrollHeight;
    }

    // Append Bot Loading Message
    const botLoadingEl = document.createElement('div');
    botLoadingEl.className = 'ai-msg ai-msg-bot';
    botLoadingEl.innerHTML = `
      <div class="ai-msg-avatar">✨</div>
      <div class="ai-msg-content">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="spinner"></span>
          <span style="color: var(--text-muted); font-size: 0.85rem;">CineBot sta analizzando il cinema per te...</span>
        </div>
      </div>
    `;
    if (aiChatMessages) {
      aiChatMessages.appendChild(botLoadingEl);
      aiChatMessages.scrollTop = aiChatMessages.scrollHeight;
    }

    if (btnSendAiChat) btnSendAiChat.disabled = true;

    try {
      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          apiKey: apiKey,
          history: aiConversationHistory
        })
      });

      const data = await res.json();
      if (btnSendAiChat) btnSendAiChat.disabled = false;

      if (!data || !data.success) {
        botLoadingEl.querySelector('.ai-msg-content').innerHTML = `
          <p style="color: #ef4444;">⚠️ <strong>Errore:</strong> ${escapeHtml(data.error || 'Impossibile completare la richiesta.')}</p>
          <p style="font-size: 0.8rem; color: var(--text-muted);">Verifica che la tua API Key Gemini sia corretta cliccando sull'icona delle impostazioni in alto a destra.</p>
        `;
        return;
      }

      // Add to conversation history
      aiConversationHistory.push({ role: 'user', content: text });
      aiConversationHistory.push({ role: 'model', content: data.reply });

      let contentHtml = formatAiMarkdown(data.reply);

      // Render catalog matches if present
      if (Array.isArray(data.catalog_matches) && data.catalog_matches.length > 0) {
        let cardsHtml = '<div class="ai-catalog-matches-grid">';
        data.catalog_matches.forEach(item => {
          const itemTitle = escapeHtml(item.name || '');
          const itemPoster = item.poster || item.cover || 'https://via.placeholder.com/100x150?text=No+Poster';
          const itemYear = item.release_date || '';
          const itemType = item.type === 'tv' ? 'Serie TV' : 'Film';
          const itemId = escapeAttr(String(item.id));
          const itemSlug = escapeAttr(item.slug || '');

          cardsHtml += `
            <div class="ai-mini-card">
              <img class="ai-mini-card-poster" src="${escapeAttr(itemPoster)}" alt="${itemTitle}" onerror="this.src='https://via.placeholder.com/100x150?text=No+Poster'" />
              <div class="ai-mini-card-body">
                <div>
                  <div class="ai-mini-card-title">${itemTitle}</div>
                  <div class="ai-mini-card-meta">${itemType} • ${itemYear}</div>
                </div>
                <div class="ai-mini-card-actions">
                  <button class="btn-mini-watch" data-id="${itemId}" data-slug="${itemSlug}">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                    Guarda
                  </button>
                  <button class="btn-mini-details" data-id="${itemId}" data-slug="${itemSlug}">Dettagli</button>
                </div>
              </div>
            </div>
          `;
        });
        cardsHtml += '</div>';
        contentHtml += cardsHtml;
      }

      botLoadingEl.querySelector('.ai-msg-content').innerHTML = contentHtml;

      // Bind actions on mini cards
      botLoadingEl.querySelectorAll('.btn-mini-watch').forEach(btn => {
        btn.addEventListener('click', () => {
          const id = btn.getAttribute('data-id');
          const slug = btn.getAttribute('data-slug');
          if (aiChatModal) aiChatModal.classList.add('hidden');
          loadTitleDetails(id, slug);
        });
      });

      botLoadingEl.querySelectorAll('.btn-mini-details').forEach(btn => {
        btn.addEventListener('click', () => {
          const id = btn.getAttribute('data-id');
          const slug = btn.getAttribute('data-slug');
          if (aiChatModal) aiChatModal.classList.add('hidden');
          loadTitleDetails(id, slug);
        });
      });

      if (aiChatMessages) {
        aiChatMessages.scrollTop = aiChatMessages.scrollHeight;
      }

    } catch (ex) {
      if (btnSendAiChat) btnSendAiChat.disabled = false;
      botLoadingEl.querySelector('.ai-msg-content').innerHTML = `
        <p style="color: #ef4444;">Errore di connessione: ${escapeHtml(String(ex))}</p>
      `;
    }
  }

  if (aiChatForm) {
    aiChatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handleSendAiMessage();
    });
  }

  // Bind prompt chips
  document.querySelectorAll('.ai-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const prompt = chip.getAttribute('data-prompt');
      if (prompt) {
        handleSendAiMessage(prompt);
      }
    });
  });

  // Initialize Home Portal automatically
  initScPortal();
});


