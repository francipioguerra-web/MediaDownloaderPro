const {test} = require('node:test');
const assert = require('node:assert/strict');
const {watchPartyActionNotice: notice} = require('../static/js/watchparty-notifications.js');
const peer = role => ({role, latest:2, lastIntent:'old', desiredPaused:false,
  video:{currentTime:120}, media:() => ({key:'episode-1'})});
const state = msg => ({last_action:'wp4:'+JSON.stringify(msg)});
test('remote pause is reported for both roles without mutating sync state', () => {
  for (const role of ['host','guest']) {
    const sync = peer(role);
    const before = JSON.stringify(sync);
    assert.equal(notice(sync, state({kind:role === 'host' ? 'intent':'command', id:3, token:'new', paused:true,time:120})), 'ha messo in pausa');
    assert.equal(JSON.stringify(sync), before);
  }
});
test('poll duplicates, clocks, initial alignment and own actions stay quiet', () => {
  const sync = peer('guest');
  assert.equal(notice(sync,state({kind:'command',id:2,paused:true})),null);
  assert.equal(notice(sync,state({kind:'clock',id:3,time:500})),null);
  sync.latest=0;
  assert.equal(notice(sync,state({kind:'command',id:3,paused:true})),null);
  sync.latest=2; sync.intent={token:'mine'};
  assert.equal(notice(sync,state({kind:'command',id:3,intent:'mine',paused:true})),null);
  const host=peer('host');
  assert.equal(notice(host,state({kind:'intent',token:'old',paused:true})),null);
});
test('seek and content changes use descriptive messages; malformed data is ignored', () => {
  const sync=peer('host');
  assert.equal(notice(sync,state({kind:'intent',token:'new',paused:false,time:245})), 'ha spostato il video a 4:05');
  assert.equal(notice(sync,state({kind:'intent',token:'new',paused:false,time:120,media:{key:'episode-2'}})), 'ha cambiato episodio o contenuto');
  assert.equal(notice(sync,{last_action:'bad'}),null);
});
