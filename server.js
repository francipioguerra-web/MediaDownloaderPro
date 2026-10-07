#!/usr/bin/env node
/**
 * StreamingCommunity / MediaDownloaderPro
 * Standalone Dedicated Watch Party Hub & Profile Server with Real-Time Socket.IO
 *
 * Supporta sia API REST (compatibilità retroattiva) sia WebSockets bidirezionali (Socket.IO):
 * - Stato autorevole della stanza
 * - Ruoli Host (👑) e Ospite (👤)
 * - Modalità controlli ("Solo host" vs "Tutti")
 * - Correzione drift a 3 livelli
 * - Sincronizzazione real-time istantanea a 0 latenza per play, pause, seek ed episodio
 */

const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
const server = http.createServer(app);
const PORT = process.env.PORT || 10000;

app.use(cors({ origin: '*' }));
app.use(express.json({ limit: '20mb' }));
app.use(express.urlencoded({ extended: true, limit: '20mb' }));

// ----------------- SOCKET.IO SETUP -----------------
const io = new Server(server, {
  cors: {
    origin: '*',
    methods: ['GET', 'POST']
  },
  pingInterval: 10000,
  pingTimeout: 5000,
  transports: ['websocket', 'polling']
});

// Store in-memory per stanze real-time Socket.IO
// roomId -> { roomId, hostSocketId, hostProfile, controlMode, playing, currentTime, playbackRate, updatedAt, item, streamUrl, members: Map }
const activeSocketRooms = new Map();

// Helper serializzazione stato pubblico stanza
function getSocketRoomPublicState(room) {
  if (!room) return null;
  const membersList = Array.from(room.members.values()).map(m => ({
    socketId: m.socketId,
    profileId: m.profile?.id || m.socketId,
    name: m.profile?.name || (m.isHost ? 'Host' : 'Ospite'),
    avatar: m.profile?.avatar || '',
    isHost: Boolean(m.isHost),
    ready: Boolean(m.ready),
    buffering: Boolean(m.buffering)
  }));

  return {
    roomId: room.roomId,
    playing: Boolean(room.playing),
    currentTime: Number(room.currentTime) || 0,
    playbackRate: Number(room.playbackRate) || 1.0,
    updatedAt: Number(room.updatedAt) || Date.now(),
    serverTimestamp: Date.now(),
    hostId: room.hostSocketId,
    hostProfile: room.hostProfile,
    controlMode: room.controlMode || 'host-only', // 'host-only' | 'all'
    item: room.item || null,
    streamUrl: room.streamUrl || '',
    members: membersList
  };
}

