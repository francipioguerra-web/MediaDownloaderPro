const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs'),vm=require('node:vm');
function fixture(){
 const elements=[],requests=[],selected=[];let revision=1;
 class Element{constructor(tag){this.tag=tag;this.children=[];this.value='';elements.push(this);}append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}setAttribute(){}}
 const context={window:{},document:{createElement:t=>new Element(t)},AbortController,fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}))};vm.createContext(context);vm.runInContext(fs.readFileSync('static/js/online-subtitles.js','utf8'),context);
 const container=new Element('div');const control=context.window.mountOnlineSubtitles({container,getItem:()=>({imdb_id:'tt1190634',type:'tv',current_season_number:2,current_episode_number:3}),getRevision:()=>revision,onSelect:track=>selected.push(track)});
 return{elements,requests,selected,control,changeEpisode(){revision++;control.reset();},search:()=>elements.find(e=>e.textContent==='Cerca sottotitoli online').onclick({stopPropagation(){}}),results:()=>elements.find(e=>e.className==='online-subs__results')};
}
const track={lang:'ita',name:'Italiano · OpenSubtitles',uri:'/api/subtitles/file/abc.vtt',format:'vtt'};
test('searches the current episode and selects a validated Italian VTT',async()=>{
 const f=fixture(),search=f.search();const payload=JSON.parse(f.requests[0].options.body);assert.equal(payload.current_episode_number,3);f.requests[0].resolve({ok:true,json:async()=>({tracks:[track]})});await search;
 const choose=f.results().children[0].onclick({stopPropagation(){}});f.requests[1].resolve({ok:true,text:async()=>('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nCiao')});await choose;assert.equal(f.selected[0].lang,'ita');
});
test('changing episodes discards a late search result',async()=>{
 const f=fixture(),search=f.search();f.changeEpisode();f.requests[0].resolve({ok:true,json:async()=>({tracks:[track]})});await search;assert.equal(f.results().children.length,0);assert.equal(f.selected.length,0);
});
test('an error page never becomes an enabled subtitle track',async()=>{
 const f=fixture(),search=f.search();f.requests[0].resolve({ok:true,json:async()=>({tracks:[track]})});await search;const choose=f.results().children[0].onclick({stopPropagation(){}});f.requests[1].resolve({ok:false,text:async()=>'<html>Error</html>'});await choose;assert.equal(f.selected.length,0);
});
