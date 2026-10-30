/* Browser history for in-page views. Snapshots stay in memory; history stores IDs. */
(function (root) {
  'use strict';
  root.createBrowserNavigation = function ({read, restore, observeRoot}) {
    const snapshots = new Map();
    const session = Math.random().toString(36).slice(2);
    let serial = 0, current = 0, restoring = false, queued = false;
    const state = id => ({...(history.state || {}), appNavigation: {session, id}});
    snapshots.set(current, read());
    history.replaceState(state(current), '', location.href);
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    function checkpoint() {
      if (restoring) return;
      const next = read(), previous = snapshots.get(current);
      if (next.key === previous.key) snapshots.set(current, next);
    }
    function commit() {
      queued = false;
      if (restoring) return;
      const next = read(), previous = snapshots.get(current);
      if (next.key === previous.key) { snapshots.set(current, next); return; }
      current = ++serial;
      snapshots.set(current, next);
      history.pushState(state(current), '', location.href);
    }
    function schedule() {
      if (queued || restoring) return;
      queued = true; queueMicrotask(commit);
    }
    const viewIds = new Set(['home-multi-rows','genre-filtered-view','archive-view','downloads-view',
      'details-modal','actor-modal','player-modal','gemini-chat-modal','profile-edit-modal']);
    new MutationObserver(records => {
      // Card appearance, hover and spotlight classes never change navigation.
      if (!records || records.some(record => record.type === 'attributes'
        ? viewIds.has(record.target.id)
        : record.target.closest?.('#catalog-grid, #archive-grid, #genre-view-title, #genre-view-count, #detail-title, #actor-hero-title'))) schedule();
    }).observe(observeRoot, {subtree:true, childList:true, attributes:true, attributeFilter:['class']});
    document.addEventListener('change', schedule);
    document.addEventListener('scroll', event => {
      if (restoring) return;
      const previous = snapshots.get(current);
      const target = event.target;
      if (target?.matches?.('.row[id], .modal-card')) {
        const position = [target, target.scrollLeft, target.scrollTop];
        const index = previous.tracks.findIndex(([element]) => element === target);
        if (index < 0) previous.tracks.push(position); else previous.tracks[index] = position;
      } else {
        previous.scroll = {x:window.scrollX, y:window.scrollY};
      }
    }, {capture:true, passive:true});
    let revision = 0;
    window.addEventListener('popstate', async event => {
      const target = event.state?.appNavigation;
      if (target?.session !== session || !snapshots.has(target.id)) return;
      const token = ++revision;
      restoring = true;
      current = target.id;
      try { await restore(snapshots.get(current), () => token === revision); }
      finally { if (token === revision) { restoring = false; } }
    });
    return {checkpoint, schedule};
  };
})(window);
