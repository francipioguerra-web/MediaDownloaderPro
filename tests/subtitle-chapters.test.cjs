const {test}=require('node:test');
const assert=require('node:assert/strict');
const {SubtitleChapters: chapters}=require('../static/js/subtitle-chapters.js');
const dialogue=Array.from({length:100},(_,i)=>({start:90+i*20,end:95+i*20}));
test('intro and credits follow subtitle silence',()=>{
 const result=chapters.detect(dialogue,2120);
 assert.deepEqual(result,{intro:{start:0,end:90},outro:2075});
});
test('cold open, overlapping cues and a later intro',()=>{
 const result=chapters.detect([{start:0,end:20},{start:5,end:10},...dialogue],2120);
 assert.deepEqual(result.intro,{start:20,end:90});
});
test('missing and sparse/forced subtitles do not imply an intro or credits',()=>{
 assert.deepEqual(chapters.detect([],2120),{intro:null,outro:null});
 assert.deepEqual(chapters.detect(dialogue.slice(0,4),2120),{intro:null,outro:null});
});
test('dialogue continuing to the end prevents early credits',()=>{
 assert.equal(chapters.detect([...dialogue,{start:2110,end:2119}],2120).outro,null);
});
test('parses VTT, SRT and timestamp map',()=>{
 assert.deepEqual(chapters.parse('00:01,000 --> 00:04,500'),[{start:1,end:4.5}]);
 assert.deepEqual(chapters.parse('X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n00:00:01.000 --> 00:00:04.000'),[{start:11,end:14}]);
});
test('loads rewritten subtitle playlists from the local proxy without enabling captions',async()=>{
 global.location={href:'http://localhost:5555/'};
 const requested=[];
 global.fetch=async url=>{
  requested.push(url);
  return {ok:true,text:async()=>requested.length===1?'#EXTM3U\n#EXTINF:2100,\n/api/stream/segment?url=https%3A%2F%2Fcdn.example%2Fsub.vtt\n#EXT-X-ENDLIST':Array.from({length:20},(_,i)=>`00:00:${String(i).padStart(2,'0')}.000 --> 00:00:${String(i+1).padStart(2,'0')}.000\nHello`).join('\n')};
 };
 const cues=await chapters.load([{uri:'https://cdn.example/sub.m3u8'}],'https://cdn.example/master.m3u8',new AbortController().signal);
 assert.equal(cues.length,20);
 assert.equal(requested[1],'http://localhost:5555/api/stream/segment?url=https%3A%2F%2Fcdn.example%2Fsub.vtt');
 delete global.fetch; delete global.location;
});
test('ignores forced subtitles even when the provider incorrectly sets FORCED=NO',async()=>{
 global.location={href:'http://localhost:5555/'};
 const requested=[];
 global.fetch=async url=>{
  requested.push(url);
  return {ok:true,text:async()=>Array.from({length:30},(_,i)=>`00:01:${String(i).padStart(2,'0')}.000 --> 00:01:${String(i+1).padStart(2,'0')}.000\nDialogue`).join('\n')};
 };
 const cues=await chapters.load([
  {name:'Italian [Forced]',lang:'ita-forced',forced:false,uri:'https://cdn.example/forced.vtt'},
  {name:'Italian [CC]',lang:'ita',forced:false,uri:'https://cdn.example/full.vtt'},
 ],'https://cdn.example/master.m3u8',new AbortController().signal);
 assert.equal(cues.length,30);
 assert.equal(requested.length,1);
 assert.match(decodeURIComponent(requested[0]),/full\.vtt/);
 delete global.fetch; delete global.location;
});

