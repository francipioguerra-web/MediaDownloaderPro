const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm'),fs=require('node:fs');
function fixture(reduced=true){
 let now=1000,opened=0,modal=false;const listeners={},timers=new Map();let timerId=0;
 class Element{
  constructor(){this.children=[];this.isConnected=true;this.classes=new Set();this.classList={add:c=>this.classes.add(c),remove:c=>this.classes.delete(c),toggle:(c,on)=>on?this.classes.add(c):this.classes.delete(c)};this.styles={};this.style={setProperty:(k,v)=>this.styles[k]=v,removeProperty:k=>delete this.styles[k]};}
  append(...els){this.children.push(...els);}appendChild(el){this.children.push(el);}replaceChildren(...els){this.children=els;}setAttribute(){}closest(){return null;}querySelectorAll(){return [];}remove(){this.removed=true;}
 }
 const track=new Element();track.scrollLeft=500;track.scrollWidth=1000;track.clientWidth=500;
 track.events={};track.addEventListener=(n,f)=>track.events[n]=f;track.getBoundingClientRect=()=>({top:200,bottom:500});
 track.querySelector=selector=>selector==='.row-catalog-end'?track.children.find(e=>e.className==='row-catalog-end'):{};
 const body=new Element();
 const context={window:{innerWidth:1280,innerHeight:800,matchMedia:()=>({matches:reduced}),addEventListener(n,f){listeners[n]=f;}},document:{body,createElement:()=>new Element(),createElementNS:()=>new Element(),querySelector:()=>modal?{}:null,addEventListener(n,f){listeners[n]=f;}},performance:{now:()=>now},setTimeout(f){timers.set(++timerId,f);return timerId;},clearTimeout(id){timers.delete(id);},MutationObserver:class{observe(){}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('static/js/carousel-catalog-spring.js','utf8'),context);
 context.window.createCarouselCatalogSpring().register(track,()=>opened++);
 return{body,track,listeners,opened:()=>opened,time:n=>now=n,modal:value=>modal=value,flush(){const pending=[...timers.values()];timers.clear();pending.forEach(f=>f());},end:()=>track.children[0],wheel(delta,extra={}){let prevented=false;listeners.wheel({deltaX:0,deltaY:delta,deltaMode:0,cancelable:true,target:{closest:selector=>selector==='.row'?track:null},preventDefault(){prevented=true;},...extra});return prevented;}};
}
test('vertical wheel over any card in the carousel opens only after the pull is released',()=>{
 const f=fixture();f.track.events.scroll();f.time(1600);assert.equal(f.wheel(120),true);assert.equal(f.opened(),0);assert.match(f.body.children[0].style.transform,/translateX/);f.flush();assert.equal(f.opened(),1);
});
test('a fast scroll reaching the end does not reveal or open the catalog',()=>{
 const f=fixture();f.track.scrollLeft=450;f.time(980);f.wheel(30);f.track.scrollLeft=500;f.time(1000);f.track.events.scroll();for(let i=1;i<30;i++){f.time(1000+i*16);f.wheel(15);}assert.equal(f.body.children.length,0);f.flush();assert.equal(f.opened(),0);f.time(1700);f.wheel(120);f.flush();assert.equal(f.opened(),1);
});
test('short pulls spring back and permit a fresh retry',()=>{
 const f=fixture();f.track.events.scroll();f.time(1600);f.wheel(30);f.flush();assert.equal(f.opened(),0);f.time(2000);f.wheel(120);f.flush();assert.equal(f.opened(),1);
});
test('hidden rows and open player dialogs never intercept page scrolling',()=>{
 const f=fixture();f.track.events.scroll();f.modal(true);f.time(1600);assert.equal(f.wheel(120),false);f.flush();assert.equal(f.opened(),0);
});
test('moving away from the end clears the global gesture target',()=>{
 const f=fixture();f.track.events.scroll();f.track.scrollLeft=200;f.track.events.scroll();f.time(1600);assert.equal(f.wheel(120),false);f.flush();assert.equal(f.opened(),0);
});

test('catalog navigation waits for the spring release animation to finish',async()=>{
 const f=fixture(false);let complete;let animations=0;
 const originalAppend=f.body.appendChild.bind(f.body);f.body.appendChild=el=>{el.animate=()=>{animations++;return{finished:new Promise(resolve=>{complete=resolve;}),cancel(){}};};originalAppend(el);};
 f.track.events.scroll();f.time(1600);f.wheel(120);f.flush();
 assert.equal(animations,1);assert.equal(f.opened(),0);complete();await Promise.resolve();assert.equal(f.opened(),1);
});

test('wheel outside the completed carousel never opens the catalog',()=>{
 const f=fixture();f.track.events.scroll();f.time(1600);
 assert.equal(f.wheel(140,{target:{closest:()=>null}}),false);
 f.flush();assert.equal(f.opened(),0);assert.equal(f.track.styles['--catalog-pull'],undefined);
});
test('the incoming page moves while the carousel itself remains still',()=>{
 const f=fixture();f.track.events.scroll();f.time(1600);f.wheel(60);
 assert.equal(f.body.children.length,1);
 assert.equal(f.end().styles['--catalog-pull'],undefined);
 f.flush();assert.equal(f.track.styles.transform,undefined);
});

test('mouse drag reveals the incoming page and opens on release',()=>{
 const f=fixture();f.track.events.scroll();
 const target={closest:s=>s==='.row'?f.track:null};
 f.listeners.mousedown({button:0,clientX:800,target,preventDefault(){}});
 f.listeners.mousemove({clientX:480,preventDefault(){},stopPropagation(){}});
 assert.equal(f.opened(),0);assert.equal(f.body.children.length,1);
 f.listeners.mouseup();assert.equal(f.opened(),1);
});

test('the incoming page edge stays aligned with the mouse, including reverse movement',()=>{
 const f=fixture();const target={closest:s=>s==='.row'?f.track:null};
 f.listeners.mousedown({button:0,clientX:800,target,preventDefault(){}});
 f.listeners.mousemove({clientX:700,preventDefault(){},stopPropagation(){}});
 assert.equal(f.body.children[0].style.transform,'translateX(700px)');
 f.listeners.mousemove({clientX:760,preventDefault(){},stopPropagation(){}});
 assert.equal(f.body.children[0].style.transform,'translateX(760px)');
});
test('the incoming page edge stays aligned with a finger',()=>{
 const f=fixture();const target={closest:s=>s==='.row'?f.track:null};
 f.listeners.touchstart({target,touches:[{clientX:350,clientY:300}]});
 f.listeners.touchmove({touches:[{clientX:250,clientY:300}],cancelable:true,preventDefault(){}});
 assert.equal(f.body.children[0].style.transform,'translateX(250px)');
 f.listeners.touchmove({touches:[{clientX:290,clientY:300}],cancelable:true,preventDefault(){}});
 assert.equal(f.body.children[0].style.transform,'translateX(290px)');
});
