const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const html=require('node:fs').readFileSync('templates/index.html','utf8');
test('late extraction from a previous title cannot overwrite the current stream metadata',async()=>{
 const start=html.indexOf('      async function resolveExtraction('),end=html.indexOf('      // DIRECT IN-APP',start);
 const requests=[];const a={id:'a'},b={id:'b'};
 const context={window:{},currentActiveItem:a,currentStreamAudioTracks:[],currentStreamSubtitleTracks:[],currentStreamQualities:[],currentStreamMetadataSource:'',fetch:()=>new Promise(resolve=>requests.push(resolve))};
 vm.createContext(context);vm.runInContext(html.slice(start,end),context);
 const first=context.resolveExtraction(a);context.currentActiveItem=b;const second=context.resolveExtraction(b);
 requests[1]({ok:true,json:async()=>({master_m3u8:'new.m3u8',audio_tracks:[{name:'new audio'}]})});await second;
 requests[0]({ok:true,json:async()=>({master_m3u8:'old.m3u8',audio_tracks:[{name:'old audio'}]})});await first;
 assert.equal(context.currentStreamMetadataSource,'new.m3u8');assert.equal(context.currentStreamAudioTracks[0].name,'new audio');
});
test('an explicitly requested stream wins over the previous pending extraction',()=>{
 const statement=html.match(/const m3u8Source = streamUrl[^;]*;/)[0];
 const ctx={streamUrl:'new.m3u8',pendingExtraction:{m3u8:'old.m3u8'}};
 vm.runInNewContext(statement+'result=m3u8Source;',ctx);assert.equal(ctx.result,'new.m3u8');
});
test('replacing a title aborts extraction and destroys its old HLS loader before resetting the video',()=>{
 const start=html.indexOf('        const target = item || currentActiveItem;',html.indexOf('      async function playDirectly('));
 const end=html.indexOf("        const _nav",start);const log=[];const item={id:'new'};
 const ctx={item,currentActiveItem:{id:'old'},playerLoadRevision:1,AbortController,
 playerExtractionRequest:{abort:()=>log.push('abort')},pendingExtraction:{m3u8:'old'},
 playerContinuity:{destroy:()=>log.push('continuity')},currentHls:{destroy:()=>log.push('hls')},externalSubtitleController:{clear:()=>{}},webIframe:{},resetSubtitleChapters:()=>{},wpConfirmedSync:null,
 webVideo:{pause:()=>log.push('pause'),removeAttribute:()=>log.push('remove-src'),load:()=>log.push('load')}};
 vm.runInNewContext('(function(){'+html.slice(start,end)+'})()',ctx);
 assert.deepEqual(log,['abort','continuity','hls','pause','remove-src','load']);assert.equal(ctx.pendingExtraction,null);assert.equal(ctx.currentHls,null);
});
test('events from a destroyed HLS instance cannot affect the replacement',()=>{
 const start=html.indexOf('          const onCurrentHls ='),end=html.indexOf('          playerContinuity =',start);
 let listener,calls=0;const previous={on:(event,callback)=>listener=callback};
 const ctx={playbackHls:previous,currentHls:previous,loadRevision:1,playerLoadRevision:1,handler:()=>calls++};
 vm.runInNewContext(html.slice(start,end)+"onCurrentHls('manifest',handler);",ctx);
 listener();assert.equal(calls,1);ctx.currentHls={};ctx.playerLoadRevision=2;listener();assert.equal(calls,1);
});
test('restored StreamingCommunity playback keeps the original local proxy on every device',async()=>{
 const start=html.indexOf('      async function resolveExtraction('),end=html.indexOf('      // DIRECT IN-APP',start);
 for(const host of ['localhost','media.example.test']) {
  const item={id:'24932',provider:'streamingcommunity',source_format:'html',watch_url:'https://streaming-community.farm/titles/24932-il-trono-di-spade-streaming/watching?s=4&e=7'};
  const ctx={window:{},location:{hostname:host},currentActiveItem:item,currentStreamProxySource:'',
   currentStreamAudioTracks:[],currentStreamSubtitleTracks:[],currentStreamQualities:[],currentStreamMetadataSource:'',
   fetch:async()=>({ok:true,json:async()=>({master_m3u8:'/api/stream/proxy?url=test',direct_m3u8:'https://cdn.test/master.m3u8'})})};
  vm.createContext(ctx);vm.runInContext(html.slice(start,end),ctx);
  const result=await ctx.resolveExtraction(item);
  assert.equal(result.master_m3u8,'/api/stream/proxy?url=test');
  assert.equal(ctx.currentStreamProxySource,'');
 }
});
