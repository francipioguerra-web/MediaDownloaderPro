/* Confirmed playback over the hub's existing action field. Both peers must use
 * this protocol; readiness from an earlier command never releases a later one. */
(function (root) {
  class WatchPartySync {
    constructor(options) {
      Object.assign(this, options);
      this.serial = Promise.resolve();
      this.sequence = 0;
      this.latest = 0;
      this.pending = null;
      this.command = null;
      this.closed = false;
      this.holding = false;
      this.desiredPaused = true;
      this.applying = false;
      this.lastWrite = 0;
      this.lastAck = 0;
      this.clockSample = 0;
      this.lastClockSample = 0;
      this.positionedId = null;
      this.acknowledgedId = null;
      this.bufferSince = null;
      this.joinToken = `${Date.now()}-${Math.random()}`;
    }
    close() { this.closed = true; this.video.playbackRate = 1; }
    write(message) {
      this.queued = (this.queued || 0) + 1;
      this.serial = this.serial.catch(() => {}).then(async () => {
        if (this.closed || (message.kind === 'command' && message.id !== this.sequence) ||
            (message.kind === 'ack' && message.id !== this.latest) ||
            (message.kind === 'intent' && message.token !== this.intent?.token)) return;
        await this.send({ action: 'wp4:' + JSON.stringify(message) });
        this.lastWrite = Date.now();
      }).finally(() => {
        this.queued--;
        // A newer click can replace a queued write before it is sent.
        // Flush that latest intent now rather than waiting for the retry timer.
        if (!this.queued && !this.closed &&
            ((message.kind === 'command' && this.pending && this.pending.id !== message.id) ||
             (message.kind === 'intent' && this.intent && this.intent.token !== message.token))) {
          this.lastWrite = 0;
          this.tick();
        }
      });
      return this.serial;
    }
    controlTime() {
      return this.intent?.time ?? this.pending?.time ?? this.video.currentTime;
    }
    toggle() {
      this.request(!this.desiredPaused, this.controlTime(), this.media());
    }
    seek(time) {
      const duration = Number(this.video.duration);
      const target = Math.max(0, Number(time) || 0);
      this.request(this.desiredPaused, Number.isFinite(duration) && duration > 0 ? Math.min(duration, target) : target, this.media());
    }
    skip(seconds) { this.seek(this.controlTime() + seconds); }
    request(paused, time, media) {
      if (this.closed) return;
      if (this.role === 'guest') {
        this.desiredPaused = paused;
        this.intent = {kind: 'intent', token: `${Date.now()}-${++this.sequence}`, paused,
          time: Math.max(0, Number(time) || 0), media};
        // Hold local playback until the host returns this exact intent.
        this.skipPause = !this.video.paused;
        this.video.pause();
        this.applying = true;
        this.write(this.intent).catch(this.error);
        return;
      }
      this.desiredPaused = paused;
      this.bufferSince = null;
      this.skipPlay = false;
      this.skipSeek = undefined;
      this.video.playbackRate = 1;
      this.holding = true;
      this.skipPause = !this.video.paused;
      this.video.pause();
      this.pending = { kind: 'command', id: ++this.sequence, paused,
        time: Math.max(0, Number(time) || 0), media, intent: this.lastIntent };
      if (this.video.readyState >= 1 && Math.abs(this.video.currentTime - this.pending.time) > 0.15) {
        this.skipSeek = this.pending.time;
        this.video.currentTime = this.pending.time;
      }
      this.wait(true);
      this.lastWrite = 0;
      this.tick();
    }
    async receive(session) {
      if (this.closed) return;
      let msg;
      try { msg = JSON.parse(String(session.last_action).replace(/^wp4:/, '')); }
      catch (_) { return; }
      if (!msg || typeof msg !== 'object') return;
      if (this.role === 'host') {
        if (msg.kind === 'join') {
          if (this.loading) return;
          if (this.pending) {
            this.lastJoin = msg.token;
            // The hub has one action slot: a join can overwrite our command.
            // Reply immediately instead of letting both retry timers collide.
            if (!this.queued) await this.write(this.pending);
          } else if (msg.token !== this.lastJoin) {
            this.lastJoin = msg.token;
            this.request(this.desiredPaused, this.video.currentTime, this.media());
          }
          return;
        }
        if (msg.kind === 'intent') {
          if (msg.token === this.lastIntent) {
            if (this.pending?.intent === msg.token && !this.queued) await this.write(this.pending);
            return;
          }
          this.lastIntent = msg.token;
          if (msg.media && msg.media.key !== this.media().key) {
            this.desiredPaused = msg.paused;
            this.load(msg.media, msg.time);
          } else this.request(msg.paused, msg.time, this.media());
          return;
        }
        if (msg.kind === 'ack' && this.pending && msg.id === this.pending.id) {
          const command = this.pending;
          this.pending = null;
          this.holding = false;
          this.wait(false);
          // Use the guest's confirmed playback position, including transit time.
          const transit = Math.max(0, Math.min(1, (Date.now() - Number(session.last_sync)) / 1000)) || 0;
          const target = msg.time + (command.paused ? 0 : transit);
          if (Math.abs(this.video.currentTime - target) > 0.15) {
            this.skipSeek = target;
            this.video.currentTime = target;
          }
          if (!command.paused) {
            this.skipPlay = true;
            this.video.play().catch(this.error);
          }
          else this.video.pause();
        } else if (msg.kind === 'buffer' && msg.id === this.sequence && !this.pending && !this.desiredPaused) {
          this.request(false, msg.time, this.media());
        }
        return;
      }
      if (this.intent) {
        if (msg.kind !== 'command' || msg.intent !== this.intent.token) return;
        this.intent = null;
      }
      if (msg.kind === 'clock' && msg.id === this.latest) {
        // Polls return the same snapshot many times. Apply each clock sample
        // once, using only gentle rate correction; clocks must never seek.
        const sample = Number(msg.sample || session.last_sync) || 0;
        if (sample <= this.lastClockSample) return;
        this.lastClockSample = sample;
        if (!this.desiredPaused && !this.loading && !this.video.seeking && this.video.readyState >= 3) {
          const age = Math.max(0, Math.min(1, (Date.now() - Number(session.last_sync)) / 1000)) || 0;
          const drift = Number(msg.time) + age - this.video.currentTime;
          this.video.playbackRate = Math.abs(drift) < 0.25 ? 1 : (drift > 0 ? 1.03 : 0.97);
          this.rateAdjustedAt = Date.now();
        }
        return;
      }
      if (msg.kind !== 'command' || msg.id < this.latest) return;
      if (msg.id === this.latest) { this.confirm(true); return; }
      this.latest = msg.id;
      this.bufferPending = null;
      this.positionedId = null;
      this.acknowledgedId = null;
      this.bufferSince = null;
      this.video.playbackRate = 1;
      this.playing = false;
      this.command = msg;
      this.lastAck = 0;
      this.playbackBlocked = false;
      this.desiredPaused = msg.paused;
      this.skipPause = !this.video.paused;
      this.video.pause();
      this.applying = true;
      if (msg.media && this.mediaKey !== msg.media.key) {
        this.mediaKey = msg.media.key;
        this.load(msg.media, msg.time);
      } else {
        this.positionGuest();
      }
    }
    positionGuest() {
      if (!this.command || this.closed || this.loading || this.video.readyState < 1) return;
      const cmd = this.command;
      if (this.positionedId !== cmd.id) {
        this.positionedId = cmd.id;
        if (Math.abs(this.video.currentTime - cmd.time) > 0.15) { this.skipSeek = cmd.time; this.video.currentTime = cmd.time; }
      }
      if (!cmd.paused && this.video.paused && !this.playbackBlocked && this.playAttempt?.id !== cmd.id) {
        this.skipPlay = true;
        const attempt = this.playAttempt = {id: cmd.id};
        Promise.resolve(this.video.play()).catch(err => {
          if (this.command !== cmd || this.closed) return;
          this.skipPlay = false;
          if (err?.name === 'NotAllowedError') this.playbackBlocked = true;
          // Seeking can interrupt play(). Retry after seek/buffer recovery.
          if (err?.name !== 'AbortError') this.error(err);
        }).finally(() => { if (this.playAttempt === attempt) this.playAttempt = null; });
      }
      this.confirm();
    }
    confirm(retry = false) {
      if (this.role !== 'guest' || !this.command || this.closed) return;
      const v = this.video, cmd = this.command;
      if (this.positionedId !== cmd.id || (!retry && this.acknowledgedId === cmd.id)) return;
      if (v.seeking || v.readyState < (cmd.paused ? 1 : 3) || this.loading) return;
      if (cmd.paused ? !v.paused : (v.paused || !this.playing)) return;
      if (cmd.paused && Math.abs(v.currentTime - cmd.time) > 0.2) return;
      if (Date.now() - this.lastAck < 700) return;
      this.lastAck = Date.now();
      this.acknowledgedId = cmd.id;
      this.applying = false;
      this.write({ kind: 'ack', id: cmd.id, time: v.currentTime }).catch(err => {
        if (this.command === cmd) this.acknowledgedId = null;
        this.error(err);
      });
    }
    event(type) {
      if (this.closed) return;
      const v = this.video;
      if (this.role === 'guest') {
        if (type === 'play' && this.skipPlay) { this.skipPlay = false; return; }
        if (type === 'pause' && this.skipPause) { this.skipPause = false; return; }
        if (type === 'seeked' && this.skipSeek !== undefined) {
          const expected = this.skipSeek; this.skipSeek = undefined;
          if (Math.abs(v.currentTime - expected) < .3) { this.confirm(); return; }
        }
        if (!this.loading && !this.applying && ['play', 'pause', 'seeked'].includes(type)) {
          this.request(type === 'seeked' ? this.desiredPaused : v.paused, v.currentTime, this.media());
          return;
        }
        if (type === 'playing') { this.playing = true; this.bufferSince = null; this.confirm(); }
        if (type === 'waiting') {
          this.playing = false;
          if (!v.seeking && !this.loading && this.acknowledgedId === this.latest && !this.desiredPaused) {
            this.bufferSince ??= Date.now();
          }
        }
        if (type === 'canplay') this.bufferSince = null;
        if (type === 'canplay' && !this.loading && !this.lastAck) this.positionGuest();
        if (type === 'seeked' || type === 'canplay' || type === 'pause') this.confirm();
        return;
      }
      if (this.loading) return;
      if (type === 'seeked' && this.skipSeek !== undefined) {
        const expected = this.skipSeek;
        this.skipSeek = undefined;
        if (Math.abs(v.currentTime - expected) < 0.3) return;
      }
      if (type === 'play') {
        if (this.skipPlay) { this.skipPlay = false; return; }
        this.request(false, v.currentTime, this.media());
      } else if (type === 'pause' && !this.holding && !this.applying && !this.desiredPaused && v.paused) {
        this.request(true, v.currentTime, this.media());
      } else if (type === 'seeked' && !this.applying) {
        if (this.pending && Math.abs(v.currentTime - this.pending.time) < 0.3) return;
        this.request(this.desiredPaused, v.currentTime, this.media());
      } else if (type === 'waiting' && !this.holding && !this.desiredPaused && !v.seeking && this.skipSeek === undefined) {
        this.bufferSince ??= Date.now();
      } else if (type === 'canplay') {
        this.bufferSince = null;
        this.tick();
      } else if (type === 'playing') {
        this.bufferSince = null;
        this.applying = false;
        if (this.holding) v.pause();
      }
    }
    tick() {
      if (this.closed) return;
      if (this.role === 'guest' && !this.command && !this.intent && !this.queued && Date.now() - this.lastWrite > 1200) {
        this.write({kind: 'join', token: this.joinToken}).catch(this.error);
      }
      if (this.role === 'guest' && this.bufferPending && !this.queued && Date.now() - this.lastWrite > 800) {
        this.write(this.bufferPending).catch(this.error);
      }
      if (this.role === 'guest' && this.intent && !this.queued && Date.now() - this.lastWrite > 800) {
        this.write(this.intent).catch(this.error);
      }
      if (this.role === 'guest' && this.command && !this.intent && !this.loading &&
          this.acknowledgedId !== this.command.id) this.positionGuest();
      if (this.rateAdjustedAt && Date.now() - this.rateAdjustedAt > 5000) this.video.playbackRate = 1;
      if (this.bufferSince !== null && Date.now() - this.bufferSince >= 900 && !this.video.seeking && this.video.readyState < 3) {
        this.bufferSince = null;
        if (this.role === 'host') this.request(false, this.video.currentTime, this.media());
        else {
          this.bufferPending = {kind: 'buffer', id: this.latest, time: this.video.currentTime};
          this.write(this.bufferPending).catch(this.error);
        }
      }
      if (this.closed || this.loading || this.queued || this.role !== 'host') return;
      // Dispatch the target before waiting for local seek/buffer readiness:
      // otherwise a paused HLS seek can prevent the guest receiving it at all.
      if (this.pending && this.video.readyState < 1) return;
      if (this.pending && Date.now() - this.lastWrite > 1200) {
        this.write(this.pending).catch(this.error);
      } else if (!this.pending && !this.desiredPaused && !this.video.seeking && this.video.readyState >= 3 && Date.now() - this.lastWrite > 2000) {
        this.write({kind: 'clock', id: this.sequence, sample: ++this.clockSample, time: this.video.currentTime}).catch(this.error);
      }
    }
  }
  root.WatchPartySync = WatchPartySync;
})(typeof module === 'object' ? module.exports : window);
