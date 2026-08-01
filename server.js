const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const url = require('url');
const { v4: uuidv4 } = require('uuid');
const axios = require('axios');
const ffmpeg = require('fluent-ffmpeg');

// Puppeteer Stealth setup for Cloudflare bypass
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const app = express();
const PORT = process.env.PORT || 5050;

app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Setup Downloads directory
const DOWNLOADS_DIR = path.join(__dirname, 'downloads');
if (!fs.existsSync(DOWNLOADS_DIR)) {
  fs.mkdirSync(DOWNLOADS_DIR, { recursive: true });
}

// Serve static web dashboard
const PUBLIC_DIR = path.join(__dirname, 'public');
if (!fs.existsSync(PUBLIC_DIR)) {
  fs.mkdirSync(PUBLIC_DIR, { recursive: true });
}
app.use(express.static(PUBLIC_DIR));

// Default Browser Headers
const DEFAULT_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
  'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7'
};

// Global Download Manager state
const activeDownloads = new Map(); // downloadId -> state object

class NodeMediaEngine {
  constructor() {
    this.browserPromise = null;
  }

  async getBrowser() {
    if (!this.browserPromise) {
      const launchOptions = {
        headless: true,
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-dev-shm-usage',
          '--disable-accelerated-2d-canvas',
          '--no-first-run',
          '--no-zygote',
          '--disable-gpu'
        ]
      };

      if (process.env.PUPPETEER_EXECUTABLE_PATH) {
        launchOptions.executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
      }

      this.browserPromise = puppeteer.launch(launchOptions).catch(err => {
        console.error("Puppeteer launch error:", err);
        this.browserPromise = null;
        throw err;
      });
    }
    return this.browserPromise;
  }

  async analyzeUrl(targetUrl, customHeaders = {}) {
    if (!targetUrl || typeof targetUrl !== 'string') {
      return { error: "URL non fornito o non valido." };
    }

    const cleanUrl = targetUrl.trim();
    const parsed = url.parse(cleanUrl);
    if (!parsed.protocol || !parsed.hostname) {
      return { error: "URL non valido. Deve iniziare con http:// o https://" };
    }

    const urlLower = cleanUrl.toLowerCase();

    // 1. Vixcloud / StreamingCommunity resolution
    if (urlLower.includes('vixcloud.co') || urlLower.includes('streamingcommunity')) {
      const vixRes = await this.resolveVixcloud(cleanUrl, customHeaders);
      if (vixRes && !vixRes.error) return vixRes;
    }

    // 2. Direct HLS .m3u8 URL
    if (urlLower.includes('.m3u8')) {
      return {
        type: 'hls',
        title: `Flusso HLS Stream (${parsed.hostname})`,
        url: cleanUrl,
        file_size: 'Stream HLS (.m3u8)',
        source: parsed.hostname,
        duration: 'Playlist HLS',
        headers: { ...DEFAULT_HEADERS, ...customHeaders }
      };
    }

    // 3. Direct video file (.mp4, .mkv, .webm, .mp3, etc.)
    const directExts = ['.mp4', '.mkv', '.webm', '.mov', '.avi', '.mp3', '.m4a', '.flac', '.wav'];
    if (directExts.some(ext => parsed.pathname.toLowerCase().endsWith(ext)) || urlLower.includes('pixeldrain.com/api/file/')) {
      return this.analyzeDirectFile(cleanUrl, customHeaders);
    }

    // 4. Puppeteer Stealth Page Sniffer Fallback (Cloudflare Bypass)
    try {
      return await this.sniffWithPuppeteer(cleanUrl);
    } catch (err) {
      return {
        type: 'stream',
        title: `Video Stream (${parsed.hostname})`,
        url: cleanUrl,
        file_size: 'Contenuto Web',
        source: parsed.hostname,
        duration: 'N/D',
        headers: { ...DEFAULT_HEADERS, ...customHeaders }
      };
    }
  }

  async resolveVixcloud(cleanUrl, customHeaders = {}) {
    try {
      const parsed = url.parse(cleanUrl);
      const embedMatch = cleanUrl.match(/\/(?:playlist|embed|iframe)\/(\d+)/);
      const embedId = embedMatch ? embedMatch[1] : '';

      let m3u8Path = parsed.pathname || '';
      m3u8Path = m3u8Path.replace('/embed/', '/playlist/').replace('/iframe/', '/playlist/');
      if (!m3u8Path.endsWith('.m3u8')) {
        m3u8Path += '.m3u8';
      }

      const fullM3U8 = url.format({
        protocol: parsed.protocol,
        host: parsed.host,
        pathname: m3u8Path,
        search: parsed.search
      });

      const referer = embedId ? `https://vixcloud.co/embed/${embedId}` : 'https://vixcloud.co/';

      return {
        type: 'hls',
        title: `Stream Vixcloud (${embedId || parsed.hostname})`,
        url: fullM3U8,
        file_size: 'Stream HLS (Vixcloud)',
        source: 'Vixcloud',
        duration: 'HLS Stream',
        headers: {
          ...DEFAULT_HEADERS,
          'Referer': referer,
          'Origin': 'https://vixcloud.co',
          ...customHeaders
        }
      };
    } catch (err) {
      return { error: `Errore risoluzione Vixcloud: ${err.message}` };
    }
  }

  async analyzeDirectFile(fileUrl, customHeaders = {}) {
    try {
      const res = await axios.head(fileUrl, {
        headers: { ...DEFAULT_HEADERS, ...customHeaders },
        timeout: 6000
      });
      const sizeBytes = parseInt(res.headers['content-length'] || '0', 10);
      const parsed = url.parse(fileUrl);
      const filename = path.basename(parsed.pathname) || 'media_file.mp4';

      return {
        type: 'direct',
        title: decodeURIComponent(filename),
        url: fileUrl,
        file_size: this.formatSize(sizeBytes),
        source: parsed.hostname,
        duration: 'File Diretto',
        headers: { ...DEFAULT_HEADERS, ...customHeaders }
      };
    } catch (err) {
      const parsed = url.parse(fileUrl);
      return {
        type: 'direct',
        title: path.basename(parsed.pathname) || 'Media File',
        url: fileUrl,
        file_size: 'File Rilevato',
        source: parsed.hostname,
        duration: 'N/D',
        headers: { ...DEFAULT_HEADERS, ...customHeaders }
      };
    }
  }

  async sniffWithPuppeteer(pageUrl) {
    const browser = await this.getBrowser();
    const page = await browser.newPage();
    let detectedMedia = null;

    try {
      await page.setUserAgent(DEFAULT_HEADERS['User-Agent']);
      await page.setExtraHTTPHeaders({ 'Accept-Language': DEFAULT_HEADERS['Accept-Language'] });

      // Intercept network requests for m3u8 or media streams
      await page.setRequestInterception(true);
      page.on('request', req => {
        const reqUrl = req.url();
        if (reqUrl.includes('.m3u8') || reqUrl.includes('/playlist/') || reqUrl.includes('vixcloud.co')) {
          if (!detectedMedia) {
            detectedMedia = {
              type: 'hls',
              url: reqUrl,
              headers: req.headers()
            };
          }
        }
        req.continue();
      });

      await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 12000 });
      const pageTitle = await page.title();

      if (detectedMedia) {
        detectedMedia.title = pageTitle || 'Video Rilevato';
        detectedMedia.source = url.parse(pageUrl).hostname;
        detectedMedia.file_size = 'Stream HLS Rilevato';
        detectedMedia.duration = 'Playlist .m3u8';
        await page.close();
        return detectedMedia;
      }

      // Check DOM for <video> tags
      const videoSrc = await page.evaluate(() => {
        const v = document.querySelector('video, source');
        return v ? (v.src || v.getAttribute('src')) : null;
      });

      await page.close();

      if (videoSrc && !videoSrc.startsWith('blob:') && !videoSrc.startsWith('data:')) {
        const fullVideoUrl = new URL(videoSrc, pageUrl).href;
        return {
          type: fullVideoUrl.includes('.m3u8') ? 'hls' : 'direct',
          title: pageTitle || 'Video Rilevato',
          url: fullVideoUrl,
          file_size: 'File Video Rilevato',
          source: url.parse(pageUrl).hostname,
          duration: 'N/D'
        };
      }
    } catch (err) {
      try { await page.close(); } catch (e) {}
    }

    return {
      type: 'stream',
      title: 'Video Stream',
      url: pageUrl,
      file_size: 'Contenuto Web',
      source: url.parse(pageUrl).hostname,
      duration: 'N/D'
    };
  }

  async startDownloadJob(downloadId, mediaUrl, mediaType, formatChoice, customTitle, customHeaders = {}) {
    const downloadState = {
      download_id: downloadId,
      url: mediaUrl,
      state: 'starting',
      percent: 0.0,
      speed: '0 MB/s',
      downloaded: '0 MB',
      total: 'N/D',
      filename: null,
      download_url: null,
      error: null
    };

    activeDownloads.set(downloadId, downloadState);

    // Run async download
    this.runDownloadProcess(downloadId, mediaUrl, mediaType, formatChoice, customTitle, customHeaders)
      .catch(err => {
        console.error(`Download job ${downloadId} error:`, err);
        const st = activeDownloads.get(downloadId);
        if (st) {
          if (err.message === 'DOWNLOAD_CANCELLED') {
            st.state = 'cancelled';
          } else {
            st.state = 'error';
            st.error = err.message || 'Errore durante il download';
          }
        }
      });

    return { download_id: downloadId, status: 'started' };
  }

  async runDownloadProcess(downloadId, mediaUrl, mediaType, formatChoice, customTitle, customHeaders) {
    const safeTitle = customTitle 
      ? customTitle.replace(/[^a-zA-Z0-9_\-\s]/g, '_').trim() 
      : `video_${downloadId}`;

    const isHLS = mediaType === 'hls' || mediaUrl.includes('.m3u8') || mediaUrl.includes('vixcloud');

    if (isHLS) {
      await this.downloadHlsStream(downloadId, mediaUrl, safeTitle, customHeaders);
    } else {
      await this.downloadDirectFile(downloadId, mediaUrl, safeTitle, customHeaders);
    }
  }

  async downloadHlsStream(downloadId, m3u8Url, safeTitle, customHeaders) {
    const downloadState = activeDownloads.get(downloadId);
    downloadState.state = 'running';

    const reqHeaders = { ...DEFAULT_HEADERS, ...customHeaders };
    if (m3u8Url.includes('vixcloud.co')) {
      const embedMatch = m3u8Url.match(/\/(?:playlist|embed|iframe)\/(\d+)/);
      const embedId = embedMatch ? embedMatch[1] : '';
      if (!reqHeaders['Referer']) {
        reqHeaders['Referer'] = embedId ? `https://vixcloud.co/embed/${embedId}` : 'https://vixcloud.co/';
      }
      reqHeaders['Origin'] = 'https://vixcloud.co';
    }

    // Fetch M3U8 Playlist
    const resM3u8 = await axios.get(m3u8Url, { headers: reqHeaders, timeout: 10000 });
    let m3u8Text = resM3u8.data;
    let playlistUrl = m3u8Url;

    // Handle master playlist variant selection
    if (m3u8Text.includes('#EXT-X-STREAM-INF')) {
      const lines = m3u8Text.split(/\r?\n/).map(l => l.trim()).filter(l => l);
      let bestSubUri = null;
      let maxBw = -1;

      for (let i = 0; i < lines.length; i++) {
        if (lines[i].startsWith('#EXT-X-STREAM-INF')) {
          const bwMatch = lines[i].match(/BANDWIDTH=(\d+)/);
          const bw = bwMatch ? parseInt(bwMatch[1], 10) : 0;
          const next = lines[i + 1];
          if (next && !next.startsWith('#')) {
            if (bw > maxBw) {
              maxBw = bw;
              bestSubUri = next;
            }
          }
        }
      }

      if (!bestSubUri) {
        const subLines = lines.filter(l => !l.startsWith('#'));
        if (subLines.length > 0) bestSubUri = subLines[subLines.length - 1];
      }

      if (bestSubUri) {
        playlistUrl = new URL(bestSubUri, m3u8Url).href;
        const subRes = await axios.get(playlistUrl, { headers: reqHeaders, timeout: 10000 });
        m3u8Text = subRes.data;
      }
    }

    // Parse segments
    const segmentUrls = [];
    const lines = m3u8Text.split(/\r?\n/).map(l => l.trim());
    for (const line of lines) {
      if (line && !line.startsWith('#')) {
        segmentUrls.push(new URL(line, playlistUrl).href);
      }
    }

    if (segmentUrls.length === 0) {
      throw new Error('Nessun frammento video trovato nella playlist M3U8');
    }

    const totalSegments = segmentUrls.length;
    const tsFilename = `${safeTitle}_${downloadId}.ts`;
    const mp4Filename = `${safeTitle}.mp4`;
    const tsFilePath = path.join(DOWNLOADS_DIR, tsFilename);
    const mp4FilePath = path.join(DOWNLOADS_DIR, mp4Filename);

    let downloadedCount = 0;
    let totalBytes = 0;
    const startTime = Date.now();
    const segmentBuffers = new Array(totalSegments);

    // Parallel Segment Downloading (6 workers)
    const concurrency = 6;
    let queueIdx = 0;

    const worker = async () => {
      while (queueIdx < totalSegments) {
        this.checkDownloadState(downloadId);

        const i = queueIdx++;
        const segUrl = segmentUrls[i];

        let fetched = false;
        for (let attempt = 0; attempt < 3; attempt++) {
          this.checkDownloadState(downloadId);
          try {
            const segRes = await axios.get(segUrl, {
              headers: reqHeaders,
              responseType: 'arraybuffer',
              timeout: 15000
            });
            if (segRes.status === 200 && segRes.data) {
              const buf = Buffer.from(segRes.data);
              segmentBuffers[i] = buf;
              downloadedCount++;
              totalBytes += buf.length;

              const elapsedSec = (Date.now() - startTime) / 1000;
              const speedBps = elapsedSec > 0 ? totalBytes / elapsedSec : 0;
              const percent = Math.min(85.0, (downloadedCount / totalSegments) * 85.0);

              downloadState.percent = parseFloat(percent.toFixed(1));
              downloadState.speed = `${this.formatSize(speedBps)}/s`;
              downloadState.downloaded = `${downloadedCount}/${totalSegments} seg (${this.formatSize(totalBytes)})`;
              downloadState.total = `${totalSegments} seg`;

              fetched = true;
              break;
            }
          } catch (e) {
            await new Promise(r => setTimeout(r, 500 * (attempt + 1)));
          }
        }

        if (!fetched) {
          throw new Error(`Impossibile scaricare il frammento HLS ${i + 1}/${totalSegments}`);
        }
      }
    };

    const workers = [];
    for (let w = 0; w < Math.min(concurrency, totalSegments); w++) {
      workers.push(worker());
    }

    await Promise.all(workers);
    this.checkDownloadState(downloadId);

    // Concatenate segments to TS file
    const tsStream = fs.createWriteStream(tsFilePath);
    for (let i = 0; i < totalSegments; i++) {
      if (segmentBuffers[i]) {
        tsStream.write(segmentBuffers[i]);
      }
    }
    tsStream.end();

    await new Promise((res, rej) => {
      tsStream.on('finish', res);
      tsStream.on('error', rej);
    });

    const tsStats = fs.statSync(tsFilePath);
    if (!tsStats || tsStats.size < 1000) {
      if (fs.existsSync(tsFilePath)) fs.unlinkSync(tsFilePath);
      throw new Error('File TS generato è vuoto o corrotto.');
    }

    // Remux TS to MP4 using fluent-ffmpeg
    downloadState.percent = 90.0;
    downloadState.speed = 'Elaborazione MP4...';
    downloadState.downloaded = 'Remuxing MP4 in corso...';

    let finalFilename = mp4Filename;

    try {
      await new Promise((resolve, reject) => {
        ffmpeg(tsFilePath)
          .outputOptions('-c copy')
          .save(mp4FilePath)
          .on('end', resolve)
          .on('error', reject);
      });

      if (fs.existsSync(mp4FilePath) && fs.statSync(mp4FilePath).size > 1000) {
        if (fs.existsSync(tsFilePath)) fs.unlinkSync(tsFilePath);
        finalFilename = mp4Filename;
      } else {
        finalFilename = tsFilename;
      }
    } catch (ffErr) {
      console.warn("FFmpeg remux failed, keeping TS format:", ffErr.message);
      finalFilename = tsFilename;
    }

    downloadState.state = 'completed';
    downloadState.percent = 100.0;
    downloadState.filename = finalFilename;
    downloadState.download_url = `/api/download/file/${encodeURIComponent(finalFilename)}`;
  }

  async downloadDirectFile(downloadId, fileUrl, safeTitle, customHeaders) {
    const downloadState = activeDownloads.get(downloadId);
    downloadState.state = 'running';

    const reqHeaders = { ...DEFAULT_HEADERS, ...customHeaders };
    const parsed = url.parse(fileUrl);
    const ext = path.extname(parsed.pathname) || '.mp4';
    const filename = `${safeTitle}${ext}`;
    const filePath = path.join(DOWNLOADS_DIR, filename);

    const res = await axios({
      method: 'get',
      url: fileUrl,
      headers: reqHeaders,
      responseType: 'stream',
      timeout: 15000
    });

    const totalBytes = parseInt(res.headers['content-length'] || '0', 10);
    let downloadedBytes = 0;
    const startTime = Date.now();

    const writer = fs.createWriteStream(filePath);
    res.data.pipe(writer);

    res.data.on('data', chunk => {
      this.checkDownloadState(downloadId);
      downloadedBytes += chunk.length;

      const elapsedSec = (Date.now() - startTime) / 1000;
      const speedBps = elapsedSec > 0 ? downloadedBytes / elapsedSec : 0;
      const percent = totalBytes > 0 ? (downloadedBytes / totalBytes) * 100 : 0;

      downloadState.percent = parseFloat(percent.toFixed(1));
      downloadState.speed = `${this.formatSize(speedBps)}/s`;
      downloadState.downloaded = this.formatSize(downloadedBytes);
      downloadState.total = this.formatSize(totalBytes);
    });

    await new Promise((resolve, reject) => {
      writer.on('finish', resolve);
      writer.on('error', reject);
      res.data.on('error', reject);
    });

    const fileStats = fs.statSync(filePath);
    if (!fileStats || fileStats.size < 1000) {
      if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
      throw new Error('File scaricato è vuoto o incompleto.');
    }

    downloadState.state = 'completed';
    downloadState.percent = 100.0;
    downloadState.filename = filename;
    downloadState.download_url = `/api/download/file/${encodeURIComponent(filename)}`;
  }

  checkDownloadState(downloadId) {
    const st = activeDownloads.get(downloadId);
    if (st) {
      if (st.state === 'cancelled') throw new Error('DOWNLOAD_CANCELLED');
      while (st.state === 'paused') {
        if (st.state === 'cancelled') throw new Error('DOWNLOAD_CANCELLED');
        // Synchronous sleep inside worker
        const stop = Date.now() + 300;
        while (Date.now() < stop) {}
      }
    }
  }

  formatSize(sizeBytes) {
    if (!sizeBytes || sizeBytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    let size = sizeBytes;
    while (size >= 1024 && i < units.length - 1) {
      size /= 1024.0;
      i++;
    }
    return `${size.toFixed(1)} ${units[i]}`;
  }
}

