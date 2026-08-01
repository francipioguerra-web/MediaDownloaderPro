// MediaDownloader Pro - Background Service Worker (Manifest V3)

const tabMediaMap = {};

// Helper to filter real media stream and file URLs
function isMediaUrl(url) {
  if (!url || typeof url !== 'string') return false;
  if (url.startsWith('chrome-extension:') || url.startsWith('data:') || url.startsWith('blob:')) return false;

  const urlLower = url.toLowerCase();
  const cleanUrl = urlLower.split('?')[0];

  // Exclude standard static web assets
  if (/\.(png|jpg|jpeg|gif|svg|webp|ico|css|js|woff|woff2|ttf|otf|eot|json|html|php|asp|jsx|tsx)(\?|$)/i.test(cleanUrl)) {
    return false;
  }

  // Exclude ad & analytics scripts
  if (urlLower.includes("google-analytics") || urlLower.includes("doubleclick") || urlLower.includes("facebook.com") || urlLower.includes("analytics")) {
    return false;
  }

  // Known media file extensions
  if (/\.(m3u8|mp4|mkv|webm|m4a|mp3|mov|avi|flac|wav)(\?|$)/i.test(cleanUrl)) {
    return true;
  }

  // Known streaming hosts / stream URLs
  if (urlLower.includes("vixcloud.co") || 
      urlLower.includes("pixeldrain.com/api/file/") || 
      urlLower.includes("bunkr") || 
      urlLower.includes("streamtape") || 
      urlLower.includes("doodstream") ||
      urlLower.includes("voe.sx") ||
      urlLower.includes("/playlist/") ||
      urlLower.includes("/hls/")) {
    return true;
  }

  return false;
}

// Listen for network requests matching media patterns
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (!details.url || details.tabId < 0) return;
    const url = details.url;

    if (!isMediaUrl(url)) return;

    if (!tabMediaMap[details.tabId]) {
      tabMediaMap[details.tabId] = [];
    }

    // Check if URL already recorded
    const exists = tabMediaMap[details.tabId].some(item => item.url === url);
    if (!exists) {
      let mediaType = "direct";
      if (url.includes(".m3u8") || url.includes("vixcloud.co") || url.includes("/hls/") || url.includes("/playlist/")) {
        mediaType = "hls";
      }

      tabMediaMap[details.tabId].push({
        url: url,
        type: mediaType,
        timestamp: Date.now()
      });

      // Update extension badge count
      const count = tabMediaMap[details.tabId].length;
      chrome.action.setBadgeText({ tabId: details.tabId, text: String(count) });
      chrome.action.setBadgeBackgroundColor({ tabId: details.tabId, color: "#6366F1" });
    }
  },
  { urls: ["<all_urls>"] }
);

// Clean up stored media when tab is closed
chrome.tabs.onRemoved.addListener((tabId) => {
  delete tabMediaMap[tabId];
});

// Setup declarativeNetRequest rules for bypassing Referer/Origin checks
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "GET_SNIFFED_MEDIA") {
    const tabId = request.tabId;
    const items = tabMediaMap[tabId] || [];
    sendResponse({ success: true, media: items });
  } else if (request.action === "SET_HEADER_RULES") {
    const referer = request.referer;
    const origin = request.origin || "https://vixcloud.co";
    
    if (chrome.declarativeNetRequest) {
      const rule = {
        id: 1,
        priority: 1,
        action: {
          type: 'modifyHeaders',
          requestHeaders: [
            { header: 'Referer', operation: 'set', value: referer },
            { header: 'Origin', operation: 'set', value: origin }
          ]
        },
        condition: {
          urlFilter: 'vixcloud.co',
          resourceTypes: ['xmlhttprequest', 'media', 'other']
        }
      };

      chrome.declarativeNetRequest.updateDynamicRules({
        removeRuleIds: [1],
        addRules: [rule]
      }, () => {
        sendResponse({ success: !chrome.runtime.lastError });
      });
      return true;
    } else {
      sendResponse({ success: false });
    }
  } else if (request.action === "START_BROWSER_DOWNLOAD") {
    chrome.downloads.download({
      url: request.url,
      filename: request.filename || "media_download.mp4",
      saveAs: true
    }, (downloadId) => {
      sendResponse({ success: !!downloadId, downloadId: downloadId });
    });
    return true; // Keep channel open for async response
  }
  return true;
});

