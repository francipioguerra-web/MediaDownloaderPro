document.addEventListener('DOMContentLoaded', () => {
  const urlInput = document.getElementById('url-input');
  const serverUrlInput = document.getElementById('server-url-input');
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
  const btnCopyLink = document.getElementById('btn-copy-link');
  
  const historyEmpty = document.getElementById('history-empty');
  const historyList = document.getElementById('history-list');
  const historyCount = document.getElementById('history-count');
  
  const chips = document.querySelectorAll('.chip');
  
  let currentAnalysis = null;
  let historyData = [];

  // Auto-fill local server IP if available
  if (serverUrlInput && !serverUrlInput.value) {
    serverUrlInput.placeholder = "IP Server (es. http://192.168.1.64:5050)";
  }

  // Chip selection
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      chips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      const radio = chip.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // Paste button
  btnPaste.addEventListener('click', async () => {
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = await navigator.clipboard.readText();
        if (text && text.startsWith('http')) {
          urlInput.value = text;
          triggerAnalysis();
          return;
        }
      }
    } catch (e) {}
    
    showToast("Incolla l'URL tenendo premuto nel campo di testo.");
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

  // Copy Stream Link
  if (btnCopyLink) {
    btnCopyLink.addEventListener('click', () => {
      if (currentAnalysis && currentAnalysis.url) {
        copyToClipboard(currentAnalysis.url);
      }
    });
  }
  if (previewUrl) {
    previewUrl.addEventListener('click', () => {
      if (currentAnalysis && currentAnalysis.url) {
        copyToClipboard(currentAnalysis.url);
      }
    });
  }

  // Download button
  btnDownloadNow.addEventListener('click', async () => {
    if (!currentAnalysis) return;

    const selectedFormat = document.querySelector('input[name="format"]:checked')?.value || 'best';
    let filename = currentAnalysis.title || 'media_file';
    filename = filename.replace(/[/\\?%*:|"<>]/g, '_').trim();
    if (!filename.endsWith('.mp4') && !filename.endsWith('.mp3') && !filename.endsWith('.mkv')) {
      filename += selectedFormat === 'mp3' ? '.mp3' : '.mp4';
    }

    // 1. If Server Mode is active
    if (currentAnalysis.isServerMode && currentAnalysis.serverBaseUrl) {
      try {
        const startRes = await fetch(`${currentAnalysis.serverBaseUrl}/api/download/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: currentAnalysis.originalUrl || currentAnalysis.url,
            media_type: currentAnalysis.type || 'stream',
            format_choice: selectedFormat,
            custom_title: currentAnalysis.title,
            custom_headers: currentAnalysis.headers
          })
        });
        if (startRes.ok) {
          const startData = await startRes.json();
          if (startData.download_id) {
            pollServerDownload(currentAnalysis.serverBaseUrl, startData.download_id, filename);
            return;
          }
        }
      } catch (e) {
        console.log("Server download start failed:", e);
      }
    }

    // 2. Direct Android DownloadManager trigger
    let downloadUrl = currentAnalysis.url;
    if (window.AndroidApp && window.AndroidApp.downloadFile) {
      window.AndroidApp.downloadFile(downloadUrl, filename);
      addToHistory(currentAnalysis.title, downloadUrl, filename);
      showToast("Download avviato su Android!");
    } else {
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = filename;
      a.target = '_blank';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      addToHistory(currentAnalysis.title, downloadUrl, filename);
    }
  });

  function pollServerDownload(baseUrl, downloadId, filename) {
    showToast("Download avviato sul server...");
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${baseUrl}/api/download/status/${downloadId}`);
        if (res.ok) {
          const statusData = await res.json();
          if (statusData.state === 'completed') {
            clearInterval(interval);
            const fileUrl = `${baseUrl}${statusData.download_url}`;
            if (window.AndroidApp && window.AndroidApp.downloadFile) {
              window.AndroidApp.downloadFile(fileUrl, filename);
            } else {
              window.location.href = fileUrl;
            }
            addToHistory(statusData.filename || filename, fileUrl, filename);
            showToast("File pronto! Download su Android avviato.");
          } else if (statusData.state === 'error' || statusData.state === 'cancelled') {
            clearInterval(interval);
            showAlert("Errore durante il download sul server: " + (statusData.error || statusData.state));
          }
        }
      } catch (e) {}
    }, 1500);
  }

  async function triggerAnalysis() {
    const rawUrl = urlInput.value.trim();
    if (!rawUrl) {
      showAlert("Inserisci o incolla un URL valido.");
      return;
    }

    if (!rawUrl.startsWith('http://') && !rawUrl.startsWith('https://')) {
      showAlert("L'URL deve iniziare con http:// o https://");
      return;
    }

    hideAlert();
    setLoading(true);
    previewSection.style.display = 'none';

    try {
      const analysis = await analyzeUrl(rawUrl);
      setLoading(false);

      if (analysis.error) {
        showAlert(analysis.error);
        return;
      }

      currentAnalysis = analysis;
      currentAnalysis.originalUrl = rawUrl;

      // Update Preview Card
      previewTitle.textContent = analysis.title || "File Multimediale";
      previewSource.textContent = analysis.source || "Web Stream";
      previewDuration.textContent = analysis.duration || "Multi-Qualità";
      previewSize.textContent = analysis.file_size || "HD Media";
      previewUrl.textContent = analysis.url;

      if (analysis.thumbnail) {
        previewImg.src = analysis.thumbnail;
        previewImg.style.display = 'block';
        previewFallbackIcon.style.display = 'none';
      } else {
        previewImg.style.display = 'none';
        previewFallbackIcon.style.display = 'flex';
      }

      previewSection.style.display = 'block';
      previewSection.scrollIntoView({ behavior: 'smooth' });

    } catch (err) {
      setLoading(false);
      showAlert("Impossibile analizzare l'URL: " + err.message);
    }
  }

  async function analyzeUrl(url) {
    const serverUrl = serverUrlInput ? serverUrlInput.value.trim() : '';

    // 0. Server Mode API check
    if (serverUrl) {
      const baseUrl = serverUrl.replace(/\/+$/, '');
      try {
        const res = await fetch(`${baseUrl}/api/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url })
        });
        if (res.ok) {
          const data = await res.json();
          if (data && !data.error) {
            data.isServerMode = true;
            data.serverBaseUrl = baseUrl;
            return data;
          }
        }
      } catch (e) {
        console.log("Server API call failed, falling back to local extractor:", e);
      }
    }

    const urlLower = url.toLowerCase();

    // 1. Pixeldrain (pixeldrain.com/u/<id> or /l/<id>)
    if (urlLower.includes('pixeldrain.com')) {
      const match = url.match(/pixeldrain\.com\/(?:u|l)\/([a-zA-Z0-9_-]+)/);
      if (match) {
        const fileId = match[1];
        const directUrl = `https://pixeldrain.com/api/file/${fileId}?download`;
        let title = `Pixeldrain File (${fileId})`;
        let size = "File Pixeldrain";

        try {
          const res = await fetch(`https://pixeldrain.com/api/file/${fileId}/info`);
          if (res.ok) {
            const meta = await res.json();
            if (meta.name) title = meta.name;
            if (meta.size) size = formatSize(meta.size);
          }
        } catch (e) {}

        return {
          title: title,
          url: directUrl,
          source: "Pixeldrain",
          duration: "File Diretto",
          file_size: size,
          thumbnail: null
        };
      }
    }

    // 2. StreamingCommunity / Vixcloud
    if (urlLower.includes('streamingcommunity') || urlLower.includes('vixcloud')) {
      const match = url.match(/\/(?:playlist|embed|iframe)\/(\d+)/);
      const embedId = match ? match[1] : '';
      let m3u8Url = url;
      if (!m3u8Url.includes('.m3u8')) {
        m3u8Url = m3u8Url.split('?')[0] + '.m3u8' + (url.includes('?') ? '?' + url.split('?')[1] : '');
      }

      return {
        title: embedId ? `Stream Vixcloud #${embedId}` : "Flusso Video Vixcloud",
        url: m3u8Url,
        source: "Vixcloud HLS",
        duration: "Stream HLS",
        file_size: "Flusso M3U8",
        thumbnail: null
      };
    }

    // 3. Direct File Link (.mp4, .mp3, .mkv, .mov, .webm, .m4a, .zip, etc.)
    const directExts = ['.mp4', '.mp3', '.mkv', '.mov', '.webm', '.m4a', '.avi', '.flv', '.zip', '.rar'];
    if (directExts.some(ext => urlLower.includes(ext))) {
      const filename = url.split('/').pop().split('?')[0] || "file_multimediale";
      return {
        title: decodeURIComponent(filename),
        url: url,
        source: "Link Diretto",
        duration: "File Media",
        file_size: "File Diretto",
        thumbnail: null
      };
    }

    // 4. Cobalt Multi-Site Extractor API (YouTube, TikTok, Instagram, Twitter, Vimeo, SoundCloud...)
    try {
      const res = await fetch('https://api.cobalt.tools/api/json', {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ url: url })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.url) {
          return {
            title: data.filename || "Video Estratto",
            url: data.url,
            source: "Media Extractor",
            duration: "Video HD",
            file_size: "HD Quality",
            thumbnail: null
          };
        }
      }
    } catch (e) {}

    // Fallback: Direct Stream Link
    const domain = new URL(url).hostname;
    return {
      title: `Media Stream (${domain})`,
      url: url,
      source: domain,
      duration: "Stream Media",
      file_size: "HD Stream",
      thumbnail: null
    };
  }

  function formatSize(bytes) {
    if (!bytes) return "0 B";
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  function setLoading(loading) {
    btnAnalyze.disabled = loading;
    if (loading) {
      analyzeSpinner.style.display = 'inline-block';
      analyzeText.textContent = 'Analisi in corso...';
    } else {
      analyzeSpinner.style.display = 'none';
      analyzeText.textContent = 'Analizza Link';
    }
  }

  function showAlert(msg) {
    alertBanner.textContent = msg;
    alertBanner.style.display = 'block';
  }

  function hideAlert() {
    alertBanner.style.display = 'none';
  }

  function showToast(msg) {
    if (window.AndroidApp && window.AndroidApp.showToast) {
      window.AndroidApp.showToast(msg);
    } else {
      alert(msg);
    }
  }

  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        showToast("Link streaming copiato negli appunti!");
      });
    } else {
      const input = document.createElement('input');
      input.value = text;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
      showToast("Link streaming copiato!");
    }
  }

  function addToHistory(title, streamUrl, filename) {
    historyData.unshift({
      title: title || filename,
      url: streamUrl,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    });

    if (historyData.length > 20) historyData.pop();
    renderHistory();
  }

  function renderHistory() {
    if (historyData.length === 0) {
      historyEmpty.style.display = 'block';
      historyList.style.display = 'none';
      historyCount.textContent = '(0)';
      return;
    }

    historyEmpty.style.display = 'none';
    historyList.style.display = 'flex';
    historyCount.textContent = `(${historyData.length})`;

    historyList.innerHTML = historyData.map((item, idx) => `
      <div class="history-card">
        <div class="history-info">
          <h4>${escapeHtml(item.title)}</h4>
          <p>${escapeHtml(item.url)}</p>
        </div>
        <div class="history-actions">
          <button class="btn-copy-hist" data-url="${escapeHtml(item.url)}">Copia Link</button>
        </div>
      </div>
    `).join('');

    document.querySelectorAll('.btn-copy-hist').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const link = e.target.getAttribute('data-url');
        if (link) copyToClipboard(link);
      });
    });
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
});
