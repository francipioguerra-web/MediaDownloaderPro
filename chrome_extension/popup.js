// MediaDownloader Pro - Popup Controller

const LOCAL_SERVER_URL = "http://localhost:5050";

let currentActiveTab = null;
let currentMediaData = null;
let activeDownloadId = null;
let progressPollInterval = null;
let isServerOnline = false;

document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await checkServerStatus();
  await restoreActiveDownloadOrScanTab();
});

function setupEventListeners() {
  document.getElementById("btnCopyUrl").addEventListener("click", () => {
    const input = document.getElementById("targetUrlInput");
    input.select();
    navigator.clipboard.writeText(input.value);
    const btn = document.getElementById("btnCopyUrl");
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    setTimeout(() => {
      btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
    }, 1500);
  });

  document.getElementById("btnStartFastDownload").addEventListener("click", startFastDownload);
  document.getElementById("btnDirectBrowserDownload").addEventListener("click", startBrowserDownload);
  document.getElementById("btnRetryScan").addEventListener("click", initializeTabAnalysis);
  
  // Download Control Buttons
  document.getElementById("btnPauseDl").addEventListener("click", pauseDownload);
  document.getElementById("btnResumeDl").addEventListener("click", resumeDownload);
  document.getElementById("btnCancelDl").addEventListener("click", cancelDownload);
}

// 1. Check local server status
async function checkServerStatus() {
  const badge = document.getElementById("serverStatusBadge");
  const badgeText = document.getElementById("serverStatusText");

  try {
    const res = await fetch(`${LOCAL_SERVER_URL}/api/ping`, { method: "GET" });
    if (res.ok) {
      isServerOnline = true;
      badge.className = "status-badge online";
      badgeText.textContent = "Server Attivo";
      return;
    }
  } catch (err) {}

  try {
    const res2 = await fetch(`${LOCAL_SERVER_URL}/`, { method: "GET" });
    if (res2.ok) {
      isServerOnline = true;
      badge.className = "status-badge online";
      badgeText.textContent = "Server Attivo";
      return;
    }
  } catch (e) {}

  isServerOnline = false;
  badge.className = "status-badge offline";
  badgeText.textContent = "Server Offline";
}

// 2. Auto-restore active download state across popup reopen
async function restoreActiveDownloadOrScanTab() {
  showView("loadingView");

  if (isServerOnline) {
    try {
      // Check server for any running or paused downloads
      const res = await fetch(`${LOCAL_SERVER_URL}/api/download/active`);
      if (res.ok) {
        const data = await res.json();
        if (data.downloads && data.downloads.length > 0) {
          const activeItem = data.downloads[0];
          activeDownloadId = activeItem.download_id;
          chrome.storage.local.set({ activeDownloadId: activeDownloadId });
          showView("progressView");
          startPollingProgress();
          return;
        }
      }
    } catch (e) {}
  }

  // Check local storage fallback
  chrome.storage.local.get(["activeDownloadId"], async (stored) => {
    if (stored && stored.activeDownloadId && isServerOnline) {
      try {
        const res = await fetch(`${LOCAL_SERVER_URL}/api/download/status/${stored.activeDownloadId}`);
        const statusData = await res.json();
        if (statusData && (statusData.state === "running" || statusData.state === "paused" || statusData.state === "starting")) {
          activeDownloadId = stored.activeDownloadId;
          showView("progressView");
          startPollingProgress();
          return;
        } else {
          chrome.storage.local.remove(["activeDownloadId"]);
        }
      } catch (e) {}
    }
    await initializeTabAnalysis();
  });
}

