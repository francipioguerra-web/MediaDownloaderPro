#!/usr/bin/env node
/**
 * StreamingCommunity - Standalone Dedicated Watch Party Hub & Profile Server
 * Node.js Express implementation for Render deployment.
 */

const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(cors({ origin: '*' }));
app.use(express.json({ limit: '20mb' }));
app.use(express.urlencoded({ extended: true, limit: '20mb' }));

// Directories
const BASE_DIR = __dirname;
const DATA_DIR = process.env.DATA_DIR || path.join(BASE_DIR, 'data');
if (!fs.existsSync(DATA_DIR)) {
  try { fs.mkdirSync(DATA_DIR, { recursive: true }); } catch (e) {}
}

const SEED_FILE = path.join(BASE_DIR, 'seed_data.json');
let SEED_DATA = { profiles: { active_profile_id: null, profiles: [] }, favorites: {}, history: {}, dates_cache: {} };
if (fs.existsSync(SEED_FILE)) {
  try {
    SEED_DATA = JSON.parse(fs.readFileSync(SEED_FILE, 'utf8'));
  } catch (e) {
    console.error('Error loading seed_data.json:', e);
  }
}

const PROFILES_FILE = path.join(DATA_DIR, 'profiles.json');
const WATCHPARTY_FILE = path.join(DATA_DIR, 'watchparty.json');
const FAVORITES_FILE = path.join(DATA_DIR, 'favorites.json');
const HISTORY_FILE = path.join(DATA_DIR, 'history.json');

function readJsonSafe(filePath, defaultVal) {
  if (fs.existsSync(filePath)) {
    try {
      const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      if (parsed) return parsed;
    } catch (e) {}
  }
  return defaultVal;
}

function writeJsonSafe(filePath, data) {
  try {
    const tmp = `${filePath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
    fs.renameSync(tmp, filePath);
  } catch (e) {
    console.error(`Error writing ${filePath}:`, e);
  }
}

// Ensure persistent files exist with seed data fallback
function getProfilesData() {
  let data = readJsonSafe(PROFILES_FILE, null);
  if (!data || !Array.isArray(data.profiles) || data.profiles.length < 2) {
    data = SEED_DATA.profiles || { active_profile_id: null, profiles: [] };
    writeJsonSafe(PROFILES_FILE, data);
  }
  return data;
}

function getFavoritesData() {
  let data = readJsonSafe(FAVORITES_FILE, null);
  if (!data || Object.keys(data).length === 0) {
    data = SEED_DATA.favorites || {};
    writeJsonSafe(FAVORITES_FILE, data);
  }
  return data;
}

function getHistoryData() {
  let data = readJsonSafe(HISTORY_FILE, null);
  if (!data || (Array.isArray(data) && data.length === 0)) {
    data = SEED_DATA.history || [];
    writeJsonSafe(HISTORY_FILE, data);
  }
  return data;
}

function getWatchPartyData() {
  let data = readJsonSafe(WATCHPARTY_FILE, { sessions: [] });
  const now = Date.now();
  data.sessions = (data.sessions || []).filter(s => (now - (s.created_at || 0)) < 3 * 3600 * 1000);
  return data;
}

// ----------------- ROOT & HEALTH -----------------
app.get('/', (req, res) => {
  const pData = getProfilesData();
  const wpData = getWatchPartyData();
  const names = (pData.profiles || []).map(p => p.name).join(', ') || 'Nessuno';
  const activeRooms = (wpData.sessions || []).filter(s => s.status === 'waiting' || s.status === 'active').length;

  if (req.headers.accept && req.headers.accept.includes('application/json') && !req.headers.accept.includes('text/html')) {
    return res.json({
      status: 'ok',
      service: 'StreamingCommunity WatchParty Hub',
      version: '2.0.0',
      active_rooms: activeRooms,
      profiles: (pData.profiles || []).map(p => p.name),
      timestamp: Date.now()
    });
  }

  res.send(`<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>WatchParty Hub</title></head>
<body style="background:#0b0b0e; color:#fff; font-family:sans-serif; text-align:center; padding:40px;">
  <h1 style="color:#ef4444;">StreamingCommunity WatchParty Hub</h1>
  <p>Server online e sincronizzato con successo.</p>
  <p><strong>Profili attivi:</strong> ${names}</p>
  <p><strong>Stanze attive:</strong> ${activeRooms}</p>
</body>
</html>`);
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'watchparty-hub', timestamp: Date.now() });
});

// ----------------- PROFILES API -----------------
app.get('/api/profiles', (req, res) => {
  const pData = getProfilesData();
  const sanitized = (pData.profiles || []).map(p => {
    const copy = { ...p };
    copy.has_pin = Boolean(copy.pin);
    delete copy.pin;
    delete copy.history;
    delete copy.favorites;
    return copy;
  });
  res.json({
    active_profile_id: pData.active_profile_id || null,
    profiles: sanitized
  });
});

// ----------------- USER DATA BUNDLE -----------------
app.get('/api/user_data/bundle', (req, res) => {
  res.json({
    success: true,
    profiles: getProfilesData(),
    favorites: getFavoritesData(),
    history: getHistoryData(),
    timestamp: Date.now()
  });
});

app.post('/api/user_data/sync', (req, res) => {
  const body = req.body || {};
  if (body.profiles) writeJsonSafe(PROFILES_FILE, body.profiles);
  if (body.favorites) writeJsonSafe(FAVORITES_FILE, body.favorites);
  if (body.history) writeJsonSafe(HISTORY_FILE, body.history);
  res.json({ success: true, message: 'Dati sincronizzati con successo' });
});

// ----------------- WATCH PARTY ENDPOINTS -----------------
app.post('/api/watchparty/create', (req, res) => {
  const { host_profile_id, guest_profile_id, item } = req.body || {};
  if (!host_profile_id || !guest_profile_id || !item) {
    return res.status(400).json({ success: false, error: 'Parametri mancanti' });
  }

  const pData = getProfilesData();
  const profs = {};
  (pData.profiles || []).forEach(p => { profs[p.id] = p; });

  const hostProf = profs[host_profile_id] || { name: 'Host', avatar: 'preset:netflix-red' };
  const guestProf = profs[guest_profile_id] || { name: 'Ospite', avatar: 'preset:amber-crown' };

  const sessionId = `wp_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
  const session = {
    session_id: sessionId,
    host_profile_id,
    host_name: hostProf.name,
    host_avatar: hostProf.avatar,
    guest_profile_id,
    guest_name: guestProf.name,
    guest_avatar: guestProf.avatar,
    item,
    status: 'waiting',
    current_time: 0,
    paused: true,
    playback_rate: 1.0,
    last_seq: 0,
    last_action: 'create',
    created_at: Date.now(),
    last_sync: Date.now()
  };

  const wpData = getWatchPartyData();
  wpData.sessions.push(session);
  writeJsonSafe(WATCHPARTY_FILE, wpData);

  res.json({ success: true, session });
});

