document.addEventListener('DOMContentLoaded', () => {
  const urlInput = document.getElementById('url-input');
  const btnPaste = document.getElementById('btn-paste');
  const btnAnalyze = document.getElementById('btn-analyze');
  const analyzeSpinner = document.getElementById('analyze-spinner');
  const analyzeText = document.getElementById('analyze-text');
  
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
  
  const folderPathSpan = document.getElementById('folder-path');
  const btnChangeFolder = document.getElementById('btn-change-folder');
  
  const activeSection = document.getElementById('active-downloads-section');
  const activeList = document.getElementById('active-downloads-list');
  
  const historyEmpty = document.getElementById('history-empty');
  const historyList = document.getElementById('history-list');
  const historyCount = document.getElementById('history-count');
  
  const chips = document.querySelectorAll('.chip');
  
  let currentAnalysis = null;
  let currentFolder = "~/Downloads";
  let activeDownloads = {};
  let lastProcessedUrl = "";
  let historyData = [];

  function checkAndAutoAnalyzePendingUrl() {
    if (window.pywebview && window.pywebview.api) {
      const api = window.pywebview.api;
      const getter = api.get_pending_url ? api.get_pending_url() : api.read_clipboard();
      Promise.resolve(getter).then(url => {
        if (url && (url.startsWith('http://') || url.startsWith('https://')) && url !== lastProcessedUrl) {
          lastProcessedUrl = url;
          urlInput.value = url;
          triggerAnalysis();
        }
      }).catch(() => {});
    }
  }

  // Wait for PyWebView API
  window.addEventListener('pywebviewready', () => {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.get_default_folder().then(folder => {
        if (folder) {
          currentFolder = folder;
          folderPathSpan.textContent = folder;
        }
      });
      checkAndAutoAnalyzePendingUrl();
    }
  });

  // Auto-paste and analyze on window focus and fast polling
  window.addEventListener('focus', checkAndAutoAnalyzePendingUrl);
  setInterval(checkAndAutoAnalyzePendingUrl, 800);

  // Chip selection
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      chips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      const radio = chip.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // Change Folder
  btnChangeFolder.addEventListener('click', () => {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.select_folder().then(folder => {
        if (folder) {
          currentFolder = folder;
          folderPathSpan.textContent = folder;
        }
      });
    }
  });

  // Paste button
  btnPaste.addEventListener('click', async () => {
    if (window.pywebview && window.pywebview.api) {
      const text = await window.pywebview.api.read_clipboard();
      if (text) {
        urlInput.value = text;
        triggerAnalysis();
      } else {
        showAlert("Nessun URL valido trovato negli appunti.");
      }
    } else {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          urlInput.value = text;
          triggerAnalysis();
        }
      } catch (err) {
        showAlert("Incolla manualmente l'URL nel campo di testo.");
      }
    }
  });

  // Analyze button
  btnAnalyze.addEventListener('click', () => {
    triggerAnalysis();
  });

  urlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      triggerAnalysis();
    }
  });

  function triggerAnalysis() {
    const url = urlInput.value.trim();
    if (!url) {
      showAlert("Per favore inserisci un URL valido.");
      return;
    }

    hideAlert();
    setAnalyzingState(true);
    previewSection.classList.add('hidden');

    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.analyze_url(url).then(result => {
        setAnalyzingState(false);
        if (result.error) {
          showAlert(result.error);
        } else {
          currentAnalysis = result;
          renderPreview(result);
        }
      }).catch(err => {
        setAnalyzingState(false);
        showAlert("Errore durante l'analisi: " + err);
      });
    } else {
      // Fallback preview test
      setTimeout(() => {
        setAnalyzingState(false);
        const dummyResult = {
          type: 'stream',
          title: 'Demo Video Content',
          url: url,
          thumbnail: 'https://picsum.photos/400/250',
          duration: '04:20',
          source: 'YouTube',
          file_size: '24.5 MB'
        };
        currentAnalysis = dummyResult;
        renderPreview(dummyResult);
      }, 1000);
    }
  }

  function renderPreview(data) {
    previewTitle.textContent = data.title || "File Multimediale";
    previewUrl.textContent = data.url;
    previewSource.textContent = data.source || "WEB";
    previewDuration.textContent = data.duration || "File Diretto";
    previewSize.textContent = data.file_size || "Dimensione N/D";

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

  const btnCopyLink = document.getElementById('btn-copy-link');
  const copyLinkText = document.getElementById('copy-link-text');

  if (btnCopyLink) {
    btnCopyLink.addEventListener('click', () => {
      if (!currentAnalysis || !currentAnalysis.url) return;
      copyTextToClipboard(currentAnalysis.url, copyLinkText);
    });
  }

  if (previewUrl) {
    previewUrl.title = "Clicca per copiare il link negli appunti";
    previewUrl.addEventListener('click', () => {
      if (!currentAnalysis || !currentAnalysis.url) return;
      copyTextToClipboard(currentAnalysis.url, copyLinkText);
    });
  }

  function copyTextToClipboard(text, labelElement) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.copy_to_clipboard) {
      window.pywebview.api.copy_to_clipboard(text);
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(() => {});
    }

    if (labelElement) {
      const origText = labelElement.textContent;
      labelElement.textContent = "✓ Link Copiato!";
      setTimeout(() => {
        labelElement.textContent = origText;
      }, 2000);
    }
  }

  // Start Download
  btnDownloadNow.addEventListener('click', () => {
    if (!currentAnalysis) return;

    const qualitySelect = document.getElementById('quality-select');
    const formatChoice = qualitySelect ? qualitySelect.value : '1080';

    const url = currentAnalysis.url;
    const mediaType = currentAnalysis.type;
    const customTitle = currentAnalysis.title;
    const customHeaders = currentAnalysis.headers;

    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.start_download(url, mediaType, formatChoice, currentFolder, customTitle, customHeaders)
        .then(res => {
          if (res.download_id) {
            addActiveDownloadItem(res.download_id, currentAnalysis.title, url);
            previewSection.classList.add('hidden');
            urlInput.value = '';
          }
        }).catch(err => {
          showAlert("Errore nell'avvio del download: " + err);
        });
    } else {
      // Demo fallback
      const demoId = "dl_" + Date.now();
      addActiveDownloadItem(demoId, currentAnalysis.title, url);
      previewSection.classList.add('hidden');
      urlInput.value = '';
      
      let p = 0;
      const interval = setInterval(() => {
        p += 10;
        window.onProgressUpdate({
          download_id: demoId,
          percent: p,
          speed: "3.5 MB/s",
          downloaded: `${(p * 0.2).toFixed(1)} MB`,
          total: "20 MB"
        });
        if (p >= 100) {
          clearInterval(interval);
          window.onDownloadFinished({
            download_id: demoId,
            filepath: "/Users/demo/Downloads/file.mp4",
            filename: currentAnalysis.title + ".mp4"
          });
        }
      }, 500);
    }
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
    activeDownloads[downloadId] = { title, element: itemCard, streamUrl: streamUrl, isPaused: false };

    const btnPause = itemCard.querySelector(`#btn_pause_${downloadId}`);
    const btnCancel = itemCard.querySelector(`#btn_cancel_${downloadId}`);

    btnPause.addEventListener('click', () => {
      const isPaused = activeDownloads[downloadId] ? activeDownloads[downloadId].isPaused : false;
      if (window.pywebview && window.pywebview.api) {
        if (isPaused) {
          window.pywebview.api.resume_download(downloadId);
        } else {
          window.pywebview.api.pause_download(downloadId);
        }
      }
    });

    btnCancel.addEventListener('click', () => {
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.cancel_download(downloadId);
      }
    });
  }

  // State Changed Hook (Pause / Resume / Cancel)
  window.onDownloadStateChanged = function(data) {
    const downloadId = data.download_id;
    const state = data.state;
    const item = activeDownloads[downloadId];
    const bar = document.getElementById(`bar_${downloadId}`);
    const badge = document.getElementById(`badge_status_${downloadId}`);
    const lblPause = document.getElementById(`lbl_pause_${downloadId}`);
    const iconPause = document.getElementById(`icon_pause_${downloadId}`);
    const speedSpan = document.getElementById(`speed_${downloadId}`);

    if (state === 'paused') {
      if (item) item.isPaused = true;
      if (bar) bar.classList.add('paused');
      if (badge) badge.classList.remove('hidden');
      if (lblPause) lblPause.textContent = "Riprendi";
      if (iconPause) {
        iconPause.innerHTML = '<polygon points="5 3 19 12 5 21 5 3" fill="currentColor"></polygon>';
      }
      if (speedSpan) speedSpan.textContent = "In pausa";
    } else if (state === 'running') {
      if (item) item.isPaused = false;
      if (bar) bar.classList.remove('paused');
      if (badge) badge.classList.add('hidden');
      if (lblPause) lblPause.textContent = "Pausa";
      if (iconPause) {
        iconPause.innerHTML = '<rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect>';
      }
    } else if (state === 'cancelled') {
      delete activeDownloads[downloadId];
      const card = document.getElementById(`card_${downloadId}`);
      if (card) card.remove();
      if (Object.keys(activeDownloads).length === 0) {
        activeSection.classList.add('hidden');
      }
    }
  };

  // Progress Update Hook
  window.onProgressUpdate = function(data) {
    const downloadId = data.download_id;
    const bar = document.getElementById(`bar_${downloadId}`);
    const percentSpan = document.getElementById(`percent_${downloadId}`);
    const speedSpan = document.getElementById(`speed_${downloadId}`);
    const bytesSpan = document.getElementById(`bytes_${downloadId}`);

    if (bar) bar.style.width = `${data.percent}%`;
    if (percentSpan) percentSpan.textContent = `${data.percent}%`;
    if (speedSpan && (!activeDownloads[downloadId] || !activeDownloads[downloadId].isPaused)) {
      speedSpan.textContent = data.speed;
    }
    if (bytesSpan) bytesSpan.textContent = `${data.downloaded} / ${data.total}`;
  };

  // Download Complete Hook
  window.onDownloadFinished = function(data) {
    const downloadId = data.download_id;
    const streamUrl = activeDownloads[downloadId] ? activeDownloads[downloadId].streamUrl : "";
    delete activeDownloads[downloadId];
    const card = document.getElementById(`card_${downloadId}`);
    if (card) {
      card.remove();
    }

    if (Object.keys(activeDownloads).length === 0) {
      activeSection.classList.add('hidden');
    }

    addToHistory(data.filename, data.filepath, streamUrl);
  };

  // Download Error Hook
  window.onDownloadError = function(data) {
    const downloadId = data.download_id;
    delete activeDownloads[downloadId];
    const card = document.getElementById(`card_${downloadId}`);
    if (card) {
      card.remove();
    }
    if (Object.keys(activeDownloads).length === 0) {
      activeSection.classList.add('hidden');
    }
    showAlert(`Download fallito: ${data.error}`);
  };

  function addToHistory(filename, filepath, streamUrl) {
    historyData.unshift({ filename, filepath, streamUrl, date: new Date().toLocaleTimeString() });

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
        <button class="btn-icon btn-finder" data-path="${escapeAttr(filepath)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          </svg>
          Mostra nel Finder
        </button>
        <button class="btn-icon btn-open" data-path="${escapeAttr(filepath)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          Apri File
        </button>
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

    item.querySelector('.btn-finder').addEventListener('click', (e) => {
      const path = e.currentTarget.getAttribute('data-path');
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.open_in_finder(path);
      }
    });

    item.querySelector('.btn-open').addEventListener('click', (e) => {
      const path = e.currentTarget.getAttribute('data-path');
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.open_file(path);
      }
    });

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

  function showAlert(msg) {
    alertBanner.textContent = msg;
    alertBanner.classList.remove('hidden');
  }

  function hideAlert() {
    alertBanner.classList.add('hidden');
  }

  function escapeHtml(str) {
    return str ? str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") : "";
  }

  function escapeAttr(str) {
    return str ? str.replace(/"/g, "&quot;") : "";
  }
});
