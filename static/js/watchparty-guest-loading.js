/* Guest presentation only. Playback and synchronization remain owned by the player. */
(function (root) {
  class WatchPartyGuestLoading {
    constructor({player, video, canFinish, onStart}) {
      this.player = player;
      this.video = video;
      this.canFinish = canFinish;
      this.element = document.createElement('div');
      this.element.id = 'wp-guest-loading';
      this.element.hidden = true;
      this.element.setAttribute('role', 'status');
      this.element.setAttribute('aria-live', 'polite');
      this.element.innerHTML = '<div class="wp-guest-loading-content"><span class="wp-guest-loading-label">WATCHPARTY</span><div class="wp-guest-loading-dots" aria-hidden="true"><i></i><i></i><i></i></div><h2>Prepariamo la visione insieme</h2><p>Sincronizzazione con l’host in corso…</p><button type="button" hidden>Avvia il video</button></div>';
      this.button = this.element.querySelector('button');
      this.button.onclick = e => { e.stopPropagation(); onStart(); };
      player.appendChild(this.element);
      video.addEventListener('playing', () => {
        if (this.pending && !video.paused && video.readyState >= 3 && canFinish()) this.stop();
      });
    }
    start() {
      this.pending = true;
      this.button.hidden = true;
      this.element.hidden = false;
      this.player.classList.add('wp-guest-starting');
      this.player.classList.remove('hidden');
    }
    needsGesture() {
      if (!this.pending) return;
      this.button.hidden = false;
    }
    stop() {
      this.pending = false;
      this.element.hidden = true;
      this.button.hidden = true;
      this.player.classList.remove('wp-guest-starting');
    }
  }
  root.WatchPartyGuestLoading = WatchPartyGuestLoading;
})(typeof module === 'object' ? module.exports : window);
