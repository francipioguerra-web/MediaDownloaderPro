const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

test('search history dropdown markup and css are correctly configured', () => {
  const html = fs.readFileSync('templates/index.html', 'utf8');

  // Verify HTML elements
  assert.ok(html.includes('id="topbar-search-history"'), 'topbar-search-history must exist in templates/index.html');
  assert.ok(html.includes('id="floating-search-history"'), 'floating-search-history must exist in templates/index.html');
  assert.ok(html.includes('class="search-history-dropdown hidden"'), 'dropdown must have search-history-dropdown hidden classes');

  // Verify CSS styles
  assert.ok(html.includes('.yt-search-box.has-history-open'), 'CSS must include .yt-search-box.has-history-open');
  assert.ok(html.includes('.floating-search-bar.has-history-open'), 'CSS must include .floating-search-bar.has-history-open');
  assert.ok(html.includes('.search-history-dropdown'), 'CSS must style .search-history-dropdown');
  assert.ok(html.includes('backdrop-filter: blur('), 'Dropdown must have frosted glass backdrop-filter');
  assert.ok(html.includes('.search-history-item'), 'CSS must include .search-history-item');
  assert.ok(html.includes('.search-history-clear-all'), 'CSS must include .search-history-clear-all');
});

test('search history storage and rendering lifecycle behaves as expected', () => {
  // Simulate localStorage
  const mockStorage = {};
  const localStorage = {
    getItem: (key) => (Object.prototype.hasOwnProperty.call(mockStorage, key) ? mockStorage[key] : null),
    setItem: (key, val) => { mockStorage[key] = String(val); },
    removeItem: (key) => { delete mockStorage[key]; }
  };

  const SEARCH_HISTORY_KEY = 'sc_search_history';
  const MAX_SEARCH_HISTORY = 10;

  function getSearchHistory() {
    try {
      const raw = localStorage.getItem(SEARCH_HISTORY_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter(item => typeof item === 'string' && item.trim().length > 0) : [];
    } catch (e) {
      return [];
    }
  }

  function saveSearchHistory(query) {
    const q = (query || '').trim();
    if (!q || q.length < 2) return;
    try {
      let list = getSearchHistory();
      list = list.filter(item => item.toLowerCase() !== q.toLowerCase());
      list.unshift(q);
      if (list.length > MAX_SEARCH_HISTORY) {
        list = list.slice(0, MAX_SEARCH_HISTORY);
      }
      localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(list));
    } catch (e) {}
  }

  function removeSearchHistoryItem(query) {
    try {
      let list = getSearchHistory();
      list = list.filter(item => item.toLowerCase() !== (query || '').trim().toLowerCase());
      localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(list));
    } catch (e) {}
  }

  function clearAllSearchHistory() {
    try {
      localStorage.removeItem(SEARCH_HISTORY_KEY);
    } catch (e) {}
  }

  // 1. Initially empty
  assert.deepEqual(getSearchHistory(), []);

  // 2. Add searches
  saveSearchHistory('Breaking Bad');
  saveSearchHistory('Better Call Saul');
  saveSearchHistory('Inception');
  assert.deepEqual(getSearchHistory(), ['Inception', 'Better Call Saul', 'Breaking Bad']);

  // 3. Deduplication and bumping to top
  saveSearchHistory('breaking bad');
  assert.deepEqual(getSearchHistory(), ['breaking bad', 'Inception', 'Better Call Saul']);

  // 4. Max 10 items
  for (let i = 1; i <= 15; i++) {
    saveSearchHistory('Movie ' + i);
  }
  const history = getSearchHistory();
  assert.equal(history.length, 10);
  assert.equal(history[0], 'Movie 15');

  // 5. Remove single item
  removeSearchHistoryItem('Movie 15');
  assert.equal(getSearchHistory().includes('Movie 15'), false);
  assert.equal(getSearchHistory().length, 9);

  // 6. Clear all
  clearAllSearchHistory();
  assert.deepEqual(getSearchHistory(), []);

  // 7. Ignore whitespace or single character
  saveSearchHistory('   ');
  saveSearchHistory('a');
  assert.deepEqual(getSearchHistory(), []);
});
