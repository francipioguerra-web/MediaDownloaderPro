// MediaDownloader Pro - In-Browser HLS Downloader Engine (Manifest V3)

class InBrowserHLSDownloader {
  constructor() {
    this.isPaused = false;
    this.isCancelled = false;
  }

  async parseM3U8(m3u8Url, customHeaders = {}) {
    const fetchOptions = { headers: customHeaders, credentials: 'include' };
    const res = await fetch(m3u8Url, fetchOptions);
    if (!res.ok) throw new Error(`Errore HTTP ${res.status} durante il recupero della playlist M3U8`);
    const text = await res.text();

    let playlistUrl = m3u8Url;
    let m3u8Text = text;

    // 1. If master playlist, select highest bandwidth sub-playlist
    if (m3u8Text.includes("#EXT-X-STREAM-INF")) {
      const lines = m3u8Text.split(/\r?\n/).map(l => l.trim()).filter(l => l);
      let bestSubUri = null;
      let maxBandwidth = -1;

      for (let i = 0; i < lines.length; i++) {
        if (lines[i].startsWith("#EXT-X-STREAM-INF")) {
          const bwMatch = lines[i].match(/BANDWIDTH=(\d+)/);
          const bw = bwMatch ? parseInt(bwMatch[1], 10) : 0;
          const nextLine = lines[i + 1];
          if (nextLine && !nextLine.startsWith("#")) {
            if (bw > maxBandwidth) {
              maxBandwidth = bw;
              bestSubUri = nextLine;
            }
          }
        }
      }

      if (!bestSubUri) {
        const subLines = lines.filter(l => !l.startsWith("#"));
        if (subLines.length > 0) bestSubUri = subLines[subLines.length - 1];
      }

      if (bestSubUri) {
        playlistUrl = new URL(bestSubUri, m3u8Url).href;
        const subRes = await fetch(playlistUrl, fetchOptions);
        if (subRes.ok) {
          m3u8Text = await subRes.text();
        }
      }
    }

    // 2. Parse TS segments and AES-128 encryption metadata
    const segments = [];
    let currentKeyInfo = null;

    const lines = m3u8Text.split(/\r?\n/).map(l => l.trim());
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.startsWith("#EXT-X-KEY")) {
        const methodMatch = line.match(/METHOD=([^,]+)/);
        const method = methodMatch ? methodMatch[1] : "NONE";

        if (method === "AES-128") {
          const uriMatch = line.match(/URI=["']?([^"',\s]+)["']?/);
          const ivMatch = line.match(/IV=0x([0-9a-fA-F]+)/);

          let keyUri = uriMatch ? uriMatch[1] : null;
          if (keyUri) {
            keyUri = new URL(keyUri, playlistUrl).href;
          }

          let iv = null;
          if (ivMatch) {
            const hex = ivMatch[1].padStart(32, '0');
            const bytes = new Uint8Array(16);
            for (let b = 0; b < 16; b++) {
              bytes[b] = parseInt(hex.substr(b * 2, 2), 16);
            }
            iv = bytes;
          }

          currentKeyInfo = { method: "AES-128", uri: keyUri, iv: iv };
        } else {
          currentKeyInfo = null;
        }
      } else if (line && !line.startsWith("#")) {
        const segmentUrl = new URL(line, playlistUrl).href;
        segments.push({
          url: segmentUrl,
          keyInfo: currentKeyInfo ? { ...currentKeyInfo } : null,
          index: segments.length
        });
      }
    }

    return { playlistUrl, segments };
  }

  async fetchEncryptionKey(keyUri, customHeaders = {}) {
    const res = await fetch(keyUri, { headers: customHeaders, credentials: 'include' });
    if (!res.ok) throw new Error(`Errore HTTP ${res.status} nel recupero della chiave AES-128`);
    const keyArrayBuffer = await res.arrayBuffer();
    return await crypto.subtle.importKey(
      "raw",
      keyArrayBuffer,
      { name: "AES-CBC" },
      false,
      ["decrypt"]
    );
  }

  async decryptSegment(cryptoKey, iv, encryptedBuffer) {
    return await crypto.subtle.decrypt(
      { name: "AES-CBC", iv: iv },
      cryptoKey,
      encryptedBuffer
    );
  }

  generateIvFromSeq(sequenceNumber) {
    const iv = new Uint8Array(16);
    const view = new DataView(iv.buffer);
    view.setUint32(12, sequenceNumber, false);
    return iv;
  }

  async downloadHLS(m3u8Url, customHeaders = {}, onProgress = () => {}) {
    this.isPaused = false;
    this.isCancelled = false;

    const { playlistUrl, segments } = await this.parseM3U8(m3u8Url, customHeaders);
    if (!segments || segments.length === 0) {
      throw new Error("Nessun frammento video trovato nella playlist M3U8.");
    }

    const total = segments.length;
    const downloadedBuffers = new Array(total);
    let completedCount = 0;
    let totalBytes = 0;
    const startTime = Date.now();
    const keyCache = new Map();

    const fetchWorker = async (segment) => {
      const { url, keyInfo, index } = segment;

      for (let attempt = 0; attempt < 4; attempt++) {
        if (this.isCancelled) throw new Error("DOWNLOAD_CANCELLED");

        while (this.isPaused) {
          if (this.isCancelled) throw new Error("DOWNLOAD_CANCELLED");
          await new Promise(r => setTimeout(r, 250));
        }

        try {
          const res = await fetch(url, { headers: customHeaders, credentials: 'include' });
          if (!res.ok) throw new Error(`Status HTTP ${res.status}`);
          let buffer = await res.arrayBuffer();

          // Decrypt segment if AES-128 encrypted
          if (keyInfo && keyInfo.method === "AES-128" && keyInfo.uri) {
            if (!keyCache.has(keyInfo.uri)) {
              const loadedKey = await this.fetchEncryptionKey(keyInfo.uri, customHeaders);
              keyCache.set(keyInfo.uri, loadedKey);
            }
            const cryptoKey = keyCache.get(keyInfo.uri);
            const iv = keyInfo.iv || this.generateIvFromSeq(index);
            buffer = await this.decryptSegment(cryptoKey, iv, buffer);
          }

          downloadedBuffers[index] = buffer;
          completedCount++;
          totalBytes += buffer.byteLength;

          const elapsedSec = (Date.now() - startTime) / 1000;
          const speedBps = elapsedSec > 0 ? totalBytes / elapsedSec : 0;
          const percent = (completedCount / total) * 100;

          onProgress({
            completedCount,
            total,
            totalBytes,
            percent: Math.min(99.9, percent),
            speedBps,
            state: "running"
          });

          return;
        } catch (err) {
          if (err.message === "DOWNLOAD_CANCELLED") throw err;
          await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
        }
      }

      throw new Error(`Impossibile scaricare il frammento video ${index + 1}/${total}`);
    };

    // Queue with 6 parallel download workers
    const concurrency = 6;
    const queue = [...segments];

    const workerLoop = async () => {
      while (queue.length > 0) {
        if (this.isCancelled) throw new Error("DOWNLOAD_CANCELLED");
        const segment = queue.shift();
        if (segment) {
          await fetchWorker(segment);
        }
      }
    };

    const workers = [];
    for (let w = 0; w < Math.min(concurrency, total); w++) {
      workers.push(workerLoop());
    }

    await Promise.all(workers);

    if (this.isCancelled) throw new Error("DOWNLOAD_CANCELLED");

    // Concatenate all segment ArrayBuffers into a single Blob
    const finalBlob = new Blob(downloadedBuffers, { type: "video/mp2t" });

    onProgress({
      completedCount: total,
      total,
      totalBytes: finalBlob.size,
      percent: 100.0,
      speedBps: 0,
      state: "completed"
    });

    return finalBlob;
  }

  pause() {
    this.isPaused = true;
  }

  resume() {
    this.isPaused = false;
  }

  cancel() {
    this.isCancelled = true;
  }
}

window.InBrowserHLSDownloader = InBrowserHLSDownloader;
