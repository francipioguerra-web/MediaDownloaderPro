const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const html=require('node:fs').readFileSync('templates/index.html','utf8');
const start=html.indexOf('        // GESTURE HANDLERS (TOUCH & MOUSE');
const end=html.indexOf('        if (rankNumber) {',start);
function fixture(){
 const handlers={},opens=[];
 const card={addEventListener:(type,fn)=>handlers[type]=fn,querySelectorAll:()=>[],closest:()=>({classList:{contains:()=>true},_isGestureSwiping:true})};
 const ctx={card,item:{id:42},window:{matchMedia:()=>({matches:true})},setTimeout,clearTimeout,
   openDetails:item=>opens.push(item.id),hidePrimeHoverCard(){},openPeek(){throw Error('Mobile peek should not run');}};
 vm.createContext(ctx);vm.runInContext(html.slice(start,end),ctx);
 const event={target:{closest:()=>null},button:0,clientX:100,clientY:100,stopPropagation(){},preventDefault(){}};
 return {handlers,opens,event};
}
test('a phone tap and its compatibility mouse events open details exactly once',()=>{
 const f=fixture();for(const type of ['touchstart','touchend','mousedown','mouseup','click']) f.handlers[type](f.event);
 assert.deepEqual(f.opens,[42]);
});
test('mobile native click opens details without requiring a preceding touch or mouse event',()=>{
 const f=fixture();f.handlers.click(f.event);assert.deepEqual(f.opens,[42]);
});
test('a native scroll gesture without a click does not open the detail sheet',()=>{
 const f=fixture();for(const type of ['touchstart','touchmove','touchcancel','touchend']) f.handlers[type](f.event);
 assert.deepEqual(f.opens,[]);
});
