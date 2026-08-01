// MediaDownloader Pro - Popup Controller

let LOCAL_SERVER_URL = "http://localhost:5050";

let currentActiveTab = null;
let currentMediaData = null;
let activeDownloadId = null;
let progressPollInterval = null;
let isServerOnline = false;
let activeBrowserHLSInstance = null;

document.addEventListener("DOMContentLoaded", async () => {
  const select = document.getElementById("serverModeSelect");
  const stored = await chrome.storage.local.get(["selectedServerUrl"]);
  
  if (stored && stored.selectedServerUrl) {
    LOCAL_SERVER_URL = stored.selectedServerUrl;
  } else {
    // Auto-check if local Mac server is running on port 5050
    try {
      const pingLocal = await fetch("http://localhost:5050/api/ping", { signal: AbortSignal.timeout(1500) });
      if (pingLocal.ok) {
        LOCAL_SERVER_URL = "http://localhost:5050";
      } else {
        LOCAL_SERVER_URL = "https://mediadownloaderpro-3q69.onrender.com";
      }
    } catch (e) {
      LOCAL_SERVER_URL = "https://mediadownloaderpro-3q69.onrender.com";
    }
  }
  
  if (select) select.value = LOCAL_SERVER_URL;

  setupEventListeners();
  await checkServerStatus();
  await restoreActiveDownloadOrScanTab();
});

function setupEventListeners() {
  const select = document.getElementById("serverModeSelect");
  if (select) {
    select.addEventListener("change", async (e) => {
      LOCAL_SERVER_URL = e.target.value;
      await chrome.storage.local.set({ selectedServerUrl: LOCAL_SERVER_URL });
      await checkServerStatus();
      await restoreActiveDownloadOrScanTab();
    });
  }

  const btnCopy = document.getElementById("btnCopyUrl");
  if (btnCopy) {
    btnCopy.addEventListener("click", () => {
      const input = document.getElementById("targetUrlInput");
      input.select();
      navigator.clipboard.writeText(input.value);
      btnCopy.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
      setTimeout(() => {
        btnCopy.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
      }, 1500);
    });
  }

  document.getElementById("btnStartFastDownload").addEventListener("click", startFastDownload);
  document.getElementById("btnDirectBrowserDownload").addEventListener("click", startBrowserDownload);
  document.getElementById("btnRetryScan").addEventListener("click", initializeTabAnalysis);

  // Download Control Buttons
  document.getElementById("btnPauseDl").addEventListener("click", pauseDownload);
  document.getElementById("btnResumeDl").addEventListener("click", resumeDownload);
  document.getElementById("btnCancelDl").addEventListener("click", cancelDownload);
}

// Extract cookies from active tab and target domain for passing Cloudflare clearance session to server
async function getTabCookiesHeader(targetUrl) {
  const cookieMap = new Map();
  const currentUrl = currentActiveTab ? currentActiveTab.url : null;

  try {
    if (targetUrl && (targetUrl.startsWith("http://") || targetUrl.startsWith("https://"))) {
      const targetCookies = await chrome.cookies.getAll({ url: targetUrl });
      if (targetCookies) {
        targetCookies.forEach(c => cookieMap.set(c.name, c.value));
      }
    }
  } catch (e) {}

  try {
    if (currentUrl && currentUrl !== targetUrl && (currentUrl.startsWith("http://") || currentUrl.startsWith("https://"))) {
      const tabCookies = await chrome.cookies.getAll({ url: currentUrl });
      if (tabCookies) {
        tabCookies.forEach(c => cookieMap.set(c.name, c.value));
      }
    }
  } catch (e) {}

  if (cookieMap.size > 0) {
    return Array.from(cookieMap.entries()).map(([k, v]) => `${k}=${v}`).join("; ");
  }
  return "";
}

// 1. Check server status
async function checkServerStatus() {
  const badge = document.getElementById("serverStatusBadge");
  const badgeText = document.getElementById("serverStatusText");
  const footerLink = document.getElementById("footerWebDashboardLink");

  if (footerLink) {
    footerLink.href = LOCAL_SERVER_URL;
    footerLink.textContent = `Apri Dashboard Web (${LOCAL_SERVER_URL.replace("https://", "").replace("http://", "")})`;
  }

  try {
    const res = await fetch(`${LOCAL_SERVER_URL}/api/ping`, { 
      method: "GET",
      signal: AbortSignal.timeout(3000)
    });
    if (res.ok) {
      isServerOnline = true;
      if (badge) badge.className = "status-badge online";
      if (badgeText) badgeText.textContent = LOCAL_SERVER_URL.includes("localhost") ? "Server Mac Attivo" : "Server Cloud Attivo";
      return;
    }
  } catch (err) {}

  isServerOnline = false;
  if (badge) badge.className = "status-badge offline";
  if (badgeText) badgeText.textContent = "Server Offline (Browser Direct Mode)";
}

