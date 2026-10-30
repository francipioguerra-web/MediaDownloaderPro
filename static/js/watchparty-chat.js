(function (root) {
  class WatchPartyChat {
    constructor(player) {
      this.player = player;
      this.button = document.createElement('button');
      this.button.id = 'wp-chat-toggle';
      this.button.type = 'button';
      this.button.hidden = true;
      this.button.setAttribute('aria-label', 'Apri chat WatchParty');
      this.button.setAttribute('aria-expanded', 'false');
      this.button.setAttribute('aria-controls', 'wp-chat-panel');
      this.button.innerHTML = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z"/><path d="M7 9h10M7 13h7"/></svg><span class="wp-chat-unread" hidden></span>';
      this.panel = document.createElement('aside');
      this.panel.id = 'wp-chat-panel';
      this.panel.hidden = true;
      this.panel.setAttribute('aria-label', 'Chat WatchParty');
      this.panel.innerHTML = '<header><div><strong>Chat WatchParty</strong><small>Due parole, insieme al film.</small></div><button type="button" aria-label="Chiudi chat">×</button></header><div class="wp-chat-messages" role="log" aria-live="polite" aria-relevant="additions"></div><p class="wp-chat-status" role="status"></p><form><label class="wp-chat-label" for="wp-chat-input">Messaggio</label><div class="wp-chat-compose"><input id="wp-chat-input" autocomplete="off" maxlength="1000" placeholder="Scrivi un messaggio…"><button type="submit" aria-label="Invia messaggio">↑</button></div></form>';
      player.append(this.button, this.panel);
      this.list = this.panel.querySelector('.wp-chat-messages');
      this.status = this.panel.querySelector('.wp-chat-status');
      this.input = this.panel.querySelector('input');
      this.submit = this.panel.querySelector('[type="submit"]');
      this.badge = this.button.querySelector('.wp-chat-unread');
      this.button.onclick = () => this.setOpen(!this.open);
      this.panel.querySelector('header button').onclick = () => { this.setOpen(false); this.button.focus(); };
      // Chat typing and taps must never reach the player's shortcuts/gestures.
      for (const type of ['keydown', 'keyup', 'click', 'dblclick', 'pointerdown', 'mousedown', 'touchstart', 'touchend']) {
        this.panel.addEventListener(type, e => {
          if (type === 'keydown' && e.key === 'Escape') { e.preventDefault(); this.setOpen(false); this.button.focus(); }
          e.stopPropagation();
        });
        this.button.addEventListener(type, e => e.stopPropagation());
      }
      this.panel.querySelector('form').onsubmit = e => { e.preventDefault(); this.send(); };
    }
    setOpen(open) {
      this.open = open;
      this.panel.hidden = !open;
      this.button.setAttribute('aria-expanded', String(open));
      this.button.setAttribute('aria-label', open ? 'Chiudi chat WatchParty' : 'Apri chat WatchParty');
      if (open) {
        this.player.classList.add('wp-chat-open');
        this.unread = 0; this.updateBadge();
        this.list.scrollTop = this.list.scrollHeight;
        this.input.focus({preventScroll:true});
      } else {
        this.player.classList.remove('wp-chat-open');
      }
    }
    start(session, role, profile) {
      this.stop();
      this.session = session.session_id;
      this.role = role;
      this.profile = String(profile.id);
      this.cursor = 0; this.unread = 0; this.seen = new Set();
      this.list.replaceChildren();
      this.empty = document.createElement('p');
      this.empty.className = 'wp-chat-empty';
      this.empty.textContent = 'La serata comincia qui. Saluta chi guarda con te.';
      this.list.appendChild(this.empty);
      this.status.textContent = 'Connessione alla chat…';
      this.button.hidden = false;
      this.updateBadge();
      const generation = this.generation;
      const poll = async () => {
        if (generation !== this.generation) return;
        try {
          const data = await this.request('GET');
          if (generation !== this.generation) return;
          for (const message of data.messages) this.render(message, !this.loaded);
          this.cursor = Math.max(this.cursor, ...data.messages.map(message => message.id));
          this.loaded = true;
          if (!this.sending) this.status.textContent = '';
        } catch (_) {
          if (generation === this.generation) this.status.textContent = 'Chat non raggiungibile. Riprovo…';
        } finally {
          if (generation === this.generation) this.timer = setTimeout(poll, 1200);
        }
      };
      poll();
    }
    stop() {
      this.generation = (this.generation || 0) + 1;
      clearTimeout(this.timer);
      this.setOpen(false);
      this.session = null; this.loaded = false; this.pending = null; this.sending = false;
      this.submit.disabled = false;
      this.button.hidden = true;
      this.input.value = '';
      this.status.textContent = '';
      this.list.replaceChildren();
    }
    async request(method, extra = {}) {
      const params = {session_id:this.session, profile_id:this.profile, role:this.role, after:this.cursor, ...extra};
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        // Same app origin: localhost and its ngrok URL share this chat backend.
        const url = '/api/watchparty/chat' + (method === 'GET' ? '?' + new URLSearchParams(params) : '');
        const response = await fetch(url, {method, cache:'no-store', signal:controller.signal,
          ...(method === 'POST' ? {headers:{'Content-Type':'application/json'}, body:JSON.stringify(params)} : {})});
        const data = await response.json();
        if (!response.ok || !data.success) throw Error(data.error || 'Invio non riuscito');
        return data;
      } finally { clearTimeout(timeout); }
    }
    async send() {
      const text = this.input.value.trim();
      if (!text || this.sending || !this.session) return;
      const generation = this.generation;
      this.sending = true; this.submit.disabled = true;
      this.status.textContent = 'Invio…';
      if (!this.pending || this.pending.text !== text) this.pending = {text, client_id:crypto.randomUUID()};
      try {
        const data = await this.request('POST', this.pending);
        if (generation !== this.generation) return;
        this.render(data.message);
        if (this.input.value.trim() === text) this.input.value = '';
        this.pending = null; this.status.textContent = '';
      } catch (err) {
        if (generation === this.generation) this.status.textContent = `${err.message}. Premi Invia per riprovare.`;
      } finally {
        if (generation === this.generation) { this.sending = false; this.submit.disabled = false; }
      }
    }
    render(message, history = false) {
      if (this.seen.has(message.id)) return;
      this.seen.add(message.id);
      // Advance cursor only on polled batches; a POST may overtake unread messages.
      const nearBottom = this.list.scrollHeight - this.list.scrollTop - this.list.clientHeight < 80;
      this.empty?.remove();
      const own = String(message.profile_id) === this.profile;
      const bubble = document.createElement('article');
      bubble.className = 'wp-chat-message' + (own ? ' own' : '');
      bubble.dataset.id = message.id;
      const meta = document.createElement('div');
      meta.className = 'wp-chat-meta';
      meta.textContent = `${own ? 'Tu' : message.name} · ${new Date(message.created_at).toLocaleTimeString('it-IT', {hour:'2-digit',minute:'2-digit'})}`;
      const body = document.createElement('p'); body.textContent = message.text;
      bubble.append(meta, body);
      const next = [...this.list.children].find(el => Number(el.dataset.id) > message.id);
      this.list.insertBefore(bubble, next || null);
      while (this.list.children.length > 200) this.list.firstChild.remove();
      if (this.open && (nearBottom || own)) this.list.scrollTop = this.list.scrollHeight;
      if (!this.open && !own && !history) { this.unread++; this.updateBadge(); }
    }
    updateBadge() {
      this.badge.hidden = !this.unread;
      this.badge.textContent = this.unread > 9 ? '9+' : this.unread || '';
    }
  }
  root.WatchPartyChat = WatchPartyChat;
})(window);
