const {test}=require('node:test');
const assert=require('node:assert/strict');
const {ExternalSubtitleTracks}=require('../static/js/player-tracks.js');
function fixture(){
 const elements=[];
 const video={appendChild:e=>elements.push(e)};
 const controller=new ExternalSubtitleTracks(video,()=>({track:{mode:'disabled'},remove(){elements.splice(elements.indexOf(this),1)}}));
 return {controller,elements};
}
test('external original and forced captions can be selected and disabled',()=>{
 const {controller:c,elements}=fixture();
 c.setTracks([{uri:'/api/stream/segment?url=https%3A%2F%2Fcdn.test%2Fita.vtt',lang:'ita',name:'Italiano'},
  {uri:'https://cdn.test/forced.vtt?t=1',lang:'ita',name:'Italiano [Forced]'}]);
 assert.equal(c.tracks.length,2);c.select('external:1');
 assert.deepEqual(elements.map(e=>e.track.mode),['disabled','showing']);
 c.select('external:0');assert.deepEqual(elements.map(e=>e.track.mode),['showing','disabled']);
 c.select(-1);assert.deepEqual(elements.map(e=>e.track.mode),['disabled','disabled']);
});
test('menu refresh preserves selection and source changes discard old captions',()=>{
 const {controller:c,elements}=fixture();const tracks=[{uri:'/first.vtt',lang:'eng'}];
 c.setTracks(tracks);c.select('external:0');c.setTracks(tracks);
 assert.equal(c.selected,'external:0');assert.equal(elements.length,1);
 c.setTracks([{uri:'/second.vtt',lang:'ita'}]);assert.equal(c.selected,-1);assert.equal(elements.length,1);
 assert.equal(elements[0].src,'/second.vtt');c.clear();assert.equal(elements.length,0);
});
test('HLS playlists and malformed track URLs are not misrepresented as external WebVTT',()=>{
 const {controller:c}=fixture();c.setTracks([{uri:'https://cdn.test/subs.m3u8'},{name:'No URL'}]);
 assert.equal(c.tracks.length,0);
});
test('VixCloud signed subtitle URLs preserve the selected language after token renewal',()=>{
 const {controller:c,elements}=fixture();
 c.setTracks([{uri:'/api/vixcloud/media?token=old',format:'vtt',name:'English',lang:'en'}]);
 c.select('external:0');
 c.setTracks([{uri:'/api/vixcloud/media?token=new',format:'vtt',name:'English',lang:'en'}]);
 assert.equal(c.selected,'external:0');assert.equal(elements[0].track.mode,'showing');assert.match(elements[0].src,/token=new/);
});
test('failed caption loading is reported and can be selected again',()=>{
 const {controller:c,elements}=fixture();let failed;
 c.onError=t=>failed=t.name;
 c.setTracks([{uri:'/api/vixcloud/media?token=sub',format:'vtt',name:'Italiano',lang:'it'}]);c.select('external:0');
 elements[0].onerror();assert.equal(c.selected,-1);assert.equal(failed,'Italiano');
 c.select('external:0');assert.equal(c.selected,'external:0');
});
