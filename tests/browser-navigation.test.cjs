const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function setup() {
  let view = {key:'home',scroll:{x:0,y:320},tracks:[]};
  const entries = [], listeners = {}, tasks = [];
  let observer;
  const history = {state:null, scrollRestoration:'auto', replaceState(s){this.state=s;entries[entries.length ? entries.length-1 : 0]=s;},pushState(s){this.state=s;entries.push(s);}};
  const root = {querySelectorAll(){return [];}};
  const context = {window:{scrollX:0,scrollY:320,addEventListener(n,f){listeners[n]=f;}},history, location:{href:'http://localhost:5555/'},document:{addEventListener(n,f){listeners[n]=f;}},MutationObserver:class{constructor(f){observer=f;}observe(){}},queueMicrotask(f){tasks.push(f);}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('static/js/browser-navigation.js','utf8'),context);
  const restored=[];
  let reads=0;
  const navigation=context.window.createBrowserNavigation({read:()=>{reads++;return {...view};}, restore:async snapshot=>{restored.push(snapshot);view={...snapshot};observer();},observeRoot:root});
  const flush=()=>{while(tasks.length)tasks.shift()();};
  return {entries,history,navigation,restored, listeners,flush, reads:()=>reads, mutate(records){observer(records);flush();}, change(key){view={...view,key};observer();flush();}};
}
test('card Back and Forward restore the prior internal screen without pushing duplicates',async()=>{
 const app=setup();app.change('details:42');assert.equal(app.entries.length,2);
 await app.listeners.popstate({state:app.entries[0]});app.flush();assert.equal(app.restored.at(-1).key,'home');assert.equal(app.restored.at(-1).scroll.y,320);assert.equal(app.entries.length,2);
 await app.listeners.popstate({state:app.entries[1]});app.flush();assert.equal(app.restored.at(-1).key,'details:42');assert.equal(app.entries.length,2);
});
test('background rendering and repeated screen selection do not add history entries',()=>{
 const app=setup();app.change('home');app.change('home');assert.equal(app.entries.length,1);app.change('archive:animation');app.change('archive:animation');assert.equal(app.entries.length,2);
});
test('search, details, and archive preserve their order; unrelated browser states are ignored',async()=>{
 const app=setup();for(const key of ['search:alien','details:1','archive:horror'])app.change(key);
 for(let i=2;i>=0;i--)await app.listeners.popstate({state:app.entries[i]});
 assert.deepEqual(app.restored.map(x=>x.key),['details:1','search:alien','home']);
 await app.listeners.popstate({state:{other:true}});assert.equal(app.restored.length,3);
});

test('poster animations do not reread or serialize navigation snapshots',()=>{
 const app=setup();const before=app.reads();
 for(let i=0;i<100;i++)app.mutate([{type:'attributes',target:{id:'',closest(){return null;}}}]);
 assert.equal(app.reads(),before);assert.equal(app.entries.length,1);
 app.mutate([{type:'attributes',target:{id:'details-modal'}}]);assert.equal(app.reads(),before+1);
});
