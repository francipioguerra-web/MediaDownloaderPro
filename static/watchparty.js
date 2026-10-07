/**
 * MediaDownloaderPro / StreamingCommunity — WatchParty Real-Time Client Module
 *
 * Architettura Real-Time basata su Socket.IO con:
 * - Room ID autorevoli (es. "ABC123" o codice stanza)
 * - Link pubblico condivisibile (es. https://.../?room=ABC123 o /watch/ABC123)
 * - Ruoli Host (👑) e Ospite (👤) con modalità controlli ("Solo host" vs "Tutti")
 * - Correzione drift a 3 livelli (seek > 1.5s, playbackRate 1.04/0.96 per 0.15-1.5s, rate 1.0 in sync)
 * - Azioni istantanee (play/pause/seek) con 0 latenza tramite WebSocket
 * - Sincronizzazione periodica leggera (ogni 2.5s)
 * - Cambio episodio sincronizzato automatico
 * - Fallback trasparente su server Render Cloud / Localhost
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.WatchParty = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const RENDER_HUB_DEFAULT = 'https://mediadownloaderpro-3q69.onrender.com';
  const LOCAL_NODE_PORT = 5556;

  class WatchPartyManager {
    constructor() {
      this.socket = null;
      this.connected = false;
      this.roomId = null;
      this.isHost = false;
      this.controlMode = 'host-only'; // 'host-only' | 'all'
      this.item = null;
      this.streamUrl = '';
      this.members = [];
      this.video = null;

      this.drift = 0;
      this.driftState = 'synced'; // 'synced' | 'adjusting' | 'seek'

      this.heartbeatTimer = null;
      this.isRemoteExecuting = false;
      this.lastSentActionAt = 0;

      // Event listeners registrati
      this.listeners = {
        'room-state': [],
        'player-action': [],
        'change-episode': [],
        'members-update': [],
        'control-mode-changed': [],
        'drift-update': [],
        'disconnected': []
      };
    }

    // Determina l'URL del server Hub Socket.IO
    getHubUrl() {
      const saved = localStorage.getItem('sc_watchparty_hub_url');
      if (saved && saved.trim()) {
        const clean = saved.trim().replace(/\/+$/, '');
        if (clean.includes('trycloudflare.com') || clean.includes('loca.lt')) {
          localStorage.removeItem('sc_watchparty_hub_url');
        } else {
          return clean;
        }
      }

      // Se ci troviamo già su onrender.com, usa l'origine corrente
      if (typeof window !== 'undefined') {
        const host = window.location.hostname;
        if (host.includes('onrender.com')) {
          return window.location.origin;
        }
        // Se siamo su localhost
        if (host === 'localhost' || host === '127.0.0.1') {
          // Se la porta corrente è 5555, il server Python o Node può avere Socket.IO
          return window.location.origin;
        }
      }
      return RENDER_HUB_DEFAULT;
    }

    // Inizializza e collega il video player
    bindVideo(videoElement) {
      this.video = videoElement;
      if (!this.video) return;

      // Intercetta eventi video locali per inviarli al server
      const onPlay = () => {
        if (this.isRemoteExecuting || !this.roomId) return;
        if (this.canControl()) {
          this.sendAction('play', this.video.currentTime);
        }
      };

      const onPause = () => {
        if (this.isRemoteExecuting || !this.roomId) return;
        if (this.canControl()) {
          this.sendAction('pause', this.video.currentTime);
        }
      };

      const onSeeked = () => {
        if (this.isRemoteExecuting || !this.roomId) return;
        if (this.canControl()) {
          this.sendAction('seek', this.video.currentTime);
        }
      };

      const onWaiting = () => {
        if (this.roomId && !this.isHost) {
          this.sendStatus({ buffering: true, ready: false });
        }
      };

      const onPlaying = () => {
        if (this.roomId && !this.isHost) {
          this.sendStatus({ buffering: false, ready: true });
        }
      };

      this.video.addEventListener('play', onPlay);
      this.video.addEventListener('pause', onPause);
      this.video.addEventListener('seeked', onSeeked);
      this.video.addEventListener('waiting', onWaiting);
      this.video.addEventListener('playing', onPlaying);
    }

    // Verifica se l'utente attuale ha il permesso di controllare il player
    canControl() {
      if (!this.roomId) return true;
      if (this.isHost) return true;
      return this.controlMode === 'all';
    }

    // Connessione a Socket.IO
    connect(customUrl) {
      return new Promise((resolve, reject) => {
        if (typeof window.io === 'undefined') {
          console.warn('[WatchParty] Socket.IO client library non caricata. Utilizzo fallback HTTP.');
          return resolve(false);
        }

        const hubUrl = customUrl || this.getHubUrl();
        console.log('[WatchParty] Connessione a Hub:', hubUrl);

        try {
          if (this.socket && this.socket.connected) {
            return resolve(true);
          }

          this.socket = window.io(hubUrl, {
            transports: ['websocket', 'polling'],
            timeout: 1500,
            reconnectionAttempts: 1,
            reconnectionDelay: 1000
          });

          this.socket.on('connect', () => {
            console.log('[WatchParty] Connesso a Hub Socket.IO (ID:', this.socket.id, ')');
            this.connected = true;
            resolve(true);
          });

          this.socket.on('connect_error', (err) => {
            console.warn('[WatchParty] Errore connessione Hub:', err.message);
            // Se fallisce il server locale, prova Render Hub se non era già selezionato
            if (hubUrl !== RENDER_HUB_DEFAULT && !hubUrl.includes('onrender.com')) {
              console.log('[WatchParty] Tentativo fallback rapido su Render Hub Cloud...');
              this.socket.disconnect();
              this.connect(RENDER_HUB_DEFAULT).then(resolve).catch(() => resolve(false));
            } else {
              resolve(false);
            }
          });

          this.socket.on('disconnect', (reason) => {
            console.log('[WatchParty] Disconnesso da Hub:', reason);
            this.connected = false;
            this.emitEvent('disconnected', { reason });
          });

          // Registrazione eventi Socket.IO del protocollo WatchParty
          this.socket.on('room-state', (data) => this.handleRoomState(data));
          this.socket.on('player-action', (data) => this.handlePlayerAction(data));
          this.socket.on('sync', (data) => this.handlePeriodicSync(data));
          this.socket.on('change-episode', (data) => this.handleChangeEpisode(data));
          this.socket.on('members-update', (data) => this.handleMembersUpdate(data));
          this.socket.on('control-mode-changed', (data) => this.handleControlModeChanged(data));
          this.socket.on('action-denied', (data) => {
            if (typeof window.showToast === 'function') window.showToast(data.reason || 'Azione non consentita');
          });
        } catch (e) {
          console.error('[WatchParty] Eccezione avvio socket:', e);
          resolve(false);
        }
      });
    }

    // Genera un Room ID casuale breve (es. ABC123)
    generateRoomId() {
      const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
      let id = '';
      for (let i = 0; i < 6; i++) {
        id += chars.charAt(Math.floor(Math.random() * chars.length));
      }
      return id;
    }

    // Genera il link pubblico condivisibile
    getShareableLink(roomId) {
      const rid = roomId || this.roomId;
      if (!rid) return '';
      const base = window.location.origin;
      return `${base}/?room=${encodeURIComponent(rid)}`;
    }

    // Crea o entra in una stanza come Host
    async createRoom({ roomId, profile, item, streamUrl, controlMode = 'host-only' }) {
      await this.connect();
      const rid = (roomId || this.generateRoomId()).trim().toUpperCase();
      this.roomId = rid;
      this.isHost = true;
      this.controlMode = controlMode;
      this.item = item;
      this.streamUrl = streamUrl;

      const payload = {
        roomId: rid,
        profile: profile || { name: 'Host', id: 'host' },
        item: item,
        streamUrl: streamUrl,
        controlMode: controlMode,
        currentTime: this.video ? Number(this.video.currentTime) || 0 : 0
      };

      if (this.socket && this.socket.connected) {
        this.socket.emit('join-room', payload, (res) => {
          if (res && res.room) this.handleRoomState(res.room);
        });
      }

      this.startHeartbeat();
      return rid;
    }

    // Entra in una stanza esistente come Ospite (o partecipante)
    async joinRoom(roomId, profile) {
      await this.connect();
      const rid = String(roomId).trim().toUpperCase();
      this.roomId = rid;

      const payload = {
        roomId: rid,
        profile: profile || { name: 'Ospite', id: 'guest' }
      };

      if (this.socket && this.socket.connected) {
        this.socket.emit('join-room', payload, (res) => {
          if (res && res.room) this.handleRoomState(res.room);
        });
      }
      return rid;
    }

    // Abbandona la stanza corrente
    leaveRoom() {
      this.stopHeartbeat();
      if (this.socket && this.socket.connected && this.roomId) {
        this.socket.emit('leave-room', { roomId: this.roomId });
      }
      this.roomId = null;
      this.isHost = false;
      this.members = [];
      this.item = null;
      this.streamUrl = '';
      if (this.video) {
        this.video.playbackRate = 1.0;
      }
    }

    // Invio di azione istantanea: play, pause, seek
    sendAction(action, currentTime) {
      if (!this.roomId) return;
      const now = Date.now();
      if (now - this.lastSentActionAt < 120 && action === 'seek') return; // Throttling seek
      this.lastSentActionAt = now;

      const time = (typeof currentTime === 'number') ? currentTime : (this.video ? this.video.currentTime : 0);
      const rate = this.video ? this.video.playbackRate : 1.0;

      if (this.socket && this.socket.connected) {
        this.socket.emit('player-action', {
          roomId: this.roomId,
          action,
          currentTime: time,
          playbackRate: rate
        });
      }
    }

    // Invio sync periodico (Host -> Server -> Ospiti ogni 2.5s)
    sendSync(force = false) {
      if (!this.roomId || !this.isHost || !this.video) return;
      const now = Date.now();
      if (!force && now - this.lastSentActionAt < 600) return;

      const payload = {
        roomId: this.roomId,
        currentTime: Number(this.video.currentTime) || 0,
        playing: !this.video.paused,
        playbackRate: Number(this.video.playbackRate) || 1.0,
        item: this.item,
        streamUrl: this.streamUrl
      };

      if (this.socket && this.socket.connected) {
        this.socket.emit('sync', payload);
      }
    }

    // Cambio episodio o titolo
    sendChangeEpisode(item, streamUrl) {
      if (!this.roomId || !this.canControl()) return;
      this.item = item;
      this.streamUrl = streamUrl;

      if (this.socket && this.socket.connected) {
        this.socket.emit('change-episode', {
          roomId: this.roomId,
          item,
          streamUrl
        });
      }
    }

    // Modifica modalità di controllo ('host-only' vs 'all')
    setControlMode(mode) {
      if (!this.roomId || !this.isHost) return;
      const cleanMode = (mode === 'all') ? 'all' : 'host-only';
      this.controlMode = cleanMode;

      if (this.socket && this.socket.connected) {
        this.socket.emit('set-control-mode', {
          roomId: this.roomId,
          controlMode: cleanMode
        });
      }
    }

    // Aggiornamento stato membro (buffering, ready)
    sendStatus({ ready, buffering }) {
      if (!this.roomId || !this.socket || !this.socket.connected) return;
      this.socket.emit('member-status', {
        roomId: this.roomId,
        ready,
        buffering
      });
    }

    // Avvia l'heartbeat periodico dell'host (ogni 2.5s)
    startHeartbeat() {
      this.stopHeartbeat();
      this.heartbeatTimer = setInterval(() => {
        this.sendSync(false);
      }, 2500);
    }

    stopHeartbeat() {
      if (this.heartbeatTimer) {
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = null;
      }
    }

    // =========================================================================
    // GESTORI EVENTI RICEVUTI DA SOCKET.IO
    // =========================================================================

    handleRoomState(state) {
      if (!state) return;
      console.log('[WatchParty] Stato stanza ricevuto:', state);
      this.roomId = state.roomId;
      this.controlMode = state.controlMode || 'host-only';
      this.members = state.members || [];
      if (state.item) this.item = state.item;
      if (state.streamUrl) this.streamUrl = state.streamUrl;

      const myId = this.socket ? this.socket.id : null;
      this.isHost = (state.hostId === myId);

      if (this.isHost) {
        this.startHeartbeat();
      } else {
        this.stopHeartbeat();
      }

      this.emitEvent('room-state', state);
      this.emitEvent('members-update', { members: this.members });
      this.emitEvent('control-mode-changed', { controlMode: this.controlMode });
    }

    handlePlayerAction(data) {
      if (!this.video) return;
      console.log('[WatchParty] Ricevuta azione remota:', data.action, 'a tempo:', data.currentTime);

      this.isRemoteExecuting = true;
      try {
        const action = data.action;
        const targetTime = Number(data.currentTime);

        if (action === 'play') {
          if (!isNaN(targetTime) && Math.abs(this.video.currentTime - targetTime) > 0.4) {
            this.video.currentTime = targetTime;
          }
          this.video.play().catch(e => console.warn('[WatchParty] Play bloccato da autoplay policy:', e));
        } else if (action === 'pause') {
          if (!isNaN(targetTime)) {
            this.video.currentTime = targetTime;
          }
          this.video.pause();
        } else if (action === 'seek') {
          if (!isNaN(targetTime)) {
            this.video.currentTime = targetTime;
          }
        }
      } finally {
        setTimeout(() => {
          this.isRemoteExecuting = false;
        }, 400);
      }

      this.emitEvent('player-action', data);
    }

    /**
     * ALGORITMO DI CORREZIONE DEL DRIFT A 3 LIVELLI
     *
     * 1) |drift| > 1.5s: Fuori sync evidente -> Seek immediato
     * 2) 0.15s < |drift| <= 1.5s: Micro-differenza -> Correzione invisibile della velocità (1.04x o 0.96x)
     * 3) |drift| <= 0.15s: Sincronizzati -> Velocità normale (1.0x)
     */
    handlePeriodicSync(data) {
      if (!this.video || this.isHost) return;

      const serverTimestamp = Number(data.serverTimestamp) || Date.now();
      const elapsed = (Date.now() - serverTimestamp) / 1000;
      const playing = Boolean(data.playing);
      const currentTime = Number(data.currentTime) || 0;

      const expectedTime = playing ? (currentTime + elapsed) : currentTime;
      const drift = expectedTime - this.video.currentTime;
      this.drift = drift;

      // Se l'host è in pausa, aggancia il video e metti in pausa
      if (!playing) {
        if (Math.abs(this.video.currentTime - expectedTime) > 0.5) {
          this.video.currentTime = expectedTime;
        }
        if (!this.video.paused) {
          this.isRemoteExecuting = true;
          this.video.pause();
          setTimeout(() => { this.isRemoteExecuting = false; }, 300);
        }
        this.video.playbackRate = 1.0;
        this.driftState = 'synced';
        this.emitEvent('drift-update', { drift: 0, state: 'synced' });
        return;
      }

      // Se l'host sta riproducendo ma il nostro video è in pausa
      if (playing && this.video.paused && this.video.readyState >= 2) {
        this.isRemoteExecuting = true;
        this.video.play().catch(() => {});
        setTimeout(() => { this.isRemoteExecuting = false; }, 300);
      }

      // Applicazione 3 livelli di correzione
      if (Math.abs(drift) > 1.5) {
        // Fuori sync evidente -> seek immediato
        this.video.currentTime = expectedTime;
        this.video.playbackRate = 1.0;
        this.driftState = 'seek';
      } else if (Math.abs(drift) > 0.15) {
        // Correzione invisibile della velocità di riproduzione
        this.video.playbackRate = drift > 0 ? 1.04 : 0.96;
        this.driftState = 'adjusting';
      } else {
        // Perfettamente sincronizzati
        this.video.playbackRate = 1.0;
        this.driftState = 'synced';
      }

      this.emitEvent('drift-update', { drift, state: this.driftState });
    }

    handleChangeEpisode(data) {
      console.log('[WatchParty] Ricevuto cambio episodio:', data);
      this.item = data.item;
      this.streamUrl = data.streamUrl;
      this.emitEvent('change-episode', data);
    }

    handleMembersUpdate(data) {
      this.members = data.members || [];
      this.emitEvent('members-update', data);
    }

    handleControlModeChanged(data) {
      this.controlMode = data.controlMode || 'host-only';
      this.emitEvent('control-mode-changed', data);
    }

    // =========================================================================
    // EVENT DISPATCHER SEMPLICE
    // =========================================================================

    on(event, callback) {
      if (this.listeners[event]) {
        this.listeners[event].push(callback);
      }
    }

    off(event, callback) {
      if (this.listeners[event]) {
        this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
      }
    }

    emitEvent(event, data) {
      if (this.listeners[event]) {
        this.listeners[event].forEach(cb => {
          try { cb(data); } catch (e) { console.error(`[WatchParty listener error on ${event}]`, e); }
        });
      }
    }
  }

  // Istanza singleton per comodità
  return new WatchPartyManager();
});
