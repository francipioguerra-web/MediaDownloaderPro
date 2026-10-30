const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const html=require('node:fs').readFileSync('templates/index.html','utf8');
const start=html.indexOf('      function updatePlayerBuffer()');
const end=html.indexOf('      if (webVideo) {\n        let lastAutoSaveCwTime',start);
function render(duration,ranges,previous='old buffer') {
 const ctx={webVideo:{duration,buffered:{length:ranges.length,start:i=>ranges[i][0],end:i=>ranges[i][1]}},scrubberBuffer:{style:{background:previous}}};
 vm.runInNewContext(html.slice(start,end)+'updatePlayerBuffer();',ctx);
 return ctx.scrubberBuffer.style.background;
}
test('buffer display preserves unloaded gaps after a seek',()=>{
 const background=render(100,[[0,12],[45,60]]);
 assert.match(background,/transparent 12%, transparent 45%/);
 assert.match(background,/rgba\(255,255,255,.42\) 60%, transparent 60%/);
});
test('switching source clears the old buffered indicator',()=>{
 assert.equal(render(NaN,[]),'transparent');
 assert.equal(render(Infinity,[]),'transparent');
 assert.doesNotMatch(render(100,[]),/rgba/);
});
test('rounding outside the media duration never draws beyond the timeline',()=>{
 const background=render(100,[[-.01,100.1]]);
 assert.doesNotMatch(background,/-0.01|100.1/);
 assert.match(background,/rgba\(255,255,255,.42\) 100%/);
});