// ----------------- DATA DIRECTORIES & PERSISTENCE -----------------
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
  if (!data || (Array.isArray(data) && data.length === 0) || (typeof data === 'object' && Object.keys(data).length === 0)) {
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
  const activeRooms = (wpData.sessions || []).filter(s => s.status === 'waiting' || s.status === 'active').length + activeSocketRooms.size;

  if (req.headers.accept && req.headers.accept.includes('application/json') && !req.headers.accept.includes('text/html')) {
    return res.json({
      status: 'ok',
      service: 'StreamingCommunity WatchParty Hub',
      version: '2.1.0',
      socket_rooms: activeSocketRooms.size,
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
  <p>Server online con supporto <strong>Socket.IO Real-Time</strong> e sincronizzazione bidirezionale attiva.</p>
  <p><strong>Profili attivi:</strong> ${names}</p>
  <p><strong>Stanze Socket.IO attive:</strong> ${activeSocketRooms.size}</p>
</body>
</html>`);
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'watchparty-hub', socket_rooms: activeSocketRooms.size, timestamp: Date.now() });
});

// Link diretto stanza: /watch/:roomId -> redirect a /?room=:roomId
app.get('/watch/:roomId', (req, res) => {
  const roomId = encodeURIComponent(req.params.roomId);
  res.redirect(`/?room=${roomId}`);
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

// ----------------- WATCH PARTY REST API -----------------
app.post('/api/watchparty/create', (req, res) => {
  const { host_profile_id, guest_profile_id, item, session_id } = req.body || {};
  if (!host_profile_id || !item) {
    return res.status(400).json({ success: false, error: 'Parametri mancanti' });
  }

  const pData = getProfilesData();
  const profs = {};
  (pData.profiles || []).forEach(p => { profs[p.id] = p; });

  const hostProf = profs[host_profile_id] || { name: 'Host', avatar: 'preset:netflix-red' };
  const guestProf = guest_profile_id ? (profs[guest_profile_id] || { name: 'Ospite', avatar: 'preset:amber-crown' }) : null;

  const sessionId = (session_id && String(session_id).trim()) || `WP-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;
  const session = {
    session_id: sessionId,
    host_profile_id,
    host_name: hostProf.name,
    host_avatar: hostProf.avatar,
    guest_profile_id: guest_profile_id || null,
    guest_name: guestProf ? guestProf.name : 'Ospite',
    guest_avatar: guestProf ? guestProf.avatar : '',
    item,
    status: 'waiting',
    current_time: Number(item.currentTime || 0) || 0,
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

  res.json({ success: true, session_id: sessionId, session });
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

// ----------------- SOCKET.IO REAL-TIME HUB -----------------
io.on('connection', (socket) => {
  let currentRoomId = null;

  // 1. JOIN ROOM
  socket.on('join-room', (payload, callback) => {
    try {
      const rawRoomId = payload?.roomId || 'GLOBAL';
      const roomId = String(rawRoomId).trim().toUpperCase();
      const profile = payload?.profile || { id: socket.id, name: 'Utente', avatar: '' };
      const item = payload?.item || null;
      const streamUrl = payload?.streamUrl || '';
      const controlMode = payload?.controlMode || 'host-only';

      socket.join(`room:${roomId}`);
      currentRoomId = roomId;

      let room = activeSocketRooms.get(roomId);
      let isHost = false;

      if (!room) {
        isHost = true;
        room = {
          roomId,
          hostSocketId: socket.id,
          hostProfile: profile,
          controlMode,
          playing: false,
          currentTime: Number(payload?.currentTime) || 0,
          playbackRate: 1.0,
          updatedAt: Date.now(),
          item,
          streamUrl,
          members: new Map()
        };
        activeSocketRooms.set(roomId, room);
      } else {
        if (!room.hostSocketId || !room.members.has(room.hostSocketId)) {
          room.hostSocketId = socket.id;
          room.hostProfile = profile;
          isHost = true;
        } else {
          isHost = (room.hostSocketId === socket.id);
        }
        if (isHost) {
          if (item) room.item = item;
          if (streamUrl) room.streamUrl = streamUrl;
        }
      }

      room.members.set(socket.id, {
        socketId: socket.id,
        profile,
        isHost,
        ready: true,
        buffering: false,
        lastSeen: Date.now()
      });

      const state = getSocketRoomPublicState(room);

      socket.emit('room-state', state);
      socket.to(`room:${roomId}`).emit('user-joined', {
        user: {
          socketId: socket.id,
          profileId: profile.id,
          name: profile.name,
          avatar: profile.avatar,
          isHost
        },
        members: state.members
      });
      io.to(`room:${roomId}`).emit('members-update', { members: state.members });

      if (typeof callback === 'function') {
        callback({ success: true, room: state, isHost });
      }
    } catch (err) {
      console.error('[Socket.IO join-room error]', err);
      if (typeof callback === 'function') callback({ success: false, error: err.message });
    }
  });

  // 2. PLAYER ACTION (play, pause, seek)
  socket.on('player-action', (data) => {
    try {
      const roomId = String(data?.roomId || currentRoomId || '').trim().toUpperCase();
      const room = activeSocketRooms.get(roomId);
      if (!room) return;

      const isHost = (socket.id === room.hostSocketId);
      if (room.controlMode === 'host-only' && !isHost) {
        socket.emit('action-denied', { reason: 'Solo l’host può controllare la riproduzione' });
        return;
      }

      const action = data.action;
      const currentTime = Number(data.currentTime);
      const playbackRate = Number(data.playbackRate) || 1.0;

      if (typeof currentTime === 'number' && !isNaN(currentTime)) {
        room.currentTime = Math.max(0, currentTime);
      }
      if (action === 'play') room.playing = true;
      else if (action === 'pause') room.playing = false;
      room.playbackRate = playbackRate;
      room.updatedAt = Date.now();

      socket.to(`room:${roomId}`).emit('player-action', {
        action,
        currentTime: room.currentTime,
        playbackRate: room.playbackRate,
        serverTimestamp: Date.now(),
        by: isHost ? 'host' : 'guest'
      });
    } catch (err) {
      console.error('[Socket.IO player-action error]', err);
    }
  });

  // 3. PERIODIC SYNC (Host -> Server -> Guests ogni 2.5s)
  socket.on('sync', (data) => {
    try {
      const roomId = String(data?.roomId || currentRoomId || '').trim().toUpperCase();
      const room = activeSocketRooms.get(roomId);
      if (!room) return;

      const isHost = (socket.id === room.hostSocketId);
      if (room.controlMode === 'host-only' && !isHost) return;

      const currentTime = Number(data.currentTime);
      const playing = Boolean(data.playing);
      const playbackRate = Number(data.playbackRate) || 1.0;

      if (!isNaN(currentTime)) room.currentTime = Math.max(0, currentTime);
      room.playing = playing;
      room.playbackRate = playbackRate;
      room.updatedAt = Date.now();

      if (data.item) room.item = data.item;
      if (data.streamUrl) room.streamUrl = data.streamUrl;

      socket.to(`room:${roomId}`).emit('sync', {
        currentTime: room.currentTime,
        playing: room.playing,
        playbackRate: room.playbackRate,
        serverTimestamp: Date.now(),
        item: room.item,
        streamUrl: room.streamUrl
      });
    } catch (err) {
      console.error('[Socket.IO sync error]', err);
    }
  });

  // 4. CAMBIO EPISODIO
  socket.on('change-episode', (data) => {
    try {
      const roomId = String(data?.roomId || currentRoomId || '').trim().toUpperCase();
      const room = activeSocketRooms.get(roomId);
      if (!room) return;

      const isHost = (socket.id === room.hostSocketId);
      if (room.controlMode === 'host-only' && !isHost) {
        socket.emit('action-denied', { reason: 'Solo l’host può cambiare episodio' });
        return;
      }

      room.item = data.item || room.item;
      room.streamUrl = data.streamUrl || '';
      room.currentTime = 0;
      room.playing = true;
      room.updatedAt = Date.now();

      socket.to(`room:${roomId}`).emit('change-episode', {
        item: room.item,
        streamUrl: room.streamUrl,
        currentTime: 0,
        serverTimestamp: Date.now()
      });
    } catch (err) {
      console.error('[Socket.IO change-episode error]', err);
    }
  });

  // 5. MODALITÀ CONTROLLI
  socket.on('set-control-mode', (data) => {
    try {
      const roomId = String(data?.roomId || currentRoomId || '').trim().toUpperCase();
      const room = activeSocketRooms.get(roomId);
      if (!room || socket.id !== room.hostSocketId) return;

      const mode = (data.controlMode === 'all') ? 'all' : 'host-only';
      room.controlMode = mode;
      io.to(`room:${roomId}`).emit('control-mode-changed', { controlMode: mode });
    } catch (err) {}
  });

  // 6. STATO MEMBRO
  socket.on('member-status', (data) => {
    try {
      const roomId = String(data?.roomId || currentRoomId || '').trim().toUpperCase();
      const room = activeSocketRooms.get(roomId);
      if (!room) return;
      const member = room.members.get(socket.id);
      if (member) {
        if (typeof data.ready === 'boolean') member.ready = data.ready;
        if (typeof data.buffering === 'boolean') member.buffering = data.buffering;
        member.lastSeen = Date.now();
        socket.to(`room:${roomId}`).emit('member-status-update', {
          socketId: socket.id,
          ready: member.ready,
          buffering: member.buffering
        });
      }
    } catch (err) {}
  });

  // 7. LEAVE ROOM & DISCONNECT
  function handleLeave() {
    if (!currentRoomId) return;
    const roomId = currentRoomId;
    currentRoomId = null;

    const room = activeSocketRooms.get(roomId);
    if (!room) return;

    const member = room.members.get(socket.id);
    const wasHost = (socket.id === room.hostSocketId);
    room.members.delete(socket.id);
    socket.leave(`room:${roomId}`);

    if (room.members.size === 0) {
      setTimeout(() => {
        const check = activeSocketRooms.get(roomId);
        if (check && check.members.size === 0) {
          activeSocketRooms.delete(roomId);
        }
      }, 60000);
    } else {
      if (wasHost) {
        const nextSocketId = room.members.keys().next().value;
        const nextMember = room.members.get(nextSocketId);
        if (nextMember) {
          nextMember.isHost = true;
          room.hostSocketId = nextSocketId;
          room.hostProfile = nextMember.profile;
          io.to(`room:${roomId}`).emit('host-changed', {
            newHost: { socketId: nextSocketId, profile: nextMember.profile }
          });
        }
      }
      const state = getSocketRoomPublicState(room);
      io.to(`room:${roomId}`).emit('user-left', {
        socketId: socket.id,
        name: member?.profile?.name || 'Un partecipante',
        members: state.members
      });
      io.to(`room:${roomId}`).emit('members-update', { members: state.members });
    }
  }

  socket.on('leave-room', handleLeave);
  socket.on('disconnect', handleLeave);
});

server.listen(PORT, '0.0.0.0', () => {
  console.log('=============================================================');
  console.log(` 🚀 WATCHPARTY HUB OPERATIVO CON SOCKET.IO`);
  console.log(` • Porta di ascolto: ${PORT}`);
  console.log(` • Health check    : http://0.0.0.0:${PORT}/health`);
  console.log('=============================================================');
});

module.exports = { app, server, io, activeSocketRooms };
