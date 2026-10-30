const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const html=require('node:fs').readFileSync('templates/index.html','utf8');
const wrapper=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function fixture(origin='http://localhost:5555/') {
 const calls=[];const ctx={URL,Request,Headers,window:{location:{href:origin},fetch:(...args)=>{calls.push(args);return Promise.resolve();}}};
 vm.createContext(ctx);vm.runInContext(wrapper,ctx);return {calls,fetch:ctx.window.fetch};
}
test('Render invite POST and pending GET have no ngrok header',async()=>{
 const t=fixture();
 for(const path of ['/api/watchparty/create','/api/watchparty/pending?profile_id=test']) {
  await t.fetch('https://mediadownloaderpro-3q69.onrender.com'+path,{headers:{'Content-Type':'application/json'}});
  assert.equal(new Headers(t.calls.at(-1)[1].headers).has('ngrok-skip-browser-warning'),false);
 }
});
test('ngrok still receives its warning bypass without mutating caller headers',async()=>{
 const t=fixture('https://example.ngrok-free.app/');const headers={'Content-Type':'application/json'};
 await t.fetch('/api/test',{headers});
 assert.equal(t.calls[0][1].headers.get('ngrok-skip-browser-warning'),'true');
 assert.equal(headers['ngrok-skip-browser-warning'],undefined);
});
test('Request objects retain existing headers when using ngrok',async()=>{
 const t=fixture();await t.fetch(new Request('https://example.ngrok.io/api/test',{headers:{'X-Test':'yes'}}));
 assert.equal(t.calls[0][1].headers.get('X-Test'),'yes');
});
