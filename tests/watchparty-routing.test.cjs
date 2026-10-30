const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const html=require('node:fs').readFileSync('templates/index.html','utf8');
const start=html.indexOf('      const RENDER_DEFAULT_HUB');
const end=html.indexOf('      function closeWatchPartyInvite',start);
function fixture(fetch) {
 const ctx={fetch,AbortController,setTimeout,clearTimeout,
 window:{location:{origin:'http://localhost:5555',protocol:'http:'}},
 localStorage:{getItem:()=> 'https://obsolete-hub.invalid'}};
 vm.createContext(ctx);vm.runInContext(html.slice(start,end),ctx);return ctx;
}
test('localhost and stale preferences cannot split the party across hubs',async()=>{
 const urls=[];const ctx=fixture(async url=>{urls.push(url);return {ok:true,json:async()=>({success:true})};});
 await ctx.wpRequest('/api/watchparty/state?session_id=test');
 assert.equal(urls[0],'https://mediadownloaderpro-3q69.onrender.com/api/watchparty/state?session_id=test');
});
test('network failure never sends a command to a second independent hub',async()=>{
 let calls=0;const ctx=fixture(async()=>{calls++;throw Error('offline');});
 await assert.rejects(ctx.wpRequest('/api/watchparty/sync',{method:'POST'}),/offline/);
 assert.equal(calls,1);
});

test('a full Render deployment uses its own origin for rooms and profiles',async()=>{
 const urls=[];const ctx=fixture(async url=>{urls.push(url);return {ok:true,json:async()=>({success:true})};});
 ctx.document={documentElement:{dataset:{watchpartyLocal:'true'}}};
 ctx.window.location.origin='https://streamingcommunity-example.onrender.com';
 await ctx.wpRequest('/api/watchparty/state?session_id=test');
 assert.equal(urls[0],'https://streamingcommunity-example.onrender.com/api/watchparty/state?session_id=test');
});
