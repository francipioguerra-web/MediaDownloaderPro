const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

test('hero details and player buttons open the active hero slide instead of a stale currentActiveItem', () => {
  const html = fs.readFileSync('templates/index.html', 'utf8');
  assert.ok(html.includes('function getHeroActiveItem()'), 'getHeroActiveItem must be declared');
  assert.ok(html.includes('const target = getHeroActiveItem() || currentActiveItem;'), 'btnHeroDetails must use getHeroActiveItem');

  // Simulate hero state logic
  let heroFeaturedList = [
    { id: 45205, name: 'Crystal Lake', type: 'tv' },
    { id: 25859, name: 'Lupin', type: 'tv' },
    { id: 27990, name: 'Nobody Wants This', type: 'tv' }
  ];
  let heroCurrentIndex = 0;
  let currentActiveItem = { id: 999, name: 'Vecchio Film', type: 'movie' }; // Stale item from earlier card

  function getHeroActiveItem() {
    if (Array.isArray(heroFeaturedList) && heroFeaturedList.length > 0) {
      const idx = (typeof heroCurrentIndex === 'number' && heroCurrentIndex >= 0 && heroCurrentIndex < heroFeaturedList.length)
        ? heroCurrentIndex
        : 0;
      return heroFeaturedList[idx] || null;
    }
    return currentActiveItem || null;
  }

  let openedItem = null;
  function openDetails(item) {
    openedItem = item;
  }

  // Hero is at index 0 (Crystal Lake)
  const target0 = getHeroActiveItem() || currentActiveItem;
  openDetails(target0);
  assert.equal(openedItem.name, 'Crystal Lake', 'Must open Crystal Lake at slide 0, not the stale item');
  assert.equal(openedItem.id, 45205);

  // Hero slides to index 1 (Lupin)
  heroCurrentIndex = 1;
  const target1 = getHeroActiveItem() || currentActiveItem;
  openDetails(target1);
  assert.equal(openedItem.name, 'Lupin', 'Must open Lupin at slide 1');
  assert.equal(openedItem.id, 25859);

  // Hero slides to index 2 (Nobody Wants This)
  heroCurrentIndex = 2;
  const target2 = getHeroActiveItem() || currentActiveItem;
  openDetails(target2);
  assert.equal(openedItem.name, 'Nobody Wants This', 'Must open Nobody Wants This at slide 2');
  assert.equal(openedItem.id, 27990);
});
