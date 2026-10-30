const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const html = require('node:fs').readFileSync('templates/index.html', 'utf8');
const start = html.indexOf('      async function resumeFromContinueWatching(cwItem)');
const end = html.indexOf('// TV SERIES: NEXT EPISODE', start);
const source = html.slice(start, end).replace(/\/\/ =+\s*$/, '');
for (const mobile of [true, false]) {
 test(`continue watching resumes the saved episode and time on ${mobile ? 'mobile' : 'desktop'}`, async () => {
  let played;
  const ctx = vm.createContext({String, Number, loadedCatalog: [], currentActiveItem: null,
   window: {matchMedia: () => ({matches: mobile})},
   openDetails: () => {throw Error('Must play directly');},
   playDirectly: async (item, time) => {played = {item, time};}});
  vm.runInContext(source, ctx);
  await ctx.resumeFromContinueWatching({titleId: '42', title: 'Serie', type:'tv',
   current_episode_id:'ep7', current_episode_number:7, current_season_number:2,
   current_watch_url:'/watch/7', currentTime:321});
  assert.equal(played.time,321);
  assert.equal(played.item.current_episode_id,'ep7');
  assert.equal(played.item.current_season_number,2);
  assert.equal(played.item.current_watch_url,'/watch/7');
 });
}
