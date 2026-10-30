/* Subtitle analysis runs independently of the selected on-screen subtitle track. */
(function (root) {
  function seconds(value) {
    return value.replace(',', '.').split(':').reduce((total, part) => total * 60 + Number(part), 0);
  }

  const AMATEUR_CREDITS_RE = /(?:traduzi?on[ei]|sottotitol[io]|a cura di|tradott[oa]|dialoghi|revisione|adattamento|resync|sync\b|sincronizz|timing|editing|check\b|subs?factory|italiansubs|itasa|subspedia|subsfaction|addic7ed|opensubtitles|italian subs addicted|iscrew|tntvillage|swsub|subscene|podnapisi|tvsubtitles|buona visione|buon divertimento|vi aspettiamo|nostro forum|nostro sito|unisciti a noi|canale telegram|telegram|t\.me\/|discord|facebook|instagram|twitter|tutti i diritti|non a scopo di lucro|\b(?:ripped|encoded|muxed|uploaded|subbed|transcribed)\s+by\b|\b(?:downloaded|scaricato)\s+(?:from|da)\b|\btranscript\b|\bfansub|support us|become vip|advertise your|contact www|www\.[a-z0-9\-]+|https?:\/\/|\b[a-z0-9\-]+\.(?:com|net|org|it|me|info|io|tv|cc|ru|co|biz|sub\.it)\b)/i;

  function parse(text, offset = 0) {
    const map = text.match(/X-TIMESTAMP-MAP=.*LOCAL:([\d:.]+).*MPEGTS:(\d+)/);
    if (map) offset = Number(map[2]) / 90000 - seconds(map[1]);
    const cues = [];
    const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const regex = /((?:\d+:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{3})[^\n]*\n([\s\S]*?)(?=(?:\n\s*\n|\n(?:\d+\n)?(?:\d+:)?\d{2}:\d{2}[.,]\d{3}\s*-->|$))/g;
    let match;
    while ((match = regex.exec(normalized)) !== null) {
      const rawLines = match[3].split('\n');
      const cleanLines = [];
      for (const rawLine of rawLines) {
        const textOnly = rawLine.replace(/<[^>]*>/g, '').replace(/\{[^}]*\}/g, '').trim();
        if (!textOnly) continue;
        if (AMATEUR_CREDITS_RE.test(textOnly)) continue;
        if (/^\[[^\]]*(?:sub|ita|sync|traduz|release|credit)[^\]]*\]$/i.test(textOnly)) continue;
        if (/^[:=\-*~#\s]+$/.test(textOnly)) continue;
        cleanLines.push(textOnly);
      }
      if (!cleanLines.length) {
        continue;
      }
      cues.push({start: seconds(match[1]) + offset, end: seconds(match[2]) + offset});
    }
    if (!cues.length) {
      return Array.from(text.matchAll(/((?:\d+:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{3})/g), m => ({start: seconds(m[1]) + offset, end: seconds(m[2]) + offset}));
    }
    return cues;
  }
  function detect(cues, duration) {
    const sorted = cues.filter(c => c.start >= 0 && c.end > c.start && c.end <= duration + 1).sort((a,b) => a.start-b.start);
    if (sorted.length < 20 || !Number.isFinite(duration)) return {intro: null, outro: null};
    let end = 0, intro = null;
    for (const cue of sorted) {
      const gap = cue.start - end;
      if (!intro && end < Math.min(600, duration * .3) && gap >= 25 && gap <= 180) intro = {start: end, end: cue.start};
      end = Math.max(end, cue.end);
    }
    const outro = end >= duration * .75 && duration - end >= 15 && duration - end <= 300 ? end : null;
    return {intro, outro};
  }
  async function load(tracks, master, signal) {
    // Some manifests label forced tracks with FORCED=NO: inspect the name/language too.
    const candidates = (tracks || []).filter(t => t.forced !== true && t.forced !== 'YES' &&
      !/forced|forzati|forzato/i.test([t.name, t.lang, t.language].join(' ')) && (t.uri || t.url));
    candidates.sort((a,b) => Number(/^(it|ita|italian|italiano)([-_\s]|$)/i.test(b.lang || b.name || '')) - Number(/^(it|ita|italian|italiano)([-_\s]|$)/i.test(a.lang || a.name || '')));
    async function read(url, referrer) {
      const base = String(url).startsWith('/api/') ? location.href : new URL(master || location.href, location.href).href;
      const absolute = new URL(url, base).href;
      let proxy;
      const target = new URL(absolute);
      const localSubtitle = target.origin === new URL(location.href).origin && /^\/api\/subtitles\/file\/[0-9a-f]{32}\.vtt$/.test(target.pathname);
      if (localSubtitle || ['/api/stream/segment', '/api/vixcloud/media'].includes(target.pathname)) {
        proxy = absolute;
      } else {
        const ref = referrer || '';
        proxy = '/api/stream/segment?url=' + encodeURIComponent(absolute) + (ref ? '&ref=' + encodeURIComponent(ref) : '');
      }
      const response = await fetch(proxy, {signal});
      if (!response.ok) throw new Error('Subtitle request failed');
      return {text: await response.text(), url: absolute};
    }
    for (const track of candidates) {
      try {
        const trackRef = track.referrer || track.ref;
        const source = await read(track.uri || track.url, trackRef);
        if (!source.text.trimStart().startsWith('#EXTM3U')) {
          const cues = parse(source.text);
          if (cues.length >= 20) {
            cues.track = track;
            return cues;
          }
          continue;
        }
        // Only a complete VOD timeline can establish where dialogue ends.
        if (!source.text.includes('#EXT-X-ENDLIST')) continue;
        const segments = source.text.split(/\r\n|\r|\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#'));
        const cues = [];
        for (const segment of segments) {
          const part = await read(new URL(segment, segment.startsWith('/api/stream/segment?') ? location.href : source.url).href, trackRef);
          cues.push(...parse(part.text));
        }
        if (cues.length >= 20) {
          cues.track = track;
          return cues;
        }
      } catch (error) {
        if (signal?.aborted) return [];
        console.warn('[Subtitle chapters]', error);
      }
    }
    return [];
  }
  async function loadOnline(item, master, signal) {
    if (!item || signal?.aborted) return [];
    try {
      const response = await fetch('/api/subtitles/search', {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify(item), signal});
      if (!response.ok || signal?.aborted) return [];
      const result = await response.json();
      const tracks = (result.tracks || []).slice(0, 12);
      tracks.sort((a,b) => Number(/^(it|ita|italian|italiano)([-_\s]|$)/i.test(b.lang || b.name || '')) - Number(/^(it|ita|italian|italiano)([-_\s]|$)/i.test(a.lang || a.name || '')));
      return await load(tracks, master, signal);
    } catch (_) { return []; }
  }
  root.SubtitleChapters = {parse, detect, load, loadOnline};
})(typeof window === 'undefined' ? module.exports : window);
