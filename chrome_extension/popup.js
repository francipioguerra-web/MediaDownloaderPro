// MediaDownloader Pro - Popup Controller for Mac Desktop App Integration

let LOCAL_SERVER_URL = "http://localhost:5050";
let currentActiveTab = null;
let currentMediaData = null;
let isServerOnline = false;

document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await checkServerStatus();
  await initializeTabAnalysis();
});

function setupEventListeners() {
  const btnCopy = document.getElementById("btnCopyUrl");
  if (btnCopy) {
    btnCopy.addEventListener("click", () => {
      copyTargetUrlToClipboard();
    });
  }

  const btnOpenMac = document.getElementById("btnOpenMacApp");
  if (btnOpenMac) {
    btnOpenMac.addEventListener("click", openAndSendToMacApp);
  }

  const btnCopyDirect = document.getElementById("btnCopyLinkDirect");
  if (btnCopyDirect) {
    btnCopyDirect.addEventListener("click", () => {
      copyTargetUrlToClipboard();
      alert("📋 Link video copiato negli appunti!\n\nPuoi incollarlo direttamente nell'applicazione MediaDownloader sul tuo Mac.");
    });
  }

  const btnRetry = document.getElementById("btnRetryScan");
  if (btnRetry) {
    btnRetry.addEventListener("click", initializeTabAnalysis);
  }
}

function copyTargetUrlToClipboard() {
  const input = document.getElementById("targetUrlInput");
  if (input && input.value) {
    input.select();
    navigator.clipboard.writeText(input.value);
    const btn = document.getElementById("btnCopyUrl");
    if (btn) {
      btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
      setTimeout(() => {
        btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
      }, 1500);
    }
  }
}

// 1. Check local Mac server status
async function checkServerStatus() {
  const badge = document.getElementById("serverStatusBadge");
  const badgeText = document.getElementById("serverStatusText");

  try {
    const res = await fetch(`${LOCAL_SERVER_URL}/api/ping`, { 
      method: "GET",
      signal: AbortSignal.timeout(2000)
    });
    if (res.ok) {
      isServerOnline = true;
      if (badge) badge.className = "status-badge online";
      if (badgeText) badgeText.textContent = "App Mac Pronta";
      return;
    }
  } catch (err) {}

  isServerOnline = false;
  if (badge) badge.className = "status-badge offline";
  if (badgeText) badgeText.textContent = "App Mac (Pronta al collegamento)";
}

// 2. Initialize tab media analysis
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

    // Check background network sniffer media items
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

    // If sniffer detected media stream, present it
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

    // Query DOM content script scanner
    chrome.tabs.sendMessage(currentActiveTab.id, { action: "SCAN_PAGE_MEDIA" }, (response) => {
      if (chrome.runtime.lastError || !response || !response.media || response.media.length === 0) {
        // Fallback to page URL itself
        renderMediaCard({
          type: "stream",
          title: currentActiveTab.title || "Pagina Media",
          url: pageUrl,
          file_size: "Contenuto Web",
          source: new URL(pageUrl).hostname,
          duration: "N/D"
        }, pageUrl);
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

// 3. Render Media UI Card
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
    badge.textContent = "VIDEO RILEVATO";
    badge.className = "badge badge-direct";
  }

  showView("resultView");
}

// 4. Open and send video URL directly to Mac Desktop App
async function openAndSendToMacApp() {
  const targetUrl = document.getElementById("targetUrlInput").value || (currentMediaData ? currentMediaData.url : null);
  if (!targetUrl) return;

  // A. Copy URL to clipboard for instant pasting
  navigator.clipboard.writeText(targetUrl);

  // B. Try Chrome Native Messaging Host to launch /Applications/MediaDownloader.app
  try {
    chrome.runtime.sendNativeMessage("com.mediadownloader.mac", { url: targetUrl }, (response) => {
      if (chrome.runtime.lastError) {
        console.warn("Native Messaging:", chrome.runtime.lastError.message);
      }
    });
  } catch (e) {}

  // C. Send POST to local Mac app server if online
  if (isServerOnline) {
    try {
      await fetch(`${LOCAL_SERVER_URL}/api/download/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: targetUrl,
          custom_title: currentMediaData ? currentMediaData.title : null
        })
      });
    } catch (e) {}
  }

  // D. Open macOS app custom protocol handler (mediadownloader://)
  try {
    const customSchemeUrl = `mediadownloader://download?url=${encodeURIComponent(targetUrl)}`;
    window.location.href = customSchemeUrl;
    if (currentActiveTab && currentActiveTab.id) {
      chrome.tabs.update(currentActiveTab.id, { url: customSchemeUrl });
    }
  } catch (e) {}

  alert("🚀 Applicazione MediaDownloader in avvio sul tuo Mac!\n\nIl link del video è stato inviato all'app e copiato negli appunti.");
}

function showView(viewId) {
  const views = ["loadingView", "resultView", "noMediaView"];
  views.forEach(v => {
    const el = document.getElementById(v);
    if (el) {
      if (v === viewId) el.classList.remove("hidden");
      else el.classList.add("hidden");
    }
  });
}
