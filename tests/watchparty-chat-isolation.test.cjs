const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('templates/index.html','utf8');
test('chat failure cannot block the watchparty startup or polling',()=>{
 const start=html.indexOf('      function activateWatchParty(');
 const end=html.indexOf('      function updateWatchPartyDriftUI',start);
 const calls=[];
 const ctx={setWatchPartyBanner(){},wpWsDisconnect(){},startConfirmedParty(){calls.push('sync');},startWatchPartyStatePolling(){calls.push('poll');},wpChat:{start(){throw Error('chat unavailable');}},wpGuestLoading:null,currentActiveProfile:{id:'host'},console:{warn(){}}};
 vm.createContext(ctx);vm.runInContext(html.slice(start,end),ctx);
 assert.doesNotThrow(()=>ctx.activateWatchParty({session_id:'test'},'host'));
 assert.deepEqual(calls,['sync','poll']);
});
test('opening the chat does not detach or reparent the media element',()=>{
 const source=fs.readFileSync('static/js/watchparty-chat.js','utf8');
 const method=source.slice(source.indexOf('    setOpen(open)'),source.indexOf('    start(session'));
 assert.doesNotMatch(method,/appendChild|replaceWith|prepend|childNodes/);
});
