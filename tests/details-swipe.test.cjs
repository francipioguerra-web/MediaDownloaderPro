const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const source=require('node:fs').readFileSync('static/js/details-swipe.js','utf8');
function fixture({top=0,mobile=true,control=false}={}) {
 const events={}; let closed=0;
 const sheet={scrollTop:top,style:{},addEventListener:(n,f)=>events[n]=f};
 const overlay={querySelector:()=>sheet,classList:{contains:()=>false}};
 const window={matchMedia:()=>({matches:mobile})};
 vm.runInNewContext(source,{window}); window.installDetailsSwipe(overlay,()=>closed++);
 const target={closest:()=>control,scrollTop:0,parentElement:sheet};
 const event=(x,y)=>({touches:[{clientX:x,clientY:y}],target,cancelable:true,preventDefault(){}});
 return {events,sheet,event,closed:()=>closed};
}
function swipe(f,x=0,y=120){f.events.touchstart(f.event(0,0));f.events.touchmove(f.event(x,y));f.events.touchend();}
test('downward swipe at top closes mobile details',()=>{const f=fixture();swipe(f);assert.equal(f.closed(),1);assert.equal(f.sheet.style.translate,'');});
for(const options of [{top:50},{mobile:false},{control:true}])test(`does not dismiss ${JSON.stringify(options)}`,()=>{const f=fixture(options);swipe(f);assert.equal(f.closed(),0);});
test('reaching top during a gesture cannot arm dismissal',()=>{const f=fixture({top:50});f.events.touchstart(f.event(0,0));f.sheet.scrollTop=0;f.events.touchmove(f.event(0,140));f.events.touchend();assert.equal(f.closed(),0);});
for(const [x,y] of [[120,10],[0,-120],[0,40]])test(`ignores horizontal, upward or short swipe ${x}/${y}`,()=>{const f=fixture();swipe(f,x,y);assert.equal(f.closed(),0);});
test('cancelled drag resets without closing',()=>{const f=fixture();f.events.touchstart(f.event(0,0));f.events.touchmove(f.event(0,120));f.events.touchcancel();f.events.touchend();assert.equal(f.closed(),0);assert.equal(f.sheet.style.translate,'');});
