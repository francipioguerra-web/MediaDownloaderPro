document.addEventListener('DOMContentLoaded', () => {
  const urlInput = document.getElementById('url-input');
  const btnAnalyze = document.getElementById('btn-analyze');
  const analyzeText = document.getElementById('analyze-text');
  const analyzeSpinner = document.getElementById('analyze-spinner');
  const alertBanner = document.getElementById('alert-banner');

  const previewSection = document.getElementById('preview-section');
  const previewImg = document.getElementById('preview-img');
  const previewFallbackIcon = document.getElementById('preview-fallback-icon');
  const previewSource = document.getElementById('preview-source');
  const previewDuration = document.getElementById('preview-duration');
  const previewSize = document.getElementById('preview-size');
  const previewTitle = document.getElementById('preview-title');
  const previewUrl = document.getElementById('preview-url');
  const btnDownloadNow = document.getElementById('btn-download-now');
  const btnCopyLink = document.getElementById('btn-copy-link');
  const copyLinkText = document.getElementById('copy-link-text');

  const activeSection = document.getElementById('active-downloads-section');
  const activeList = document.getElementById('active-downloads-list');

  const historyEmpty = document.getElementById('history-empty');
  const historyList = document.getElementById('history-list');
  const historyCount = document.getElementById('history-count');

  let currentAnalysis = null;
  const activePollers = {};
  const historyData = [];

  // Chip selection
  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      const radio = chip.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // Analyze URL
  btnAnalyze.addEventListener('click', analyzeCurrentUrl);
  urlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') analyzeCurrentUrl();
  });

  function analyzeCurrentUrl() {
    const url = urlInput.value.strip ? urlInput.value.strip() : urlInput.value.trim();
    if (!url) {
      showAlert("Per favore, inserisci un URL valido.");
      return;
    }

    hideAlert();
    setAnalyzingState(true);
    previewSection.classList.add('hidden');

    fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    })
    .then(r => r.json())
    .then(res => {
      setAnalyzingState(false);
      if (res.error) {
        showAlert(res.error);
      } else {
        currentAnalysis = res;
        renderPreview(res);
      }
    })
    .catch(err => {
      setAnalyzingState(false);
      showAlert("Errore durante l'analisi dell'URL: " + err);
    });
  }

  function renderPreview(data) {
    previewTitle.textContent = data.title || "Media Multimediale";
    previewUrl.textContent = data.url || "";
    previewSource.textContent = data.source || "WEB";
    previewDuration.textContent = data.duration || "N/D";
    previewSize.textContent = data.file_size || "N/D";

    if (data.thumbnail) {
      previewImg.src = data.thumbnail;
      previewImg.classList.remove('hidden');
      previewFallbackIcon.classList.add('hidden');
    } else {
      previewImg.classList.add('hidden');
      previewFallbackIcon.classList.remove('hidden');
    }

    previewSection.classList.remove('hidden');
  }

  // Copy Link Handlers
  if (btnCopyLink) {
    btnCopyLink.addEventListener('click', () => {
      if (!currentAnalysis || !currentAnalysis.url) return;
      copyTextToClipboard(currentAnalysis.url, copyLinkText);
    });
  }

  if (previewUrl) {
    previewUrl.addEventListener('click', () => {
      if (!currentAnalysis || !currentAnalysis.url) return;
      copyTextToClipboard(currentAnalysis.url, copyLinkText);
    });
  }

  function copyTextToClipboard(text, labelElement) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(showSuccessFeedback).catch(fallbackCopy);
    } else {
      fallbackCopy();
    }

    function fallbackCopy() {
      const textArea = document.createElement("textarea");
      textArea.value = text;
      textArea.style.position = "fixed";
      textArea.style.left = "-999999px";
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      try {
        document.execCommand('copy');
        showSuccessFeedback();
      } catch (err) {
        alert("Copia fallita: " + err);
      }
      document.body.removeChild(textArea);
    }

    function showSuccessFeedback() {
      if (labelElement) {
        const origText = labelElement.textContent;
        labelElement.textContent = "✓ Link Copiato!";
        setTimeout(() => {
          labelElement.textContent = origText;
        }, 2000);
      }
    }
  }

  // Start Download
  btnDownloadNow.addEventListener('click', () => {
    if (!currentAnalysis) return;

    const selectedChip = document.querySelector('input[name="format"]:checked');
    const formatChoice = selectedChip ? selectedChip.value : 'mp4';

    const payload = {
      url: currentAnalysis.url,
      media_type: currentAnalysis.type,
      format_choice: formatChoice,
      custom_title: currentAnalysis.title,
      custom_headers: currentAnalysis.headers
    };

    fetch('/api/download/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(res => {
      if (res.download_id) {
        addActiveDownloadItem(res.download_id, currentAnalysis.title, currentAnalysis.url);
        startPollingStatus(res.download_id);
        previewSection.classList.add('hidden');
        urlInput.value = '';
      } else {
        showAlert("Impossibile avviare il download.");
      }
    })
    .catch(err => {
      showAlert("Errore avvio download: " + err);
    });
  });

  function addActiveDownloadItem(downloadId, title, streamUrl) {
    activeSection.classList.remove('hidden');

    const itemCard = document.createElement('div');
    itemCard.className = 'download-item-card';
    itemCard.id = `card_${downloadId}`;

    itemCard.innerHTML = `
      <div class="download-item-info">
        <div class="download-item-title-wrapper">
          <span class="download-item-title">${escapeHtml(title)}</span>
          <span id="badge_status_${downloadId}" class="badge-status-paused hidden">In Pausa</span>
        </div>
        <div class="download-item-controls">
          <button id="btn_pause_${downloadId}" class="btn-ctrl btn-ctrl-pause" title="Metti in pausa o riprendi">
            <svg id="icon_pause_${downloadId}" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
            <span id="lbl_pause_${downloadId}">Pausa</span>
          </button>
          <button id="btn_cancel_${downloadId}" class="btn-ctrl btn-ctrl-cancel" title="Interrompi download">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            <span>Interrompi</span>
          </button>
        </div>
      </div>
      <div class="progress-bar-bg">
        <div id="bar_${downloadId}" class="progress-bar-fill"></div>
      </div>
      <div class="download-item-info">
        <span id="bytes_${downloadId}" class="download-item-meta">0 B / --</span>
        <span id="speed_${downloadId}" class="download-item-meta">Inizializzazione...</span>
        <span id="percent_${downloadId}" class="download-item-meta">0%</span>
      </div>
    `;

    activeList.appendChild(itemCard);

    const btnPause = itemCard.querySelector(`#btn_pause_${downloadId}`);
    const btnCancel = itemCard.querySelector(`#btn_cancel_${downloadId}`);

    let isPaused = false;

    btnPause.addEventListener('click', () => {
      if (isPaused) {
        fetch(`/api/download/resume/${downloadId}`, { method: 'POST' });
        isPaused = false;
      } else {
        fetch(`/api/download/pause/${downloadId}`, { method: 'POST' });
        isPaused = true;
      }
    });

    btnCancel.addEventListener('click', () => {
      fetch(`/api/download/cancel/${downloadId}`, { method: 'POST' });
    });
  }

  function startPollingStatus(downloadId) {
    const interval = setInterval(() => {
      fetch(`/api/download/status/${downloadId}`)
        .then(r => r.json())
        .then(data => {
          if (data.error) {
            clearInterval(interval);
            removeActiveCard(downloadId);
            showAlert(`Download fallito: ${data.error}`);
            return;
          }

          updateCardUI(downloadId, data);

          if (data.state === 'completed') {
            clearInterval(interval);
            removeActiveCard(downloadId);
            addToHistory(data.filename, data.download_url, data.url);
          } else if (data.state === 'cancelled') {
            clearInterval(interval);
            removeActiveCard(downloadId);
          } else if (data.state === 'error') {
            clearInterval(interval);
            removeActiveCard(downloadId);
            showAlert(`Download fallito: ${data.error}`);
          }
        })
        .catch(err => {
          console.error("Polling error:", err);
        });
    }, 500);

    activePollers[downloadId] = interval;
  }

  function updateCardUI(downloadId, data) {
    const bar = document.getElementById(`bar_${downloadId}`);
    const percentSpan = document.getElementById(`percent_${downloadId}`);
    const speedSpan = document.getElementById(`speed_${downloadId}`);
    const bytesSpan = document.getElementById(`bytes_${downloadId}`);
    const badge = document.getElementById(`badge_status_${downloadId}`);
    const lblPause = document.getElementById(`lbl_pause_${downloadId}`);
    const iconPause = document.getElementById(`icon_pause_${downloadId}`);

    if (bar) bar.style.width = `${data.percent}%`;
    if (percentSpan) percentSpan.textContent = `${data.percent}%`;
    if (bytesSpan) bytesSpan.textContent = `${data.downloaded} / ${data.total}`;

    if (data.state === 'paused') {
      if (bar) bar.classList.add('paused');
      if (badge) badge.classList.remove('hidden');
      if (lblPause) lblPause.textContent = "Riprendi";
      if (iconPause) iconPause.innerHTML = '<polygon points="5 3 19 12 5 21 5 3" fill="currentColor"></polygon>';
      if (speedSpan) speedSpan.textContent = "In pausa";
    } else {
      if (bar) bar.classList.remove('paused');
      if (badge) badge.classList.add('hidden');
      if (lblPause) lblPause.textContent = "Pausa";
      if (iconPause) iconPause.innerHTML = '<rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect>';
      if (speedSpan) speedSpan.textContent = data.speed;
    }
  }

  function removeActiveCard(downloadId) {
    const card = document.getElementById(`card_${downloadId}`);
    if (card) card.remove();
    if (activePollers[downloadId]) {
      clearInterval(activePollers[downloadId]);
      delete activePollers[downloadId];
    }
    if (activeList.children.length === 0) {
      activeSection.classList.add('hidden');
    }
  }

  function addToHistory(filename, downloadUrl, streamUrl) {
    historyData.unshift({ filename, downloadUrl, streamUrl, date: new Date().toLocaleTimeString() });

    historyEmpty.classList.add('hidden');
    historyList.classList.remove('hidden');
    historyCount.textContent = `${historyData.length} file`;

    const item = document.createElement('div');
    item.className = 'history-item';
    item.innerHTML = `
      <div class="history-file-info">
        <div class="file-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
        </div>
        <span class="file-name">${escapeHtml(filename)}</span>
      </div>
      <div class="history-actions">
        ${streamUrl ? `
        <button class="btn-icon btn-copy-hist" data-url="${escapeAttr(streamUrl)}" title="Copia link dello stream">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span class="lbl-hist-copy">Copia Link</span>
        </button>` : ''}
        <a class="btn-icon btn-download-device" href="${downloadUrl}" download="${escapeAttr(filename)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          Scarica su Dispositivo
        </a>
      </div>
    `;

    const btnCopyHist = item.querySelector('.btn-copy-hist');
    if (btnCopyHist) {
      btnCopyHist.addEventListener('click', (e) => {
        const urlToCopy = e.currentTarget.getAttribute('data-url');
        const lbl = e.currentTarget.querySelector('.lbl-hist-copy');
        copyTextToClipboard(urlToCopy, lbl);
      });
    }

    historyList.insertBefore(item, historyList.firstChild);
  }

  function setAnalyzingState(isAnalyzing) {
    if (isAnalyzing) {
      analyzeSpinner.classList.remove('hidden');
      analyzeText.textContent = "Analisi...";
      btnAnalyze.disabled = true;
    } else {
      analyzeSpinner.classList.add('hidden');
      analyzeText.textContent = "Analizza Media";
      btnAnalyze.disabled = false;
    }
  }

  function showAlert(message) {
    alertBanner.textContent = message;
    alertBanner.classList.remove('hidden');
  }

  function hideAlert() {
    alertBanner.classList.add('hidden');
    alertBanner.textContent = '';
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function escapeAttr(str) {
    if (!str) return '';
    return String(str)
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
});
