/* Presentation only: observe accepted remote commands without writing party state. */
(function (root) {
  root.watchPartyActionNotice = function (sync, session) {
    let msg;
    try { msg = JSON.parse(String(session.last_action).replace(/^wp4:/, '')); }
    catch (_) { return null; }
    if (!msg || sync.closed) return null;
    if (sync.role === 'host') {
      if (msg.kind !== 'intent' || msg.token === sync.lastIntent) return null;
    } else {
      if (msg.kind !== 'command' || msg.id <= sync.latest) return null;
      if (sync.intent && msg.intent !== sync.intent.token) return null;
      // The first command is initial alignment; an echoed local action is not remote.
      if (!sync.latest || sync.intent) return null;
    }
    const media = sync.media();
    if (msg.media && msg.media.key !== media.key) return 'ha cambiato episodio o contenuto';
    if (msg.paused !== sync.desiredPaused) return msg.paused ? 'ha messo in pausa' : 'ha ripreso la riproduzione';
    if (Math.abs(Number(msg.time) - sync.video.currentTime) > 1.5) {
      const seconds = Math.max(0, Math.floor(Number(msg.time)));
      const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
      return `ha spostato il video a ${time}`;
    }
    return null;
  };
})(typeof module === 'object' ? module.exports : window);