const mediaEngine = new NodeMediaEngine();

// API Routes
app.get('/api/ping', (req, res) => {
  res.json({
    status: 'ok',
    app: 'MediaDownloader Pro (Node.js)',
    version: '3.0'
  });
});

app.get('/api/download/active', (req, res) => {
  const active = [];
  for (const [id, info] of activeDownloads.entries()) {
    if (['running', 'paused', 'starting'].includes(info.state)) {
      active.push(info);
    }
  }
  res.json({ downloads: active });
});

app.post('/api/analyze', async (req, res) => {
  const { url, headers } = req.body || {};
  const result = await mediaEngine.analyzeUrl(url, headers);
  res.json(result);
});

app.post('/api/download/start', async (req, res) => {
  const { url, media_type, format_choice, custom_title, custom_headers } = req.body || {};
  const downloadId = `dl_${Date.now()}_${uuidv4().substring(0, 6)}`;
  
  const result = await mediaEngine.startDownloadJob(
    downloadId,
    url,
    media_type,
    format_choice,
    custom_title,
    custom_headers
  );
  
  res.json(result);
});

app.get('/api/download/status/:downloadId', (req, res) => {
  const downloadId = req.params.downloadId;
  const status = activeDownloads.get(downloadId);
  if (status) {
    res.json(status);
  } else {
    res.json({ state: 'not_found', percent: 0 });
  }
});

