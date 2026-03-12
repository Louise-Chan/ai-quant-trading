/** 智能选币 */
const searchEl = document.getElementById('coin-search');
const listEl = document.getElementById('coin-list');

async function loadCoins(keyword = '', page = 1) {
  if (!window.api) return;
  try {
    const res = await window.api.dashboard.coins(keyword, page, 50);
    const list = res.data?.list || [];
    listEl.innerHTML = list.map(p => `
      <div class="coin-item" data-symbol="${p.symbol || ''}">
        <span>${p.symbol || '-'}</span>
        <button class="btn-add">+ 自选</button>
      </div>
    `).join('');
    listEl.querySelectorAll('.btn-add').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = btn.closest('.coin-item');
        const symbol = item?.dataset?.symbol;
        if (symbol) addToWatchlist(symbol);
      });
    });
  } catch (e) {
    listEl.innerHTML = '<p class="empty">加载失败</p>';
  }
}

async function addToWatchlist(symbol) {
  if (!window.api) return;
  try {
    await window.api.dashboard.addWatchlist(symbol);
    if (window.loadWatchlist) window.loadWatchlist();
  } catch (e) {
    alert(e.message);
  }
}

let debounceTimer;
searchEl?.addEventListener('input', () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => loadCoins(searchEl.value), 300);
});

document.getElementById('btn-refresh-coins')?.addEventListener('click', () => loadCoins(searchEl?.value || ''));

loadCoins();
