const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const html=require('node:fs').readFileSync('templates/index.html','utf8');
const start=html.indexOf('      async function loadSeasonEpisodes(item, seasonNum) {');
const end=html.indexOf('\n      let isEpisodeSelectionMode',start);
function fixture(){
 const requests=[],rendered=[]; const item={id:'42',slug:'show'};
 const context={AbortController,Number,encodeURIComponent,episodeRequestRevision:0,episodeRequestAbort:null,
  currentActiveItem:item,episodesContainer:{innerHTML:''},
  fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve})),
  renderEpisodesList:(item,episodes,season)=>rendered.push({item,episodes,season})};
 vm.createContext(context);
 vm.runInContext(html.slice(html.indexOf('      function cardPlaceholders('),html.indexOf('      let homeGenreObserver')),context);
 vm.runInContext(html.slice(start,end),context);
 return {context,item,requests,rendered};
}
test('changing season discards an older response even if the server ignores cancellation',async()=>{
 const f=fixture();const first=f.context.loadSeasonEpisodes(f.item,1),second=f.context.loadSeasonEpisodes(f.item,2);
 assert.equal(f.requests[0].options.signal.aborted,true);
 f.requests[1].resolve({ok:true,json:async()=>({success:true,episodes:[{number:1,name:'Season two'}]})});await second;
 f.requests[0].resolve({ok:true,json:async()=>({success:true,episodes:[{number:1,name:'Season one'}]})});await first;
 assert.deepEqual(f.rendered.map(r=>r.season),[2]);
});
test('a response for a previous title cannot replace the active title episodes',async()=>{
 const f=fixture();const pending=f.context.loadSeasonEpisodes(f.item,1);f.context.currentActiveItem={id:'other'};
 f.requests[0].resolve({ok:true,json:async()=>({success:true,episodes:[{number:1}]})});await pending;assert.equal(f.rendered.length,0);
});
test('a different episode starts at zero; the same episode keeps its resume position',()=>{
 const start=html.indexOf('            const sameEpisode =');const end=html.indexOf('\n          };',start);
 for(const same of [true,false]){
  let played;const item={current_episode_id:'old',current_season_number:1,currentTime:321};
  const context={String,Number,item,ep:{id:same?'old':'new',watch_url:'/ep',number:2},seasonNum:1,cleanEpName:'Titolo',playDirectly:x=>played=x};
  vm.runInNewContext(html.slice(start,end),context);assert.equal(played.currentTime,same?321:0);
 }
});

test('recovering the episode list also restores all available seasons',async()=>{
 const f=fixture();let options=[];
 f.context.document={getElementById:()=>({replaceChildren:(...next)=>options=next}),createElement:()=>({})};
 const pending=f.context.loadSeasonEpisodes(f.item,4);
 f.requests[0].resolve({ok:true,json:async()=>({success:true,episodes:[{number:1}],seasons:[{number:1,episodes_count:10},{number:4,episodes_count:10}]})});
 await pending;assert.equal(options.length,2);assert.equal(options[1].selected,true);assert.equal(f.item.seasons[1].number,4);
});