app.post('/api/download/pause/:downloadId', (req, res) => {
  const downloadId = req.params.downloadId;
  const st = activeDownloads.get(downloadId);
  if (st && st.state === 'running') {
    st.state = 'paused';
    return res.json({ success: true });
  }
  res.json({ success: false });
});

app.post('/api/download/resume/:downloadId', (req, res) => {
  const downloadId = req.params.downloadId;
  const st = activeDownloads.get(downloadId);
  if (st && st.state === 'paused') {
    st.state = 'running';
    return res.json({ success: true });
  }
  res.json({ success: false });
});

app.post('/api/download/cancel/:downloadId', (req, res) => {
  const downloadId = req.params.downloadId;
  const st = activeDownloads.get(downloadId);
  if (st) {
    st.state = 'cancelled';
    return res.json({ success: true });
  }
  res.json({ success: false });
});

app.get('/api/download/file/:filename', (req, res) => {
  const filename = decodeURIComponent(req.params.filename);
  const filePath = path.join(DOWNLOADS_DIR, filename);
  if (fs.existsSync(filePath)) {
    res.download(filePath, filename);
  } else {
    res.status(404).json({ error: 'File non trovato' });
  }
});

// Start Node.js Express server
app.listen(PORT, () => {
  console.log('=' .repeat(60));
  console.log(' 🚀 MEDIA DOWNLOADER PRO - NODE.JS BACKEND SERVER STARTED!');
  console.log(` 🌐 Server URL: http://localhost:${PORT}`);
  console.log('=' .repeat(60));
});
