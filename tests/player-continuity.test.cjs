const {test}=require('node:test');
const assert=require('node:assert/strict');
const {PlayerContinuity}=require('../static/js/player-continuity.js');
function fixture(){
 const handlers={},calls=[];
 const video={currentTime:120,paused:false,ended:false,readyState:4,
  addEventListener:(n,f)=>(handlers[n] ||= []).push(f),
  removeEventListener:(n,f)=>handlers[n]=handlers[n].filter(x=>x!==f),
  pause(){this.paused=true;emit('pause');},play(){this.paused=false;emit('play');return Promise.resolve();}};
 const emit=n=>(handlers[n] || []).slice().forEach(f=>f());
 const hls={stopLoad:()=>calls.push('stop'),startLoad:t=>calls.push(['start',t])};
 const continuity=new PlayerContinuity(video,hls);return {video,emit,calls,continuity};
}
test('pausing stops background loading without unloading the frame or resetting time',()=>{
 const f=fixture();f.video.pause();assert.equal(f.video.currentTime,120);assert.deepEqual(f.calls,['stop']);
 f.video.play();assert.deepEqual(f.calls,['stop',['start',120]]);
});
test('media recovery restores a paused frame and never autoplays or returns to zero',()=>{
 const f=fixture();f.video.pause();
 f.continuity.recover(()=>{f.video.currentTime=0;f.video.readyState=0;f.emit('pause');});
 f.video.readyState=1;f.emit('loadedmetadata');
 assert.equal(f.video.currentTime,120);assert.equal(f.video.paused,true);
});
test('recovery resumes a playing video at its previous time',()=>{
 const f=fixture();f.continuity.recover(()=>{f.video.currentTime=0;f.video.pause();});
 f.emit('loadedmetadata');assert.equal(f.video.currentTime,120);assert.equal(f.video.paused,false);
});
test('a backward seek becomes the saved recovery position',()=>{
 const f=fixture();f.video.currentTime=15;f.emit('seeked');
 f.continuity.recover(()=>{f.video.currentTime=0;});f.emit('loadedmetadata');assert.equal(f.video.currentTime,15);
});
test('duplicate errors do not trigger repeated source resets while recovery is pending',()=>{
 const f=fixture();let resets=0;f.continuity.recover(()=>resets++);f.continuity.recover(()=>resets++);assert.equal(resets,1);
 f.continuity.destroy();f.video.pause();assert.deepEqual(f.calls,[]);
});
test('an error during pause never detaches the frame until the user resumes',()=>{
 const f=fixture();f.video.pause();let resets=0;
 f.continuity.defer(()=>{resets++;f.video.currentTime=0;f.video.readyState=0;});
 assert.equal(resets,0);assert.equal(f.video.currentTime,120);assert.equal(f.video.paused,true);
 assert.equal(f.continuity.resumeDeferred(),true);assert.equal(resets,1);
 f.video.readyState=1;f.emit('loadedmetadata');assert.equal(f.video.currentTime,120);assert.equal(f.video.paused,false);
});
test('retrying a failed source replacement preserves the original position and intent',()=>{
 const f=fixture();const positions=[];
 f.continuity.recover(position=>{positions.push(position);f.video.currentTime=0;f.video.readyState=0;f.video.pause();});
 f.continuity.recover(position=>positions.push(position),true);
 assert.deepEqual(positions,[120,120]);
 f.video.readyState=1;f.emit('loadedmetadata');
 assert.equal(f.video.currentTime,120);assert.equal(f.video.paused,false);
});
