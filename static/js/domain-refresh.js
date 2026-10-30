/* Refresh the source authority after one minute without interaction.
 * Existing playback, watchparty and in-progress user input are left alone. */
(function (root) {
  root.startIdleDomainRefresh = function ({busy, apply, fetchDomain = fetch, now = Date.now}) {
    let lastActivity = now(), lastCheck = 0, pending = false, stopped = false;
    const activity = () => { lastActivity = now(); };
    const events = ['pointerdown', 'pointermove', 'keydown', 'touchstart', 'scroll', 'input'];
    for (const event of events) document.addEventListener(event, activity, {passive:true});
    async function check() {
      if (stopped || pending || now() - lastActivity < 60000 || now() - lastCheck < 300000 || busy()) return;
      pending = true;
      lastCheck = now();
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 120000);
      try {
        const response = await fetchDomain('/api/sc/domain?refresh=idle', {cache:'no-store', signal:controller.signal});
        if (!response.ok) throw Error('Domain refresh failed');
        const data = await response.json();
        // A player or user interaction may have started while the check ran.
        if (!stopped && !data.deferred && !busy() && now() - lastActivity >= 60000 && data.domain) apply(data.domain);
      } catch (_) { /* Retry at the next idle check; keep the working domain. */ }
      finally { clearTimeout(timeout); pending = false; }
    }
    const timer = setInterval(check, 15000);
    return {check, stop() {
      stopped = true; clearInterval(timer);
      for (const event of events) document.removeEventListener(event, activity);
    }};
  };
})(typeof module === 'object' ? module.exports : window);