// 2. Auto-restore active download state across popup reopen
async function restoreActiveDownloadOrScanTab() {
  showView("loadingView");

  if (isServerOnline) {
    try {
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

    // A. Check background network sniffer media items
    let sniffedItems = [];
    try {
      const sniffRes = await new Promise((resolve) => {
        chrome.runtime.sendMessage({ action: "GET_SNIFFED_MEDIA", tabId: currentActiveTab.id }, (res) => {
          if (chrome.runtime.lastError) resolve(null);
          else resolve(res);
        });
      });
      if (sniffRes && sniffRes.media) {
        sniffedItems = sniffRes.media;
      }
    } catch (e) {}

    const bestSniffed = sniffedItems.find(m => m.type === 'hls' || m.url.includes('.m3u8')) || sniffedItems[0];

    // B. Analyze via Python server engine (try sniffed URL first if present, then page URL)
    if (isServerOnline) {
      const urlsToTry = [];
      if (bestSniffed && bestSniffed.url) urlsToTry.push(bestSniffed.url);
      urlsToTry.push(pageUrl);

      for (const targetUrl of urlsToTry) {
        try {
          const res = await fetch(`${LOCAL_SERVER_URL}/api/analyze`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: targetUrl })
          });
          const data = await res.json();
          if (data && !data.error) {
            renderMediaCard(data, pageUrl);
            return;
          }
        } catch (e) {
          console.warn("Backend analysis failed for", targetUrl, e);
        }
      }
    }

    // C. Fallback: If sniffer captured a valid media item
    if (bestSniffed) {
      renderMediaCard({
        type: bestSniffed.type || "stream",
        title: currentActiveTab.title || "Video Stream Rilevato",
        url: bestSniffed.url,
        file_size: "Flusso Rilevato",
        source: new URL(pageUrl).hostname,
        duration: "N/D"
      }, pageUrl);
      return;
    }

    // D. Fallback: Query DOM content script scanner
    chrome.tabs.sendMessage(currentActiveTab.id, { action: "SCAN_PAGE_MEDIA" }, (response) => {
      if (chrome.runtime.lastError || !response || !response.media || response.media.length === 0) {
        showView("noMediaView");
        return;
      }
      const item = response.media[0];
      renderMediaCard({
        type: item.type,
        title: item.title || response.pageTitle || "Video Rilevato",
        url: item.url,
        file_size: "File Rilevato",
        source: new URL(pageUrl).hostname,
        duration: "N/D"
      }, pageUrl);
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

// 5. Start download via Python engine or Browser fallback
async function startFastDownload() {
  if (!isServerOnline) {
    // If server is offline, seamlessly use in-browser download mode
    await startBrowserDownload();
    return;
  }

  if (!currentMediaData) return;

  const formatChoice = document.getElementById("formatSelect").value;
  const targetUrl = document.getElementById("targetUrlInput").value || currentMediaData.url;

  // Extract cookies from Chrome browser tab for Cloudflare clearance session
  const cookieStr = await getTabCookiesHeader(targetUrl || (currentActiveTab ? currentActiveTab.url : null));
  const customHeaders = currentMediaData.headers || {};
  if (cookieStr) {
    customHeaders['Cookie'] = cookieStr;
  }
  if (currentActiveTab && currentActiveTab.url) {
    if (!customHeaders['Referer']) customHeaders['Referer'] = currentActiveTab.url;
  }

  try {
    const res = await fetch(`${LOCAL_SERVER_URL}/api/download/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: targetUrl,
        media_type: currentMediaData.type || "stream",
        format_choice: formatChoice,
        custom_title: currentMediaData.title,
        custom_headers: customHeaders
      })
    });

    const data = await res.json();
    if (data.download_id) {
      activeDownloadId = data.download_id;
      chrome.storage.local.set({ activeDownloadId: activeDownloadId });
      showView("progressView");
      startPollingProgress();
    } else {
      alert("Errore nell'avvio del download: " + (data.error || "Risposta server non valida"));
    }
  } catch (err) {
    alert("Impossibile contattare il server di download. Avvio del download nel browser...");
    await startBrowserDownload();
  }
}

// 6. Poll server download status
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
          progressTitle.textContent = "⚡ Download in corso (Server)...";
          btnPause.classList.remove("hidden");
          btnResume.classList.add("hidden");
        }

        if (statusData.state === "completed") {
          clearInterval(progressPollInterval);
          chrome.storage.local.remove(["activeDownloadId"]);
          activeDownloadId = null;

          // Trigger browser download of the completed file
          if (statusData.download_url) {
            const fileUrl = statusData.download_url.startsWith("http")
              ? statusData.download_url
              : `${LOCAL_SERVER_URL}${statusData.download_url}`;

            chrome.downloads.download({
              url: fileUrl,
              filename: statusData.filename || "media_download.mp4",
              saveAs: false
            }, () => {
              if (chrome.runtime.lastError) {
                console.warn("Browser download trigger warning:", chrome.runtime.lastError);
              }
            });
          }

          alert("🎉 Download completato con successo! Il file è stato inviato ai download del tuo browser.");
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

// 7. Pause download (Server or In-Browser)
async function pauseDownload() {
  if (activeBrowserHLSInstance) {
    activeBrowserHLSInstance.pause();
    document.querySelector(".progress-title").textContent = "⏸ Download in Pausa (Browser)";
    document.getElementById("btnPauseDl").classList.add("hidden");
    document.getElementById("btnResumeDl").classList.remove("hidden");
    return;
  }
  if (!activeDownloadId) return;
  try {
    await fetch(`${LOCAL_SERVER_URL}/api/download/pause/${activeDownloadId}`, { method: "POST" });
  } catch (e) {
    console.error("Pause error", e);
  }
}

// 8. Resume download (Server or In-Browser)
async function resumeDownload() {
  if (activeBrowserHLSInstance) {
    activeBrowserHLSInstance.resume();
    document.querySelector(".progress-title").textContent = "⚡ Download in corso nel Browser (No Server)...";
    document.getElementById("btnPauseDl").classList.remove("hidden");
    document.getElementById("btnResumeDl").classList.add("hidden");
    return;
  }
  if (!activeDownloadId) return;
  try {
    await fetch(`${LOCAL_SERVER_URL}/api/download/resume/${activeDownloadId}`, { method: "POST" });
  } catch (e) {
    console.error("Resume error", e);
  }
}

// 9. Cancel active download (Server or In-Browser)
async function cancelDownload() {
  if (activeBrowserHLSInstance) {
    activeBrowserHLSInstance.cancel();
    activeBrowserHLSInstance = null;
    initializeTabAnalysis();
    return;
  }
  if (!activeDownloadId) return;
  try {
    await fetch(`${LOCAL_SERVER_URL}/api/download/cancel/${activeDownloadId}`, { method: "POST" });
  } catch (e) {}
  if (progressPollInterval) clearInterval(progressPollInterval);
  chrome.storage.local.remove(["activeDownloadId"]);
  activeDownloadId = null;
  initializeTabAnalysis();
}

// 10. Native In-Browser HLS & Direct File Downloader (No Server Required!)
async function startBrowserDownload() {
  const targetUrl = document.getElementById("targetUrlInput").value || (currentMediaData ? currentMediaData.url : null);
  if (!targetUrl) return;

  const safeTitle = (currentMediaData && currentMediaData.title)
    ? currentMediaData.title.replace(/[^a-zA-Z0-9_\-\s]/g, "_").trim()
    : "video_download";

  const isHLS = targetUrl.includes('.m3u8') || (currentMediaData && currentMediaData.type === 'hls');

  if (isHLS) {
    // A. Native In-Browser HLS Downloader Engine (Complete Cloudflare Bypass!)
    showView("progressView");

    const progressTitle = document.querySelector(".progress-title");
    const btnPause = document.getElementById("btnPauseDl");
    const btnResume = document.getElementById("btnResumeDl");

    progressTitle.textContent = "⚡ Download in corso nel Browser (No Server)...";
    btnPause.classList.remove("hidden");
    btnResume.classList.add("hidden");

    activeBrowserHLSInstance = new window.InBrowserHLSDownloader();

    const headers = {};
    if (currentActiveTab && currentActiveTab.url) {
      headers['Referer'] = currentActiveTab.url;
    }

    try {
      const blob = await activeBrowserHLSInstance.downloadHLS(targetUrl, headers, (stats) => {
        document.getElementById("progressBarFill").style.width = `${stats.percent}%`;
        document.getElementById("progressPercent").textContent = `${stats.percent.toFixed(1)}%`;

        const downloadedMB = (stats.totalBytes / (1024 * 1024)).toFixed(1);
        document.getElementById("progressDownloaded").textContent = `${stats.completedCount}/${stats.total} seg (${downloadedMB} MB)`;

        const speedMBps = (stats.speedBps / (1024 * 1024)).toFixed(1);
        document.getElementById("progressSpeed").textContent = `${speedMBps} MB/s`;

        if (activeBrowserHLSInstance.isPaused) {
          progressTitle.textContent = "⏸ Download in Pausa (Browser)";
          btnPause.classList.add("hidden");
          btnResume.classList.remove("hidden");
        } else {
          progressTitle.textContent = "⚡ Download in corso nel Browser (No Server)...";
          btnPause.classList.remove("hidden");
          btnResume.classList.add("hidden");
        }
      });

      // Save generated Blob file directly to Chrome Downloads
      const blobUrl = URL.createObjectURL(blob);
      chrome.downloads.download({
        url: blobUrl,
        filename: `${safeTitle}.ts`,
        saveAs: false
      }, (downloadId) => {
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
      });

      alert("🎉 Download completato con successo direttamente dal tuo browser!");
      activeBrowserHLSInstance = null;
      initializeTabAnalysis();

    } catch (err) {
      if (err.message === "DOWNLOAD_CANCELLED") {
        activeBrowserHLSInstance = null;
        initializeTabAnalysis();
      } else {
        alert("❌ Errore durante il download nel browser: " + err.message);
        activeBrowserHLSInstance = null;
        initializeTabAnalysis();
      }
    }

    return;
  }

  // B. Direct File Browser Download
  const safeFilename = `${safeTitle}.mp4`;
  chrome.runtime.sendMessage({
    action: "START_BROWSER_DOWNLOAD",
    url: targetUrl,
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
