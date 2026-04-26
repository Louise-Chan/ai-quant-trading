/** 自选币列表 */
const watchlistEl = document.getElementById('watchlist');
const klineContainer = document.getElementById('kline-container');
const klineContent = document.getElementById('kline-content');
const klineIntervalBar = document.getElementById('kline-interval-bar');

let currentSymbol = null;
let currentInterval = '1h';
/** 当前 K 线行情类型：spot 现货 API，futures 合约 U 本位 */
window._klineQuoteMarket = window._klineQuoteMarket || 'spot';
let _klineLoadId = 0;  // 用于忽略过期请求的响应
let _klineAbortController = null;  // 用于取消进行中的请求

async function getDashboardMode() {
  try {
    const local = window.electronAPI ? (await window.electronAPI.store.get('trading_mode')) : localStorage.getItem('trading_mode');
    if (local) return local;
  } catch (_) {}
  try {
    if (window.api?.broker?.status) {
      const res = await window.api.broker.status();
      return res?.data?.current_mode || 'real';
    }
  } catch (_) {}
  try {
    return window.electronAPI ? (await window.electronAPI.store.get('trading_mode')) : (localStorage.getItem('trading_mode') || 'real');
  } catch (_) {
    return 'real';
  }
}

const INTERVAL_LABELS = { '1m': '1分钟', '15m': '15分钟', '1h': '1小时', '4h': '4小时', '1d': '1日', '7d': '1周', '30d': '1月' };

function quoteMarketLabel(qm) {
  const x = (qm || 'spot').toLowerCase();
  if (x === 'futures') return '合约';
  if (x === 'option') return '期权';
  return '现货';
}

window.loadWatchlist = async function () {
  if (!window.api) return;
  try {
    let res = await window.api.dashboard.watchlist();
    let items = res.data?.items;
    let symbols = res.data?.symbols || [];
    if (!items?.length && symbols.length) {
      items = symbols.map((s) => ({ symbol: s, quote_market: 'spot' }));
    }
    let positions = [];
    let tickers = {};
    try {
      const wpRes = await window.api.dashboard.watchlistWithPositions();
      if (wpRes?.data) {
        if (wpRes.data.items?.length) items = wpRes.data.items;
        else if (wpRes.data.symbols?.length) {
          symbols = wpRes.data.symbols;
          items = symbols.map((s) => ({ symbol: s, quote_market: 'spot' }));
        }
        positions = wpRes.data.positions || [];
        tickers = wpRes.data.tickers || {};
      }
    } catch (_) {}
    const posMap = {};
    positions.forEach(p => { posMap[p.symbol] = p; });
    watchlistEl.innerHTML = (items || []).map((it) => {
      const s = it.symbol;
      const qm = it.quote_market || 'spot';
      const tkey = `${s}@${qm}`;
      const pos = posMap[s];
      const tick = tickers[tkey] || tickers[s];
      const posInfo = qm === 'spot' && pos ? ` <small class="pos-info">持仓: ${pos.amount} ≈ ${(pos.value_usdt || 0).toFixed(2)}U</small>` : '';
      const priceInfo = tick?.last ? ` <small class="price-info">${tick.last}</small>` : '';
      const typeTag = `<span class="watch-market-tag">${quoteMarketLabel(qm)}</span>`;
      return `<div class="watch-item" data-symbol="${s}" data-quote-market="${qm}"><span>${typeTag} ${s}${priceInfo}${posInfo}</span><button class="btn-remove">移除</button></div>`;
    }).join('') || '<p class="empty">暂无自选</p>';
    watchlistEl.querySelectorAll('.btn-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = btn.closest('.watch-item');
        const symbol = item?.dataset?.symbol;
        const qm = item?.dataset?.quoteMarket || 'spot';
        if (symbol) removeFromWatchlist(symbol, qm);
      });
    });
    watchlistEl.querySelectorAll('.watch-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (!e.target.classList.contains('btn-remove')) {
          const qm = item.dataset.quoteMarket || 'spot';
          window._klineQuoteMarket = qm === 'futures' ? 'futures' : 'spot';
          loadKline(item.dataset.symbol);
        }
      });
    });
    try {
      window.__onWatchlistCountUpdated?.((items || []).length);
    } catch (_) {}
  } catch (e) {
    watchlistEl.innerHTML = '<p class="empty">加载失败</p>';
  }
};

