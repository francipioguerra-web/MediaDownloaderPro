const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('templates/index.html','utf8');
const code=html.slice(html.indexOf('      let nextEpisodeStarting = false;'),html.indexOf('      async function updateNextEpisodeButton'));
function setup(next, fetch) {
 const original={id:'123',type:'tv',current_episode_id:10,current_episode_number:1,current_season_number:1};
 const calls=[];
 let release;
 const ctx={currentActiveItem:original,currentNextEpisode:next,isNextEpPopupDismissed:false,
 hideNextEpisodePopup(){},decodeHtml:s=>s,showToast(){},console,
 saveContinueWatching(item){calls.push(['save',item.current_episode_id]);},
 webVideo:{currentTime:100,duration:120,pause(){calls.push(['pause',ctx.currentActiveItem.current_episode_id]);}},
 playDirectly: async (item,time)=>{calls.push(['play',item,time]);await new Promise(r=>release=r);},fetch};
 vm.createContext(ctx);vm.runInContext(code,ctx);
 return {ctx,original,calls,release:()=>release()};
}
test('next episode accepts numeric series id, preserves old progress and ignores repeated clicks',async()=>{
 const t=setup({id:11,number:2,season_number:1,title_id:123,name:'Secondo'});
 const p=t.ctx.triggerNextEpisode();await t.ctx.triggerNextEpisode();
 assert.deepEqual(t.calls.slice(0,2),[['save',10],['pause',10]]);
 assert.equal(t.calls.filter(x=>x[0]==='play').length,1);
 assert.equal(t.calls[2][1].current_episode_id,11);
 assert.equal(t.calls[2][1].currentTime,0);
 assert.equal(t.original.current_episode_id,10);
 t.release();await p;
});
test('fallback resolves the following season without losing the startup lock',async()=>{
 const t=setup(null,async url=>({json:async()=>({success:true,episodes:url.includes('/2?')?[{id:20,number:1,name:'Nuova stagione'}]:[{id:10,number:1}]})}));
 const p=t.ctx.triggerNextEpisode();
 await new Promise(r=>setImmediate(r));
 assert.equal(t.calls[2][1].current_season_number,2);
 assert.equal(t.calls[2][1].current_episode_id,20);
 t.release();await p;
});
test('guests cannot advance independently',async()=>{
 const t=setup({id:11,number:2});t.ctx.isWatchPartyGuest=()=>true;
 await t.ctx.triggerNextEpisode();assert.equal(t.calls.length,0);
});
for(const [i,m] of [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].entries()) {
 if(m[1].trim()) new vm.Script(m[1],{filename:`inline-${i}`});
}
