const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function setup() {
  const elements=[];
  class Element {
    constructor(tag){this.tag=tag;this.children=[];this.value='';elements.push(this);}
    append(...children){this.children.push(...children);if(this.tag==='select'&&!this.value)this.value=children[0]?.value||'';}
    replaceChildren(...children){this.children=children;}
    setAttribute(){} addEventListener(){} close(){} remove(){} showModal(){} focus(){}
  }
  let resolveRequest;
  const context={window:{addEventListener(){},removeEventListener(){}},document:{createElement:tag=>new Element(tag),body:new Element('body')},AbortController,setTimeout(){return 1;},clearTimeout(){},fetch(){return new Promise(resolve=>{resolveRequest=resolve;});}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('static/js/download-options.js','utf8'),context);
  const result=context.window.chooseDownloadOptions({name:'Serie',current_watch_url:'https://source.test/episode'});
  return {elements,result,async sources(sources){resolveRequest({ok:true,json:async()=>({sources})});for(let i=0;i<8;i++)await Promise.resolve();}, container(){return elements.find(e=>e.className==='download-options__sources');}};
}
const sc={provider:'streamingcommunity',label:'StreamingCommunity',url:'https://sc.test/episode',qualities:[{value:'1080p',label:'1080p'}]};
const gs={provider:'guardoseries',label:'Guardaserie',url:'https://gs.test/episode',qualities:[{value:'1080p',label:'1080p'},{value:'720p',label:'720p'}]};
test('waits for matching then shows only Guardaserie and passes selected quality',async()=>{
 const app=setup();assert.equal(app.container().children.length,0,'No original-source shortcut while matching');
 await app.sources([sc,gs]);assert.equal(app.container().children.length,1);
 const section=app.container().children[0];assert.equal(section.children[0].textContent,'Guardaserie');
 const select=section.children[1].children[0];select.value='720p';section.children[2].onclick();
 const result=await app.result;assert.equal(result.provider,'guardoseries');assert.equal(result.format_choice,'720p');assert.equal(result.url,gs.url);
});
test('uses StreamingCommunity when no matching Guardaserie source is available',async()=>{
 const app=setup();await app.sources([sc]);const section=app.container().children[0];assert.equal(section.children[0].textContent,'StreamingCommunity');section.children[2].onclick();assert.equal((await app.result).provider,'streamingcommunity');
});
test('cancelling during matching never starts a download',async()=>{
 const app=setup();app.elements.find(e=>e.className==='download-options__cancel').onclick();assert.equal(await app.result,null);await app.sources([sc,gs]);assert.equal(app.container().children.length,0);
});
