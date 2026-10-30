(function (root) {
  class ScrollDock {
    constructor({nav, position = 0, schedule = (fn, ms) => setTimeout(fn, ms), cancel = id => clearTimeout(id)}) {
      this.nav = nav; this.lastY = position; this.distance = 0; this.direction = 0;
      this.schedule = schedule; this.cancel = cancel; this.timer = null;
    }
    expand() { this.nav.classList.remove('collapsed-dot'); }
    scroll(y) {
      const delta = y - this.lastY; this.lastY = y;
      if (!delta) return;
      const direction = Math.sign(delta);
      this.distance = direction === this.direction ? this.distance + Math.abs(delta) : Math.abs(delta);
      this.direction = direction;
      if (direction < 0 || y <= 40) this.expand();
      else if (this.distance >= 8 && y > 70 && !this.nav.querySelector(':focus-visible, .bottom-profile-popup:not(.hidden)')) {
        this.nav.classList.add('collapsed-dot');
      }
      this.cancel(this.timer);
      this.timer = this.schedule(() => { this.expand(); this.distance = 0; }, 320);
    }
  }
  root.ScrollDock = ScrollDock;
})(typeof module === 'object' ? module.exports : window);
