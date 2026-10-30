const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const html=require('node:fs').readFileSync('templates/index.html','utf8');
function fixture(sync) {
 const calls=[];
 const ctx={wpConfirmedSync:sync,webVideo:{paused:true,currentTime:120,duration:600},
   wakePlayerControls(){calls.push('wake');},calls};
 vm.createContext(ctx);
 for(const [start,end] of [['      function togglePlayPause() {','      function updatePlayPauseUI('],['      function seekPlayer(time) {','      function seekToPosition(e) {']]) {
   vm.runInContext(html.slice(html.indexOf(start),html.indexOf(end,html.indexOf(start))),ctx);
 }
 return ctx;
}
test('both participants use sync controls without mutating the media locally',()=>{
 const calls=[];const ctx=fixture({toggle:()=>calls.push('toggle'),seek:t=>calls.push(['seek',t]),skip:t=>calls.push(['skip',t])});
 ctx.togglePlayPause();ctx.seekPlayer(200);ctx.skipPlayer(-10);ctx.skipPlayer(10);
 assert.deepEqual(calls,['toggle',['seek',200],['skip',-10],['skip',10]]);
 assert.equal(ctx.webVideo.currentTime,120);
});
test('standalone seeking retains normal local behavior',()=>{
 const ctx=fixture(null);ctx.skipPlayer(10);assert.equal(ctx.webVideo.currentTime,130);
 ctx.skipPlayer(-10);assert.equal(ctx.webVideo.currentTime,120);
 ctx.seekPlayer(300);assert.equal(ctx.webVideo.currentTime,300);
});
