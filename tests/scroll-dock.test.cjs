const {test}=require('node:test'),assert=require('node:assert/strict');
const {ScrollDock}=require('../static/js/scroll-dock.js');
function fixture(){const classes=new Set();let idle,blocked=false;const nav={classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)},querySelector:()=>blocked?{}:null};const dock=new ScrollDock({nav,position:100,schedule:fn=>(idle=fn,1),cancel(){}});return{dock,classes,stop:()=>idle(),block:()=>blocked=true};}
test('small downward increments collapse and idle restores the dock',()=>{const f=fixture();[102,104,106,108].forEach(y=>f.dock.scroll(y));assert.equal(f.classes.has('collapsed-dot'),true);f.stop();assert.equal(f.classes.size,0)});
test('upward scrolling immediately restores the dock',()=>{const f=fixture();f.dock.scroll(140);f.dock.scroll(139);assert.equal(f.classes.size,0)});
test('an open profile menu or keyboard focus keeps navigation accessible',()=>{const f=fixture();f.block();f.dock.scroll(140);assert.equal(f.classes.size,0)});
