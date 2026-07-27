// MediaDownloader Pro - Content Script DOM Media Scanner

function scanDOMForMedia() {
  const mediaList = [];
  const pageUrl = window.location.href;
  const pageTitle = document.title || "Media File";

  // 1. Scan HTML5 <video> and <source> tags
  const videos = document.querySelectorAll('video, source');
  videos.forEach(v => {
    const src = v.src || v.getAttribute('src');
    if (src && !src.startsWith('blob:') && !src.startsWith('data:')) {
      const fullUrl = new URL(src, pageUrl).href;
      if (!mediaList.some(m => m.url === fullUrl)) {
        mediaList.push({
          url: fullUrl,
          title: pageTitle,
          type: fullUrl.includes('.m3u8') ? 'hls' : 'direct',
          source: 'HTML5 Video Tag'
        });
      }
    }
  });

  // 2. Scan for inline .m3u8 URLs in scripts or page HTML
  const htmlContent = document.documentElement.outerHTML;
  const m3u8Matches = htmlContent.match(/(https?:\/\/[^\s"'<>]+?\.m3u8[^\s"'<>]*)/g);
  if (m3u8Matches) {
    m3u8Matches.forEach(mUrl => {
      if (!mediaList.some(m => m.url === mUrl)) {
        mediaList.push({
          url: mUrl,
          title: pageTitle,
          type: 'hls',
          source: 'HLS Stream Match'
        });
      }
    });
  }

  // 3. Scan for iframes (embeds)
  const iframes = document.querySelectorAll('iframe');
  iframes.forEach(iframe => {
    const src = iframe.src || iframe.getAttribute('src');
    if (src && (src.includes('vixcloud') || src.includes('embed') || src.includes('iframe') || src.includes('bunkr') || src.includes('pixeldrain'))) {
      const fullUrl = new URL(src, pageUrl).href;
      if (!mediaList.some(m => m.url === fullUrl)) {
        mediaList.push({
          url: fullUrl,
          title: `${pageTitle} (Embed)`,
          type: 'stream',
          source: 'Embedded Player'
        });
      }
    }
  });

  return {
    pageUrl: pageUrl,
    pageTitle: pageTitle,
    media: mediaList
  };
}

// Listen for messages from extension popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "SCAN_PAGE_MEDIA") {
    const result = scanDOMForMedia();
    sendResponse(result);
  }
  return true;
});
