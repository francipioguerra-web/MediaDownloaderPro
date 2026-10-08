const { test } = require('node:test');
const assert = require('node:assert/strict');

test('watchparty API logic allows stream_url sync while waiting', () => {
  const sessions = [];
  function create(req) {
    const s = {
      session_id: req.session_id || 'WP-TEST',
      host_profile_id: req.host_profile_id,
      guest_profile_id: req.guest_profile_id,
      item: req.item,
      status: 'waiting',
      stream_url: req.stream_url || null,
      current_time: 0,
      paused: true
    };
    sessions.push(s);
    return s;
  }
  function sync(req) {
    const s = sessions.find(x => x.session_id === req.session_id && (x.status === 'waiting' || x.status === 'active'));
    if (!s) return null;
    if (req.stream_url) s.stream_url = req.stream_url;
    if (req.current_time !== undefined) s.current_time = req.current_time;
    if (req.paused !== undefined) s.paused = req.paused;
    return s;
  }
  function accept(req) {
    const s = sessions.find(x => x.session_id === req.session_id && (x.status === 'waiting' || x.status === 'active'));
    if (!s) return null;
    s.status = 'active';
    if (req.guest_profile_id) s.guest_profile_id = req.guest_profile_id;
    return s;
  }

  // 1. Host creates party
  const session = create({ host_profile_id: 'host1', guest_profile_id: 'guest1', item: { id: 70 }, session_id: 'ROOM-1' });
  assert.equal(session.status, 'waiting');
  assert.equal(session.stream_url, null);

  // 2. Host extracts stream immediately while waiting and syncs it
  const synced = sync({ session_id: 'ROOM-1', stream_url: 'https://vixcloud.co/playlist/278687.m3u8?token=xyz', current_time: 15 });
  assert.ok(synced, 'Sync while waiting must succeed');
  assert.equal(synced.stream_url, 'https://vixcloud.co/playlist/278687.m3u8?token=xyz');
  assert.equal(synced.current_time, 15);

  // 3. Guest accepts - receives host stream_url immediately
  const accepted = accept({ session_id: 'ROOM-1', guest_profile_id: 'guest1' });
  assert.ok(accepted);
  assert.equal(accepted.status, 'active');
  assert.equal(accepted.stream_url, 'https://vixcloud.co/playlist/278687.m3u8?token=xyz');
  assert.equal(accepted.current_time, 15);
});
