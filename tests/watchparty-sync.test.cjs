const { test } = require('node:test');
const assert = require('node:assert/strict');
const { WatchPartySync } = require('../static/js/watchparty-sync.js');
function peer(role) {
  const messages = [];
  const video = { currentTime: 120, readyState: 4, paused: true, seeking: false,
    pause() { this.paused = true; },
    play() { this.paused = false; return Promise.resolve(); } };
  const sync = new WatchPartySync({role, video,
    send: async payload => messages.push(JSON.parse(payload.action.slice(4))),
    wait() {}, error(e) { throw e; }, media: () => ({key:'episode-2'}), load() {} });
  return {sync, video, messages};
}
function state(msg) { return {last_action:'wp4:'+JSON.stringify(msg), last_sync:Date.now()}; }
test('host remains paused until guest is actually playing; stale confirmation cannot release next seek', async () => {
  const h=peer('host'), g=peer('guest');
  h.sync.request(false,120);
  await h.sync.serial;
  await g.sync.receive(state(h.messages[0]));
  await g.sync.serial;
  assert.equal(h.video.paused,true);
  assert.equal(g.messages.length,0, 'canplay/play promise alone is not confirmation');
  g.sync.event('playing'); await g.sync.serial;
  await h.sync.receive(state(g.messages[0]));
  assert.equal(h.video.paused,false);
  h.sync.request(false,300); await h.sync.serial;
  await h.sync.receive(state(g.messages[0]));
  assert.equal(h.video.paused,true);
  assert.equal(h.sync.pending.time,300);
});
test('seek while paused remains paused on both peers', async () => {
  const h=peer('host'), g=peer('guest');
  h.sync.request(true,240); await h.sync.serial;
  await g.sync.receive(state(h.messages[0])); await g.sync.serial;
  assert.equal(g.video.currentTime,240);
  await h.sync.receive(state(g.messages[0]));
  assert.equal(h.video.paused,true);
  assert.equal(g.video.paused,true);
  assert.equal(h.sync.pending,null);
});
test('buffering and autoplay rejection do not confirm playback', async () => {
  const g=peer('guest');
  g.video.play=()=>Promise.resolve(); // stays paused, as when autoplay is blocked
  await g.sync.receive(state({kind:'command',id:1,time:120,paused:false}));
  g.sync.event('canplay'); await g.sync.serial;
  assert.equal(g.messages.length,0);
  g.video.paused=false; g.video.readyState=2;
  g.sync.event('playing'); await g.sync.serial;
  assert.equal(g.messages.length,0);
});
test('host waits for its own buffer, retries lost commands, and never times out into playback', async () => {
  const h=peer('host'); h.video.readyState=1;
  h.sync.request(false,120); await h.sync.serial;
  assert.equal(h.messages.length,0);
  h.video.readyState=4; h.sync.tick(); await h.sync.serial;
  h.sync.lastWrite=0; h.sync.tick(); await h.sync.serial;
  assert.equal(h.messages.length,2);
  assert.equal(h.video.paused,true);
  assert.equal(h.messages[0].id,h.messages[1].id);
});
test('duplicate command does not rewind guest; obsolete command is ignored', async () => {
  const g=peer('guest'); const cmd={kind:'command',id:2,time:120,paused:false};
  await g.sync.receive(state(cmd));
  g.video.currentTime=123;
  await g.sync.receive(state(cmd));
  await g.sync.receive(state({...cmd,id:1,time:30}));
  assert.equal(g.video.currentTime,123);
});
test('ended session cannot send queued commands', async () => {
  const h=peer('host'); h.sync.request(false,120); h.sync.close(); await h.sync.serial;
  assert.equal(h.messages.length,0);
});
test('guest buffering requests a new confirmed start at guest position', async () => {
  const h=peer('host'); h.sync.sequence=3; h.sync.desiredPaused=false; h.video.paused=false;
  await h.sync.receive(state({kind:'buffer',id:3,time:125})); await h.sync.serial;
  assert.equal(h.video.paused,true);
  assert.equal(h.sync.pending.time,125);
  assert.equal(h.sync.pending.id,4);
});
test('episode change waits for the new media before acknowledging its resume position', async () => {
  const g=peer('guest'); let loaded;
  g.sync.load=(media,time)=>{g.sync.loading=true;loaded={media,time};};
  await g.sync.receive(state({kind:'command',id:1,time:1356,paused:false,media:{key:'s3e8'}}));
  g.sync.event('playing'); await g.sync.serial;
  assert.equal(g.messages.length,0);
  assert.equal(loaded.time,1356);
  assert.equal(loaded.media.key,'s3e8');
  g.sync.loading=false; g.sync.positionGuest(); g.sync.event('playing'); await g.sync.serial;
  assert.equal(g.messages[0].time,1356);
});
test('programmatic host resume does not create another play or seek command', async () => {
  const h=peer('host'); h.sync.request(false,120); await h.sync.serial;
  await h.sync.receive(state({kind:'ack',id:1,time:121}));
  h.sync.event('seeked'); h.sync.event('play'); h.sync.event('playing');
  assert.equal(h.sync.sequence,1);
  assert.equal(h.sync.pending,null);
  h.video.pause(); h.sync.event('pause'); await h.sync.serial;
  assert.equal(h.sync.pending.paused,true);
});
test('repeated clock polls never seek a playing guest back to an old scene', async () => {
  const g=peer('guest'); g.sync.latest=1; g.sync.desiredPaused=false; g.video.paused=false;
  const clock=state({kind:'clock',id:1,sample:1,time:120});
  for (let i=0;i<8;i++) {
    const before=120+i*0.4; g.video.currentTime=before;
    await g.sync.receive(clock);
    assert.equal(g.video.currentTime,before);
  }
});
test('loadeddata and canplay callbacks cannot reapply an already positioned command', async () => {
  const g=peer('guest');
  await g.sync.receive(state({kind:'command',id:1,time:120,paused:false}));
  g.video.currentTime=122;
  g.sync.positionGuest();
  assert.equal(g.video.currentTime,122);
});
test('waiting caused by a seek must not create another host command', async () => {
  const h=peer('host'); h.sync.desiredPaused=false; h.video.paused=false; h.video.seeking=true;
  h.sync.event('waiting');
  assert.equal(h.sync.sequence,0);
});
test('brief buffering does not restart the watchparty; sustained buffering does', async () => {
  const h=peer('host');h.sync.desiredPaused=false;h.video.paused=false;h.video.readyState=2;
  h.sync.event('waiting');h.sync.tick();assert.equal(h.sync.sequence,0);
  h.video.readyState=4;h.sync.event('playing');h.sync.tick();assert.equal(h.sync.sequence,0);
  h.video.readyState=2;h.sync.event('waiting');h.sync.bufferSince=Date.now()-1000;h.sync.tick();
  assert.equal(h.sync.sequence,1);assert.equal(h.video.paused,true);
  await h.sync.serial;
});
test('fresh clocks use bounded speed correction and stale clocks are ignored', async () => {
  const g=peer('guest');g.sync.latest=1;g.sync.desiredPaused=false;g.video.paused=false;g.video.currentTime=125;
  await g.sync.receive(state({kind:'clock',id:1,sample:2,time:124}));
  assert.equal(g.video.playbackRate,.97);
  await g.sync.receive(state({kind:'clock',id:1,sample:1,time:130}));
  assert.equal(g.video.playbackRate,.97);assert.equal(g.video.currentTime,125);
  g.sync.close();assert.equal(g.video.playbackRate,1);
});
test('late seeked for the pending startup does not generate a second command', async () => {
  const h=peer('host');h.sync.request(false,120);h.sync.event('seeked');await h.sync.serial;
  assert.equal(h.sync.sequence,1);
});
function playerReadyFixture() {
  const fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
  const html=fs.readFileSync(path.join(__dirname,'../templates/index.html'),'utf8');
  const start=html.indexOf('        let hasResumed = false;',html.indexOf('function playInWebPlayer('));
  const end=html.indexOf("        if (webVideo) {\n          webVideo.addEventListener('loadeddata'",start);
  const calls=[], listeners=[];
  const ctx={loadRevision:1,playerLoadRevision:1,resumeTime:1356,watchPartyRole:'host',
    webVideo:{readyState:1,currentTime:0,addEventListener:(ev,fn)=>listeners.push(fn)},
    wpConfirmedSync:{request:(...args)=>calls.push(args)},wpCurrentMedia:()=>({key:'s3e8'}),
    hidePlayerLoader(){},autoEnterMobileLandscape(){},wakePlayerControls(){},showToast(){},formatTime:String};
  vm.createContext(ctx);vm.runInContext(html.slice(start,end)+'\nglobalThis.runReady=onReady;',ctx);
  return {ctx,calls,listeners};
}
test('HLS manifest recovery cannot restart an already running party', () => {
  const {ctx,calls}=playerReadyFixture();ctx.runReady();ctx.webVideo.currentTime=1366;ctx.runReady();
  assert.equal(calls.length,1);assert.equal(ctx.webVideo.currentTime,1366);
});
test('startup waits for metadata before applying the saved resume position', () => {
  const {ctx,calls,listeners}=playerReadyFixture();ctx.webVideo.readyState=0;ctx.runReady();
  assert.equal(calls.length,0);assert.equal(ctx.webVideo.currentTime,0);
  ctx.webVideo.readyState=1;listeners[0]();assert.equal(calls[0][1],1356);assert.equal(ctx.webVideo.currentTime,1356);
});
test('callbacks from a replaced media load cannot restart the current episode', () => {
  const {ctx,calls}=playerReadyFixture();ctx.playerLoadRevision=2;ctx.runReady();assert.equal(calls.length,0);
});