// 3. Initialize analysis of current active tab
async function initializeTabAnalysis() {
  showView("loadingView");

  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs || !tabs.length) {
      showView("noMediaView");
      return;
    }

    currentActiveTab = tabs[0];
    const pageUrl = currentActiveTab.url;

    if (!pageUrl || (!pageUrl.startsWith("http://") && !pageUrl.startsWith("https://"))) {
      showView("noMediaView");
      return;
    }

    // Attempt 1: Analyze via local Python server engine
    if (isServerOnline) {
      try {
        const res = await fetch(`${LOCAL_SERVER_URL}/api/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: pageUrl })
        });
        const data = await res.json();
        if (data && !data.error) {
          renderMediaCard(data, pageUrl);
          return;
        }
      } catch (e) {
        console.warn("Backend analysis failed, fallback to client scan", e);
      }
    }

    // Attempt 2: Client DOM & Sniffed network scanner
    chrome.tabs.sendMessage(currentActiveTab.id, { action: "SCAN_PAGE_MEDIA" }, (response) => {
      if (response && response.media && response.media.length > 0) {
        const item = response.media[0];
        renderMediaCard({
          type: item.type,
          title: item.title || response.pageTitle || "Video Rilevato",
          url: item.url,
          file_size: "File Rilevato",
          source: new URL(pageUrl).hostname,
          duration: "N/D"
        }, pageUrl);
      } else {
        // Check background network sniffer
        chrome.runtime.sendMessage({ action: "GET_SNIFFED_MEDIA", tabId: currentActiveTab.id }, (sniffRes) => {
          if (sniffRes && sniffRes.media && sniffRes.media.length > 0) {
            const item = sniffRes.media[0];
            renderMediaCard({
              type: item.type,
              title: currentActiveTab.title || "Video Stream",
              url: item.url,
              file_size: "Flusso Rilevato",
              source: new URL(pageUrl).hostname,
              duration: "N/D"
            }, pageUrl);
          } else {
            showView("noMediaView");
          }
        });
      }
    });

  } catch (err) {
    console.error("Tab analysis error:", err);
    showView("noMediaView");
  }
}

// 4. Render Media Details UI Card
function renderMediaCard(mediaInfo, pageUrl) {
  currentMediaData = mediaInfo;

  document.getElementById("mediaTitle").textContent = mediaInfo.title || "Contenuto Multimediale";
  document.getElementById("targetUrlInput").value = mediaInfo.url || pageUrl;
  document.getElementById("mediaSize").textContent = `Dimensione: ${mediaInfo.file_size || "N/D"}`;
  document.getElementById("mediaDuration").textContent = `Durata: ${mediaInfo.duration || "N/D"}`;
  document.getElementById("mediaSourceBadge").textContent = mediaInfo.source || new URL(pageUrl).hostname;

  const badge = document.getElementById("mediaTypeBadge");
  if (mediaInfo.type === "hls") {
    badge.textContent = "HLS STREAM (.m3u8)";
    badge.className = "badge badge-hls";
  } else {
    badge.textContent = "DIRECT FILE";
    badge.className = "badge badge-direct";
  }

  showView("resultView");
}

// 5. Start download via local Python engine (app_fast.py / web_app.py)
async function startFastDownload() {
  if (!isServerOnline) {
    alert("Il Server MediaDownloader non è attivo su http://localhost:5050!\nAvvia 'web_app.py' per usare il download ad alta velocità.");
    return;
  }

  if (!currentMediaData) return;

  const formatChoice = document.getElementById("formatSelect").value;
  const targetUrl = currentMediaData.url;

  try {
    const res = await fetch(`${LOCAL_SERVER_URL}/api/download/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: targetUrl,
        media_type: currentMediaData.type || "stream",
        format_choice: formatChoice,
        custom_title: currentMediaData.title,
        custom_headers: currentMediaData.headers || null
      })
    });

    const data = await res.json();
    if (data.download_id) {
      activeDownloadId = data.download_id;
      chrome.storage.local.set({ activeDownloadId: activeDownloadId });
      showView("progressView");
      startPollingProgress();
    } else {
      alert("Errore nell'avvio del download.");
    }
  } catch (err) {
    alert("Impossibile contattare il server di download: " + err.message);
  }
}

// 6. Poll download status with Pause / Resume / Cancel integration
function startPollingProgress() {
  if (progressPollInterval) clearInterval(progressPollInterval);

  const btnPause = document.getElementById("btnPauseDl");
  const btnResume = document.getElementById("btnResumeDl");
  const progressTitle = document.querySelector(".progress-title");

  progressPollInterval = setInterval(async () => {
    if (!activeDownloadId) return;

    try {
      const res = await fetch(`${LOCAL_SERVER_URL}/api/download/status/${activeDownloadId}`);
      const statusData = await res.json();

      if (statusData) {
        const percent = statusData.percent || 0;
        document.getElementById("progressBarFill").style.width = `${percent}%`;
        document.getElementById("progressPercent").textContent = `${percent.toFixed(1)}%`;
        document.getElementById("progressDownloaded").textContent = `${statusData.downloaded || "0 MB"} / ${statusData.total || "N/D"}`;
        document.getElementById("progressSpeed").textContent = statusData.speed || "0 MB/s";

        // Handle Paused vs Running state
        if (statusData.state === "paused") {
          progressTitle.textContent = "⏸ Download in Pausa";
          btnPause.classList.add("hidden");
          btnResume.classList.remove("hidden");
        } else if (statusData.state === "running" || statusData.state === "starting") {
          progressTitle.textContent = "⚡ Download in corso (Fast)...";
          btnPause.classList.remove("hidden");
          btnResume.classList.add("hidden");
        }

        if (statusData.state === "completed") {
          clearInterval(progressPollInterval);
          chrome.storage.local.remove(["activeDownloadId"]);
          alert("🎉 Download completato con successo!");
          activeDownloadId = null;
          initializeTabAnalysis();
        } else if (statusData.state === "error") {
          clearInterval(progressPollInterval);
          chrome.storage.local.remove(["activeDownloadId"]);
          alert("❌ Errore durante il download: " + (statusData.error || "Errore sconosciuto"));
          activeDownloadId = null;
          initializeTabAnalysis();
        } else if (statusData.state === "cancelled") {
          clearInterval(progressPollInterval);
          chrome.storage.local.remove(["activeDownloadId"]);
          activeDownloadId = null;
          initializeTabAnalysis();
        }
      }
    } catch (e) {
      console.warn("Polling status error", e);
    }
  }, 500);
}

