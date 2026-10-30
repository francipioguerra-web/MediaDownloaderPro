const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('templates/index.html','utf8');
const helper = source.slice(source.indexOf('      let detailPresentationRevision = 0;'),source.indexOf('      async function updateDetailLogo'));
(async () => {
  for (const [history, expected, next] of [
    [[], 'Riproduci primo episodio'],
    [[{titleId:'42',current_episode_id:'e2',current_episode_number:2,current_season_number:1,currentTime:120,duration:2400}], 'Riprendi'],
    [[{titleId:'42',current_episode_id:'e2',current_episode_number:2,current_season_number:1,currentTime:2300,duration:2400}], 'Riproduci episodio 3', 3]
  ]) {
    let label;
    const context = vm.createContext({Map, Number, String, encodeURIComponent,
      btnModalPlayerOpen:{querySelector:()=>({set textContent(v){label=v;}}),setAttribute(){}},
      getContinueWatchingList: async()=>history,
      fetch:async()=>({json:async()=>({success:true,episodes:[{id:'e3',number:3,name:'Tre',watch_url:'/ep3'}]})})});
    vm.runInContext(helper,context);
    context.item={id:'42',type:'tv',seasons:[{number:1}]};
    await vm.runInContext('updateDetailPlayback(item,0)',context);
    assert.equal(label,expected);
    if(next) { assert.equal(context.item.current_episode_number,next); assert.equal(context.item.currentTime,0); }
  }
  console.log('3 playback states passed');
})();