app.get('/api/watchparty/pending', (req, res) => {
  const profileId = req.query.profile_id;
  if (!profileId) return res.status(400).json({ success: false, error: 'profile_id mancante' });

  const wpData = getWatchPartyData();
  const pending = (wpData.sessions || []).filter(s => s.guest_profile_id === profileId && s.status === 'waiting');
  res.json({ success: true, sessions: pending });
});

app.post('/api/watchparty/accept', (req, res) => {
  const { session_id } = req.body || {};
  if (!session_id) return res.status(400).json({ success: false, error: 'session_id mancante' });

  const wpData = getWatchPartyData();
  const session = (wpData.sessions || []).find(s => s.session_id === session_id);
  if (!session) return res.status(404).json({ success: false, error: 'Sessione non trovata' });

  session.status = 'active';
  session.last_sync = Date.now();
  writeJsonSafe(WATCHPARTY_FILE, wpData);

  res.json({ success: true, session });
});

app.post('/api/watchparty/decline', (req, res) => {
  const { session_id } = req.body || {};
  if (!session_id) return res.status(400).json({ success: false, error: 'session_id mancante' });

  const wpData = getWatchPartyData();
  const session = (wpData.sessions || []).find(s => s.session_id === session_id);
  if (!session) return res.status(404).json({ success: false, error: 'Sessione non trovata' });

  session.status = 'declined';
  session.last_sync = Date.now();
  writeJsonSafe(WATCHPARTY_FILE, wpData);

  res.json({ success: true });
});

app.post('/api/watchparty/sync', (req, res) => {
  const body = req.body || {};
  const { session_id, current_time, paused, playback_rate, seq, stream_url, episode_id, season_number, episode_number } = body;
  if (!session_id) return res.status(400).json({ success: false, error: 'session_id mancante' });

  const wpData = getWatchPartyData();
  const session = (wpData.sessions || []).find(s => s.session_id === session_id);
  if (!session || session.status !== 'active') {
    return res.status(404).json({ success: false, error: 'Sessione non attiva' });
  }

  if (current_time !== undefined && current_time !== null) session.current_time = Number(current_time) || 0;
  if (paused !== undefined && paused !== null) session.paused = Boolean(paused);
  if (playback_rate !== undefined && playback_rate !== null) session.playback_rate = Number(playback_rate) || 1.0;
  if (seq !== undefined && seq !== null) session.last_seq = Number(seq) || 0;
  if (stream_url) session.stream_url = stream_url;
  if (episode_id) session.current_episode_id = episode_id;
  if (season_number) session.current_season_number = season_number;
  if (episode_number) session.current_episode_number = episode_number;

  session.last_action = body.action || session.last_action || 'sync';
  session.last_sync = Date.now();
  writeJsonSafe(WATCHPARTY_FILE, wpData);

  res.json({ success: true, session });
});

app.get('/api/watchparty/state', (req, res) => {
  const sessionId = req.query.session_id;
  if (!sessionId) return res.status(400).json({ success: false, error: 'session_id mancante' });

  const wpData = getWatchPartyData();
  const session = (wpData.sessions || []).find(s => s.session_id === sessionId);
  if (!session) return res.status(404).json({ success: false, error: 'Sessione non trovata' });

  res.json({ success: true, session });
});

app.post('/api/watchparty/end', (req, res) => {
  const { session_id } = req.body || {};
  if (!session_id) return res.status(400).json({ success: false, error: 'session_id mancante' });

  const wpData = getWatchPartyData();
  const session = (wpData.sessions || []).find(s => s.session_id === session_id);
  if (!session) return res.status(404).json({ success: false, error: 'Sessione non trovata' });

  session.status = 'ended';
  session.last_sync = Date.now();
  writeJsonSafe(WATCHPARTY_FILE, wpData);

  res.json({ success: true });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`WatchParty Hub Server running on http://0.0.0.0:${PORT}`);
});