test('passes referrer parameter to proxy when track provides one', async () => {
  global.location = {href: 'http://localhost:5555/'};
  const requested = [];
  global.fetch = async url => {
    requested.push(url);
    return {
      ok: true,
      text: async () => Array.from({length: 25}, (_, i) => '00:01:' + String(i).padStart(2, '0') + '.000 --> 00:01:' + String(i+1).padStart(2, '0') + '.000\nLine ' + i).join('\n')
    };
  };
  const cues = await chapters.load([
    {uri: 'https://cdn.example/vtt/sub.vtt', referrer: 'https://vixcloud.cc/embed/123'}
  ], 'https://cdn.example/master.m3u8', new AbortController().signal);
  assert.equal(cues.length, 25);
  assert.match(requested[0], /&ref=https%3A%2F%2Fvixcloud\.cc%2Fembed%2F123/);
  delete global.fetch; delete global.location;
});
test('VixCloud signed subtitles stay local when the video manifest loads directly from its origin',async()=>{
 global.location={href:'http://localhost:5555/'};
 const requested=[];
 global.fetch=async url=>{
  requested.push(url);
  return {ok:true,text:async()=>Array.from({length:20},(_,i)=>`00:00:${String(i).padStart(2,'0')}.000 --> 00:00:${String(i+1).padStart(2,'0')}.000\nHello`).join('\n')};
 };
 try {
  const cues=await chapters.load([{uri:'/api/vixcloud/media?token=signed',lang:'ita'}],
   'https://vixcloud.cc/playlist/42',new AbortController().signal);
  assert.equal(cues.length,20);
  assert.deepEqual(requested,['http://localhost:5555/api/vixcloud/media?token=signed']);
 } finally {delete global.fetch;delete global.location;}
});

test('online subtitle timelines load locally without passing through the media proxy',async()=>{
 global.location={href:'http://localhost:5555/'};
 const uri='/api/subtitles/file/'+'a'.repeat(32)+'.vtt';const requests=[];
 global.fetch=async (url,options)=>{
  requests.push({url,options});
  if(url==='/api/subtitles/search')return{ok:true,json:async()=>({tracks:[{lang:'ita',uri,format:'vtt'}]})};
  return{ok:true,text:async()=>Array.from({length:100},(_,i)=>{
    const start=90+i*20;const end=start+5;
    const time=n=>new Date(n*1000).toISOString().slice(11,23);
    return `${time(start)} --> ${time(end)}\nDialogue`;
  }).join('\n\n')};
 };
 try {
  const item={imdb_id:'tt1234567',type:'tv',current_season_number:1,current_episode_number:2};
  const cues=await chapters.loadOnline(item,'https://cdn.test/master.m3u8',new AbortController().signal);
  assert.equal(cues.length,100);assert.equal(JSON.parse(requests[0].options.body).current_episode_number,2);
  assert.equal(requests[1].url,'http://localhost:5555'+uri);
  assert.deepEqual(chapters.detect(cues,2120),{intro:{start:0,end:90},outro:2075});
 }finally{delete global.fetch;delete global.location;}
});
test('cancelled episode analysis does not search online or attach old timelines',async()=>{
 const controller=new AbortController();controller.abort();let requested=false;
 global.fetch=async()=>{requested=true;throw Error('Must not fetch')};
 try{assert.deepEqual(await chapters.loadOnline({type:'tv'},'',controller.signal),[]);assert.equal(requested,false);}finally{delete global.fetch;}
});

test('filters amateur credits watermarks and preserves dialogue', () => {
  const vtt = `00:00:01.000 --> 00:00:04.000\n::Italian Subs Addicted::\n[www.italiansubs.net]\n\n00:00:05.000 --> 00:00:08.000\nTraduzione a cura di Mario\nCalma, bello.\n\n00:00:10.000 --> 00:00:12.000\nQuante cose si fanno per amore...\n\n00:00:15.000 --> 00:00:20.000\nTranscript: swsub.com`;
  const cues = chapters.parse(vtt);
  assert.equal(cues.length, 2);
  assert.deepEqual(cues, [{start: 5, end: 8}, {start: 10, end: 12}]);
});
