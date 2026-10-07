const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('templates/index.html','utf8');
const start=html.indexOf('      function wpItemSnapshot');
const end=html.indexOf('      const RENDER_DEFAULT_HUB',start);
const ctx={currentActiveItem:null};vm.createContext(ctx);vm.runInContext(html.slice(start,end),ctx);
test('invite retains episode and exact saved position',()=>{
 const result=ctx.wpItemSnapshot({id:'42',type:'tv',current_episode_id:'9',current_season_number:2,current_episode_number:3,currentTime:1365.25});
 assert.equal(result.current_episode_id,'9');assert.equal(result.currentTime,1365.25);
 assert.equal(result.current_season_number,2);assert.equal(result.current_episode_number,3);
});
test('movie resume and safe defaults',()=>{
 assert.equal(ctx.wpItemSnapshot({type:'movie',currentTime:'1071'}).currentTime,1071);
 for(const currentTime of [undefined,-10,'invalid',Infinity]) assert.equal(ctx.wpItemSnapshot({currentTime}).currentTime,0);
});
for(const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) if(m[1].trim()) new vm.Script(m[1]);