async function removeFromWatchlist(symbol, quoteMarket) {
  if (!window.api) return;
  try {
    await window.api.dashboard.removeWatchlist(symbol, quoteMarket || 'spot');
    loadWatchlist();
  } catch (e) {
    alert(e.message);
  }
}

function loadKline(symbol, interval, options) {
  if (!symbol || !window.api) return;
  const quoteMarket = (options && options.market) || window._klineQuoteMarket || 'spot';

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
  window._klineQuoteMarket = quoteMarket;
  const loadId = ++_klineLoadId;
  const limit = currentInterval === '1m' ? 100 : currentInterval === '30d' ? 100 : 150;
  klineIntervalBar.style.display = 'flex';
  klineIntervalBar.querySelectorAll('.interval-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.interval === currentInterval);
  });

  // 4. 发起新时段请求：每个加载使用独立 AbortController（避免 await 后全局变量已被下一次点击替换）
  const ac = new AbortController();
  _klineAbortController = ac;
  const KLINE_REQ_TIMEOUT_MS = 15000;
  let timeoutHandle = null;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutHandle = setTimeout(() => {
      /* 仅中止本批次；勿动全局 _klineAbortController，否则 45s 后会误杀新标的的请求 */
      if (loadId !== _klineLoadId) return;
      ac.abort();
      reject(new Error('请求超时'));
    }, KLINE_REQ_TIMEOUT_MS);
  });

  (async () => {
    let mode = 'real';
    try {
      mode = await getDashboardMode();
    } catch (_) {}
    if (loadId !== _klineLoadId) return;
    window._klineApiMode = mode;
    const tag = quoteMarket === 'futures' ? '合约' : '现货';
    try {
      const res = await Promise.race([
        window.api.market.candlesticks(symbol, currentInterval, null, null, limit, {
          signal: ac.signal,
          market: quoteMarket === 'futures' ? 'futures' : 'spot',
          mode,
        }),
        timeoutPromise,
      ]);
      if (timeoutHandle) clearTimeout(timeoutHandle);
      if (loadId !== _klineLoadId) return;
      const data = res.data || [];
      klineContent.innerHTML = `<p class="kline-title">${escHtml(symbol)} <small class="kline-market-tag">${tag}</small> · K线 (${INTERVAL_LABELS[currentInterval] || currentInterval})</p><div class="kline-chart-wrap"></div>`;
      const chartWrap = klineContent.querySelector('.kline-chart-wrap');
      if (chartWrap && typeof createChart === 'function') {
        try {
          createChart(chartWrap, data, symbol);
          if (loadId === _klineLoadId && typeof startRealtimeUpdate === 'function') {
            startRealtimeUpdate(symbol, currentInterval, quoteMarket === 'futures' ? 'futures' : 'spot');
          }
          try {
            window.dispatchEvent(new CustomEvent('dashboard-kline-symbol'));
          } catch (_) {}
          try {
            if (typeof window.refreshKlineOrderOverlays === 'function') {
              window.refreshKlineOrderOverlays(
                symbol,
                currentInterval,
                quoteMarket === 'futures' ? 'futures' : 'spot'
              );
            }
          } catch (_) {}
        } catch (e) {
          if (loadId === _klineLoadId) {
            klineContent.innerHTML = `<p class="kline-title">${escHtml(symbol)} · K线 (${INTERVAL_LABELS[currentInterval] || currentInterval})</p><p class="kline-loading">图表渲染失败</p>`;
          }
        }
      }
    } catch (err) {
      if (timeoutHandle) clearTimeout(timeoutHandle);
      if (loadId !== _klineLoadId) return;
      if (err?.name === 'AbortError') return;
      klineContent.innerHTML = `<p class="kline-loading">${escHtml(symbol)} 加载失败${err?.message ? ': ' + escHtml(String(err.message)) : ''}</p>`;
    }
  })();
}

function escHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 从行情表点击：现货 / 合约 */
window.loadKlineFromQuote = function (symbol, marketKind) {
  if (!symbol) return;
  window._klineQuoteMarket = marketKind === 'futures' ? 'futures' : 'spot';
  loadKline(symbol);
};

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

/** 供订单审核等模块读取当前 K 线交易对 */
window.getDashboardCurrentSymbol = function () {
  return currentSymbol;
};

/** 供订单审核与 K 线周期对齐 */
window.getDashboardCurrentInterval = function () {
  return currentInterval || '1h';
};

window.getDashboardQuoteMarket = function () {
  return window._klineQuoteMarket || 'spot';
};
