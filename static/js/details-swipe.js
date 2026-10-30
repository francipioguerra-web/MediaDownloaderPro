/* Downward dismissal is armed only when a phone gesture starts at sheet top. */
(function (root) {
  root.installDetailsSwipe = function (overlay, close) {
    const sheet = overlay && overlay.querySelector('.modal-card');
    if (!sheet) return;
    let gesture = null;
    const reset = () => { gesture = null; sheet.style.translate = ''; };
    sheet.addEventListener('touchstart', event => {
      reset();
      if (!root.matchMedia('(max-width: 768px)').matches || event.touches.length !== 1 ||
          sheet.scrollTop > 1 || overlay.classList.contains('hidden') ||
          event.target.closest('button, a, input, select, textarea, video, iframe, [role="button"]')) return;
      // A nested vertical list must also be at its top before dismissal is armed.
      for (let node = event.target; node && node !== sheet; node = node.parentElement) {
        if (node.scrollTop > 1) return;
      }
      const touch = event.touches[0];
      gesture = {x: touch.clientX, y: touch.clientY, distance: 0, dragging: false};
    }, {passive: true});
    sheet.addEventListener('touchmove', event => {
      if (!gesture) return;
      if (event.touches.length !== 1 || sheet.scrollTop > 1) { reset(); return; }
      const dx = event.touches[0].clientX - gesture.x;
      const dy = event.touches[0].clientY - gesture.y;
      if (!gesture.dragging) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) < 8) return;
        if (dy <= 0 || Math.abs(dx) >= dy) { reset(); return; }
        gesture.dragging = true;
      }
      if (event.cancelable) event.preventDefault();
      gesture.distance = Math.max(0, dy);
      sheet.style.translate = `0 ${Math.min(gesture.distance * .55, 150)}px`;
    }, {passive: false});
    sheet.addEventListener('touchend', () => {
      const dismiss = gesture && gesture.dragging && gesture.distance >= 90;
      reset();
      if (dismiss) close();
    }, {passive: true});
    sheet.addEventListener('touchcancel', reset, {passive: true});
  };
})(window);
