/* Preserve the frame, playback position and user pause state during HLS recovery. */
(function (root) {
  class PlayerContinuity {
    constructor(video, hls) {
      this.video = video; this.hls = hls; this.position = Number(video.currentTime) || 0;
      this.paused = video.paused; this.pending = null; this.stopped = false; this.deferred = null; this.listeners = [];
      const listen = (event, handler) => { video.addEventListener(event, handler); this.listeners.push([event, handler]); };
      const remember = () => { if (!this.pending && Number.isFinite(video.currentTime)) this.position = video.currentTime; };
      listen('timeupdate', remember); listen('seeked', () => { if (this.pending) this.restore(); else remember(); });
      listen('pause', () => {
        if (this.pending || video.ended) return;
        remember(); this.paused = true;
        if (video.readyState >= 1) { hls.stopLoad(); this.stopped = true; }
      });
      listen('play', () => {
        if (this.pending) return;
        if (this.resumeDeferred()) return;
        this.paused = false;
        if (this.stopped) { this.stopped = false; hls.startLoad(video.currentTime || this.position); }
      });
      listen('loadedmetadata', () => this.restore());
      listen('canplay', () => this.restore());
    }
    defer(action) {
      this.deferred = action; this.hls.stopLoad(); this.stopped = true;
    }
    resumeDeferred() {
      if (!this.deferred) return false;
      const action = this.deferred; this.deferred = null; this.paused = false;
      this.recover(action); this.hls.startLoad(this.position);
      return true;
    }
    recover(action, retry = false) {
      if (this.pending && !retry) return false;
      // A failed replacement may leave the element at zero. Keep the original
      // saved position and pause intent when retrying that replacement.
      this.pending ||= {time: Number(this.video.currentTime) > 0 ? this.video.currentTime : this.position, paused: this.paused};
      try { action(this.pending.time); }
      catch (error) { this.pending = null; throw error; }
      return true;
    }
    restore() {
      if (!this.pending || this.video.readyState < 1) return;
      const saved = this.pending;
      if (Math.abs(this.video.currentTime - saved.time) > .25) this.video.currentTime = saved.time;
      this.position = saved.time; this.paused = saved.paused; this.pending = null;
      if (saved.paused) {
        this.video.pause(); this.hls.stopLoad(); this.stopped = true;
      } else {
        this.stopped = false;
        this.video.play().catch(() => {});
      }
    }
    destroy() {
      this.listeners.forEach(([event, handler]) => this.video.removeEventListener(event, handler));
      this.listeners = []; this.pending = null; this.deferred = null;
    }
  }
  root.PlayerContinuity = PlayerContinuity;
})(typeof module === 'object' ? module.exports : window);
