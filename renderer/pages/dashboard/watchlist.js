/** 自选币列表 */
const watchlistEl = document.getElementById('watchlist');
const klineContainer = document.getElementById('kline-container');
const klineContent = document.getElementById('kline-content');
const klineIntervalBar = document.getElementById('kline-interval-bar');

let currentSymbol = null;
let currentInterval = '1h';
let _klineLoadId = 0;  // 用于忽略过期请求的响应
let _klineAbortController = null;  // 用于取消进行中的请求

const INTERVAL_LABELS = { '1m': '1分钟', '15m': '15分钟', '1h': '1小时', '4h': '4小时', '1d': '1日', '7d': '1周', '30d': '1月' };

window.loadWatchlist = async function () {
  if (!window.api) return;
  try {
    let res = await window.api.dashboard.watchlist();
    let symbols = res.data?.symbols || [];
    let positions = [];
    let tickers = {};
    try {
      const wpRes = await window.api.dashboard.watchlistWithPositions();
      if (wpRes?.data) {
        symbols = wpRes.data.symbols || symbols;
        positions = wpRes.data.positions || [];
        tickers = wpRes.data.tickers || {};
      }
    } catch (_) {}
    const posMap = {};
    positions.forEach(p => { posMap[p.symbol] = p; });
    watchlistEl.innerHTML = symbols.map(s => {
      const pos = posMap[s];
      const tick = tickers[s];
      const posInfo = pos ? ` <small class="pos-info">持仓: ${pos.amount} ≈ ${(pos.value_usdt || 0).toFixed(2)}U</small>` : '';
      const priceInfo = tick?.last ? ` <small class="price-info">${tick.last}</small>` : '';
      return `<div class="watch-item" data-symbol="${s}"><span>${s}${priceInfo}${posInfo}</span><button class="btn-remove">移除</button></div>`;
    }).join('') || '<p class="empty">暂无自选</p>';
    watchlistEl.querySelectorAll('.btn-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = btn.closest('.watch-item');
        const symbol = item?.dataset?.symbol;
        if (symbol) removeFromWatchlist(symbol);
      });
    });
    watchlistEl.querySelectorAll('.watch-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (!e.target.classList.contains('btn-remove')) loadKline(item.dataset.symbol);
      });
    });
  } catch (e) {
    watchlistEl.innerHTML = '<p class="empty">加载失败</p>';
  }
};

async function removeFromWatchlist(symbol) {
  if (!window.api) return;
  try {
    await window.api.dashboard.removeWatchlist(symbol);
    loadWatchlist();
  } catch (e) {
    alert(e.message);
  }
}

function loadKline(symbol, interval) {
  if (!symbol || !window.api) return;

  // 1. 取消上一时段的 K 线主请求
  if (_klineAbortController) {
    _klineAbortController.abort();
    _klineAbortController = null;
  }
  // 2. 停止上一时段实时更新、取消进行中的实时请求、关闭图表、释放上一时段数据
  if (typeof destroyChart === 'function') destroyChart();
  else if (typeof stopRealtimeUpdate === 'function') stopRealtimeUpdate();

  // 3. 立即清空图表区域，去除已显示的数据，释放 DOM 资源
  klineContent.innerHTML = '<p class="kline-loading">加载中...</p>';

  currentSymbol = symbol;
  currentInterval = interval || currentInterval;
  const loadId = ++_klineLoadId;
  const limit = currentInterval === '1m' ? 100 : currentInterval === '30d' ? 100 : 150;
  klineIntervalBar.style.display = 'flex';
  klineIntervalBar.querySelectorAll('.interval-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.interval === currentInterval);
  });

  // 4. 发起新时段请求（带 AbortSignal，切换时可取消）
  _klineAbortController = new AbortController();
  const KLINE_REQ_TIMEOUT_MS = 45000;
  const timeoutPromise = new Promise((_, reject) => {
    setTimeout(() => {
      if (_klineAbortController) _klineAbortController.abort();
      reject(new Error('请求超时'));
    }, KLINE_REQ_TIMEOUT_MS);
  });
  Promise.race([
    window.api.market.candlesticks(symbol, currentInterval, null, null, limit, { signal: _klineAbortController.signal }),
    timeoutPromise,
  ]).then(res => {
    if (loadId !== _klineLoadId) return;  // 已切换其他时段，忽略过期响应
    const data = res.data || [];
    klineContent.innerHTML = `<p class="kline-title">${symbol} K线 (${INTERVAL_LABELS[currentInterval] || currentInterval})</p><div class="kline-chart-wrap"></div>`;
    const chartWrap = klineContent.querySelector('.kline-chart-wrap');
    if (chartWrap && typeof createChart === 'function') {
      try {
        createChart(chartWrap, data, symbol);
        if (loadId === _klineLoadId && typeof startRealtimeUpdate === 'function') {
          startRealtimeUpdate(symbol, currentInterval);
        }
      } catch (e) {
        if (loadId === _klineLoadId) klineContent.innerHTML = `<p class="kline-title">${symbol} K线 (${INTERVAL_LABELS[currentInterval] || currentInterval})</p><p class="kline-loading">图表渲染失败</p>`;
      }
    }
  }).catch((err) => {
    if (loadId !== _klineLoadId) return;
    if (err?.name === 'AbortError') return;  // 用户切换时段主动取消，不提示
    klineContent.innerHTML = `<p class="kline-loading">${symbol} 加载失败${err?.message ? ': ' + err.message : ''}</p>`;
  });
}

klineIntervalBar?.querySelectorAll('.interval-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (currentSymbol) loadKline(currentSymbol, btn.dataset.interval);
  });
});

document.getElementById('btn-refresh-watchlist')?.addEventListener('click', () => loadWatchlist());
document.getElementById('btn-refresh-kline')?.addEventListener('click', () => {
  if (currentSymbol) loadKline(currentSymbol);
});

loadWatchlist();