// 7. Pause download
async function pauseDownload() {
  if (!activeDownloadId) return;
  try {
    await fetch(`${LOCAL_SERVER_URL}/api/download/pause/${activeDownloadId}`, { method: "POST" });
  } catch (e) {
    console.error("Pause error", e);
  }
}

// 8. Resume download
async function resumeDownload() {
  if (!activeDownloadId) return;
  try {
    await fetch(`${LOCAL_SERVER_URL}/api/download/resume/${activeDownloadId}`, { method: "POST" });
  } catch (e) {
    console.error("Resume error", e);
  }
}

// 9. Cancel active download
async function cancelDownload() {
  if (!activeDownloadId) return;
  try {
    await fetch(`${LOCAL_SERVER_URL}/api/download/cancel/${activeDownloadId}`, { method: "POST" });
  } catch (e) {}
  if (progressPollInterval) clearInterval(progressPollInterval);
  chrome.storage.local.remove(["activeDownloadId"]);
  activeDownloadId = null;
  initializeTabAnalysis();
}

// 10. Direct browser download fallback
async function startBrowserDownload() {
  if (!currentMediaData || !currentMediaData.url) return;

  let downloadUrl = currentMediaData.url;

  if (currentMediaData.type === 'hls' || downloadUrl.includes('.m3u8')) {
    alert("⚠️ I flussi HLS (.m3u8) sono divisi in centinaia di frammenti e non possono essere scaricati direttamente dal browser come un singolo file MP4.\n\nPer scaricare questo video completo in MP4, usa il pulsante 'Scarica con MediaDownloader (Fast)' con il server attivo su http://localhost:5050.");
    return;
  }

  const parsedPath = new URL(downloadUrl).pathname.toLowerCase();
  const directMediaExts = ['.mp4', '.mkv', '.webm', '.mov', '.avi', '.mp3', '.m4a', '.flac', '.wav'];
  const isDirectFile = directMediaExts.some(ext => parsedPath.endsWith(ext)) || downloadUrl.includes('pixeldrain.com/api/file/');

  if (!isDirectFile && isServerOnline) {
    try {
      const res = await fetch(`${LOCAL_SERVER_URL}/api/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: downloadUrl })
      });
      const data = await res.json();
      if (data && data.url && data.type === 'direct') {
        downloadUrl = data.url;
      } else if (data && data.type === 'hls') {
        alert("⚠️ Questo contenuto è un flusso video HLS (.m3u8). Il browser non può unirlo in un unico MP4.\n\nUsa il pulsante 'Scarica con MediaDownloader (Fast)'.");
        return;
      }
    } catch (e) {}
  }

  const safeFilename = (currentMediaData.title ? currentMediaData.title.replace(/[^a-zA-Z0-9_-]/g, "_") : "media_download") + ".mp4";

  chrome.runtime.sendMessage({
    action: "START_BROWSER_DOWNLOAD",
    url: downloadUrl,
    filename: safeFilename
  }, (res) => {
    if (res && res.success) {
      alert("Download avviato nel browser!");
    } else {
      alert("Impossibile avviare il download con il browser su questo URL.");
    }
  });
}

function showView(viewId) {
  const views = ["loadingView", "resultView", "noMediaView", "progressView"];
  views.forEach(v => {
    const el = document.getElementById(v);
    if (el) {
      if (v === viewId) el.classList.remove("hidden");
      else el.classList.add("hidden");
    }
  });
}
