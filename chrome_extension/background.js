// MediaDownloader Pro - Background Service Worker (Manifest V3)

const tabMediaMap = {};

// Filter patterns for video/audio streams
const MEDIA_PATTERNS = [
  "*.m3u8*",
  "*vixcloud.co/playlist*",
  "*vixcloud.co/embed*",
  "*.mp4*",
  "*.mkv*",
  "*.webm*",
  "*.m4a*",
  "*.mp3*"
];

// Listen for network requests matching media patterns
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (!details.url || details.tabId < 0) return;
    const url = details.url;

    // Ignore tiny requests / images / analytics
    if (url.includes(".png") || url.includes(".jpg") || url.includes(".svg") || url.includes("google-analytics")) {
      return;
    }

    if (!tabMediaMap[details.tabId]) {
      tabMediaMap[details.tabId] = [];
    }

    // Check if URL already recorded
    const exists = tabMediaMap[details.tabId].some(item => item.url === url);
    if (!exists) {
      let mediaType = "direct";
      if (url.includes(".m3u8") || url.includes("vixcloud.co")) {
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

// Handle incoming runtime messages
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "GET_SNIFFED_MEDIA") {
    const tabId = request.tabId;
    const items = tabMediaMap[tabId] || [];
    sendResponse({ success: true, media: items });
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
