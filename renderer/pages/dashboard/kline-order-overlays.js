/**
 * K 线：历史成交 Buy/Sell 标记；进行中 bracket 的开仓/止盈/止损线与浅绿/浅红风险区（随周期扩展宽度）
 */
(function () {
  const ACTIVE = new Set(['pending_fill', 'watching', 'closing']);

  let _priceLines = [];
  let _svgLayer = null;
  let _svg = null;
  let _bracketRightState = new Map();
  let _pollTimer = null;
  let _layoutDeb = null;
  let _lastSymbol = '';
  let _lastInterval = '';
  let _lastMarket = 'spot';
  /** 可拖动的止盈/止损价线（与 bracket 跟踪任务同步） */
  let _bracketDragHandles = [];
  let _bracketDragState = null;
  const PERF_BOOST_KEY = 'dashboard_perf_boost_until';

  function shouldPausePolling() {
    if (document.hidden) return true;
    try {
      const until = Number(localStorage.getItem(PERF_BOOST_KEY) || '0');
      return Number.isFinite(until) && until > Date.now();
    } catch (_) {
      return false;
    }
  }

  function barWidthSec(interval) {
    const m = {
      '1m': 60,
      '15m': 900,
      '1h': 3600,
      '4h': 14400,
      '1d': 86400,
      '7d': 604800,
      '30d': 2592000,
    };
    return m[interval] || 3600;
  }

  function floorToBar(tsSec, W) {
    return Math.floor(tsSec / W) * W;
  }

  /** 扩展矩形右边界：先固定 3.5 根 K 线宽；最新 K 线时间 ≥ 右缘−0.5 根宽后，每新增一根 K 线右缘 +1 根宽 */
  function computeRightEdge(trackId, entryBarTime, lastBarTimeSec, W) {
    const initialRight = entryBarTime + 3.5 * W;
    let st = _bracketRightState.get(trackId);
    if (!st) {
      st = { phase: 'fixed', right: initialRight, lastBarKey: floorToBar(lastBarTimeSec, W) };
      _bracketRightState.set(trackId, st);
      if (lastBarTimeSec >= initialRight - 0.5 * W) {
        st.phase = 'extend';
        st.lastBarKey = floorToBar(lastBarTimeSec, W);
      }
      return st.right;
    }
    if (st.phase === 'fixed') {
      st.right = initialRight;
      if (lastBarTimeSec >= initialRight - 0.5 * W) {
        st.phase = 'extend';
        st.lastBarKey = floorToBar(lastBarTimeSec, W);
      }
      return st.right;
    }
    const bk = floorToBar(lastBarTimeSec, W);
    if (bk > st.lastBarKey) {
      const n = Math.round((bk - st.lastBarKey) / W);
      if (n > 0) {
        st.right += n * W;
        st.lastBarKey = bk;
      }
    }
    return st.right;
  }

  function tradeTimeToUnix(t) {
    if (t == null || t === '') return null;
    const n = Number(t);
    if (!Number.isFinite(n)) return null;
    return n > 1e12 ? Math.floor(n / 1000) : Math.floor(n);
  }

  function parseCreatedAt(iso) {
    if (!iso) return null;
    const ms = Date.parse(String(iso));
    return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
  }

  function parsePx(s) {
    const v = parseFloat(String(s || '').replace(/,/g, '').trim());
    return Number.isFinite(v) && v > 0 ? v : NaN;
  }

  function fmtPriceStr(ref, x) {
    if (!Number.isFinite(x) || x <= 0) return '';
    const r = Number(ref);
    const d = !Number.isFinite(r) || r <= 0 ? 4 : r >= 1000 ? 2 : r >= 1 ? 4 : 6;
    let t = x.toFixed(d);
    if (d > 2) t = t.replace(/\.?0+$/, '');
    return t;
  }

  function clampBracketDrag(side, kind, entry, raw) {
    if (!Number.isFinite(entry) || entry <= 0 || !Number.isFinite(raw) || raw <= 0) return raw;
    const eps = Math.max(entry * 1e-10, 1e-12);
    if (String(side || '').toLowerCase() === 'buy') {
      if (kind === 'tp') return Math.max(raw, entry + eps);
      return Math.min(raw, entry - eps);
    }
    if (kind === 'tp') return Math.min(raw, entry - eps);
    return Math.max(raw, entry + eps);
  }

  function pickDragHandle(clientY, clientX) {
    const series = window.__klineLw?.candleSeries;
    const chartDiv = window.__klineLw?.container;
    if (!series || !chartDiv || !_bracketDragHandles.length) return null;
    const rect = chartDiv.getBoundingClientRect();
    const y = clientY - rect.top;
    const x = clientX - rect.left;
    if (x < 0 || y < 0 || x > rect.width || y > rect.height) return null;
    let best = null;
    let bestD = 14;
    _bracketDragHandles.forEach((h) => {
      const cy = series.priceToCoordinate(h.price);
      if (cy == null) return;
      const d = Math.abs(cy - y);
      if (d < bestD) {
        bestD = d;
        best = h;
      }
    });
    return best;
  }

  function onBracketDragMove(ev) {
    if (!_bracketDragState) return;
    const series = window.__klineLw?.candleSeries;
    const chartDiv = window.__klineLw?.container;
    if (!series || !chartDiv) return;
    const rect = chartDiv.getBoundingClientRect();
    const y = ev.clientY - rect.top;
    let np = series.coordinateToPrice(y);
    if (np != null && typeof np === 'object' && np !== null && 'close' in np) {
      np = /** @type {{ close?: number }} */ (np).close;
    }
    if (np == null || typeof np !== 'number' || !Number.isFinite(np)) return;
    const h = _bracketDragState.handle;
    np = clampBracketDrag(h.side, h.kind, h.entryRef, np);
    h.price = np;
    try {
      h.line.applyOptions({ price: np });
    } catch (_) {}
    ev.preventDefault();
  }

  async function onBracketDragUp(ev) {
    if (!_bracketDragState) return;
    const st = _bracketDragState;
    _bracketDragState = null;
    window.removeEventListener('pointermove', onBracketDragMove, true);
    window.removeEventListener('pointerup', onBracketDragUp, true);
    window.removeEventListener('pointercancel', onBracketDragUp, true);
    const chartDiv = window.__klineLw?.container;
    if (chartDiv) {
      try {
        chartDiv.releasePointerCapture(st.pointerId);
      } catch (_) {}
    }
    const h = st.handle;
    const body =
      h.kind === 'tp'
        ? { take_profit_price: fmtPriceStr(h.entryRef, h.price) }
        : { stop_loss_price: fmtPriceStr(h.entryRef, h.price) };
    if (!window.api?.trading?.updateBracketTrack) return;
    try {
      await window.api.trading.updateBracketTrack(h.trackId, body);
      try {
        window.dispatchEvent(new CustomEvent('dashboard-bracket-refresh'));
      } catch (_) {}
    } catch (e) {
      try {
        alert(e?.message || '同步止盈/止损失败');
      } catch (_) {}
      scheduleRefresh();
    }
    ev.preventDefault();
  }

  function onBracketPointerDown(ev) {
    if (ev.button !== 0 || _bracketDragState) return;
    const h = pickDragHandle(ev.clientY, ev.clientX);
    if (!h) return;
    ev.preventDefault();
    ev.stopPropagation();
    const chartDiv = window.__klineLw?.container;
    if (!chartDiv) return;
    _bracketDragState = { handle: h, pointerId: ev.pointerId };
    try {
      chartDiv.setPointerCapture(ev.pointerId);
    } catch (_) {}
    window.addEventListener('pointermove', onBracketDragMove, true);
    window.addEventListener('pointerup', onBracketDragUp, true);
    window.addEventListener('pointercancel', onBracketDragUp, true);
  }

  function ensureBracketDragListener(chartDiv) {
    if (!chartDiv || chartDiv.__klineBracketDragBound) return;
    chartDiv.__klineBracketDragBound = true;
    chartDiv.addEventListener('pointerdown', onBracketPointerDown, true);
  }

  function clearPriceLines() {
    const series = window.__klineLw?.candleSeries;
    if (!series) {
      _priceLines = [];
      return;
    }
    _priceLines.forEach((l) => {
      try {
        series.removePriceLine(l);
      } catch (_) {}
    });
    _priceLines = [];
  }

  function ensureSvgLayer(chartDiv) {
    if (!chartDiv) return null;
    let layer = chartDiv.querySelector('.kline-order-svg-layer');
    if (!layer) {
      layer = document.createElement('div');
      layer.className = 'kline-order-svg-layer';
      layer.style.cssText =
        'position:absolute;inset:0;pointer-events:none;z-index:1;overflow:hidden;border-radius:inherit;';
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '100%');
      svg.setAttribute('height', '100%');
      svg.setAttribute('preserveAspectRatio', 'none');
      layer.appendChild(svg);
      chartDiv.style.position = chartDiv.style.position || 'relative';
      chartDiv.insertBefore(layer, chartDiv.firstChild);
    }
    _svgLayer = layer;
    _svg = layer.querySelector('svg');
    return _svg;
  }

  function clearSvg() {
    if (_svg) _svg.innerHTML = '';
  }

  function boxCoords(chart, series, t1, t2, pHigh, pLow) {
    const x1 = chart.timeScale().timeToCoordinate(t1);
    const x2 = chart.timeScale().timeToCoordinate(t2);
    const yHi = series.priceToCoordinate(pHigh);
    const yLo = series.priceToCoordinate(pLow);
    if (x1 == null || x2 == null || yHi == null || yLo == null) return null;
    const x = Math.min(x1, x2);
    const w = Math.max(2, Math.abs(x2 - x1));
    const y = Math.min(yHi, yLo);
    const h = Math.max(2, Math.abs(yLo - yHi));
    return { x, y, w, h };
  }

  function drawRect(svg, attrs) {
    const r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    Object.entries(attrs).forEach(([k, v]) => r.setAttribute(k, String(v)));
    svg.appendChild(r);
  }

  async function getMode() {
    try {
      if (window.api?.broker?.status) {
        const r = await window.api.broker.status();
        return r?.data?.current_mode || 'real';
      }
    } catch (_) {}
    return window._klineApiMode || 'real';
  }

  function pruneBracketState(activeIds) {
    const keep = new Set(activeIds.map(String));
    Array.from(_bracketRightState.keys()).forEach((k) => {
      if (!keep.has(String(k))) _bracketRightState.delete(k);
    });
  }

  async function fetchOverlayData(symbol, mode) {
    const tradesP = window.api?.trading?.trades
      ? window.api.trading.trades(mode, symbol, 1, 200).catch(() => ({ data: { list: [] } }))
      : Promise.resolve({ data: { list: [] } });
    const tracksP = window.api?.trading?.bracketTracks
      ? window.api.trading.bracketTracks(80).catch(() => ({ data: { list: [] } }))
      : Promise.resolve({ data: { list: [] } });
    const [trRes, brRes] = await Promise.all([tradesP, tracksP]);
    const trades = trRes?.data?.list || [];
    const tracks = (brRes?.data?.list || []).filter(
      (t) => String(t.symbol || '').toUpperCase() === String(symbol || '').toUpperCase()
    );
    return { trades, tracks };
  }

  function buildTradeMarkers(trades, sym, interval) {
    const W = barWidthSec(interval || '1h');
    const markers = [];
    const su = String(sym || '').toUpperCase();
    trades.forEach((tr) => {
      if (String(tr.symbol || '').toUpperCase() !== su) return;
      const t = tradeTimeToUnix(tr.create_time);
      if (t == null) return;
      const barT = floorToBar(t, W);
      const side = String(tr.side || '').toLowerCase();
      const isBuy = side === 'buy';
      markers.push({
        time: barT,
        position: isBuy ? 'belowBar' : 'aboveBar',
        color: isBuy ? '#26a69a' : '#ef5350',
        shape: isBuy ? 'arrowUp' : 'arrowDown',
        text: isBuy ? 'Buy' : 'Sell',
      });
    });
    markers.sort((a, b) => a.time - b.time);
    return markers;
  }

  async function refreshKlineOrderOverlays(symbol, interval, market) {
    const chart = window.__klineLw?.chart;
    const series = window.__klineLw?.candleSeries;
    const chartDiv = window.__klineLw?.container;
    if (!chart || !series || !symbol) {
      clearPriceLines();
      clearSvg();
      return;
    }

    _lastSymbol = symbol;
    _lastInterval = interval || '1h';
    _lastMarket = market || 'spot';
    if (_lastMarket !== 'spot') {
      clearPriceLines();
      clearSvg();
      series.setMarkers([]);
      return;
    }

    const mode = await getMode();
    let trades;
    let tracks;
    try {
      const d = await fetchOverlayData(symbol, mode);
      trades = d.trades;
      tracks = d.tracks;
    } catch (_) {
      return;
    }

    const markers = buildTradeMarkers(trades, symbol, interval || '1h');
    series.setMarkers(markers);

    clearPriceLines();
    _bracketDragHandles = [];
    const svg = ensureSvgLayer(chartDiv);
    clearSvg();
    ensureBracketDragListener(chartDiv);

    const W = barWidthSec(interval || '1h');
    const data = window._klineChartDataSnapshot || [];
    const lastBarTime =
      data.length > 0 ? data[data.length - 1].time : Math.floor(Date.now() / 1000);

    const activeTracks = tracks.filter((tr) => ACTIVE.has(String(tr.status || '')));
    pruneBracketState(activeTracks.map((t) => t.id));

    const chartForSub = chart;
    if (chartForSub && !chartForSub.__klineOrderRangeSub) {
      chartForSub.__klineOrderRangeSub = true;
      chartForSub.timeScale().subscribeVisibleTimeRangeChange(() => {
        clearTimeout(_layoutDeb);
        _layoutDeb = setTimeout(() => scheduleRefresh(), 100);
      });
    }

    activeTracks.forEach((tr) => {
      const entryPx = parsePx(tr.price);
      const tpPx = parsePx(tr.take_profit_price);
      const slPx = parsePx(tr.stop_loss_price);
      const entryRef = parsePx(tr.entry_fill_price) || entryPx;
      const created = parseCreatedAt(tr.created_at) || lastBarTime;
      const entryBarT = floorToBar(created, W);
      const rightT = computeRightEdge(tr.id, entryBarT, lastBarTime, W);
      const side = String(tr.side || '').toLowerCase();

      if (Number.isFinite(entryPx)) {
        try {
          _priceLines.push(
            series.createPriceLine({
              price: entryPx,
              color: '#212121',
              lineWidth: 1,
              lineStyle: 0,
              axisLabelVisible: true,
            })
          );
        } catch (_) {}
      }
      if (Number.isFinite(tpPx)) {
        try {
          const pl = series.createPriceLine({
            price: tpPx,
            color: '#2e7d32',
            lineWidth: 2,
            lineStyle: 2,
            axisLabelVisible: true,
            title: '止盈 · 拖动改价',
          });
          _priceLines.push(pl);
          if (Number.isFinite(entryRef)) {
            _bracketDragHandles.push({
              line: pl,
              trackId: tr.id,
              kind: 'tp',
              side,
              entryRef,
              price: tpPx,
            });
          }
        } catch (_) {}
      }
      if (Number.isFinite(slPx)) {
        try {
          const pl = series.createPriceLine({
            price: slPx,
            color: '#c62828',
            lineWidth: 2,
            lineStyle: 2,
            axisLabelVisible: true,
            title: '止损 · 拖动改价',
          });
          _priceLines.push(pl);
          if (Number.isFinite(entryRef)) {
            _bracketDragHandles.push({
              line: pl,
              trackId: tr.id,
              kind: 'sl',
              side,
              entryRef,
              price: slPx,
            });
          }
        } catch (_) {}
      }

      if (!svg || !Number.isFinite(entryPx)) return;

      if (side === 'buy') {
        if (Number.isFinite(tpPx) && tpPx > entryPx) {
          const b = boxCoords(chart, series, entryBarT, rightT, tpPx, entryPx);
          if (b)
            drawRect(svg, {
              x: b.x,
              y: b.y,
              width: b.w,
              height: b.h,
              fill: 'rgba(38, 166, 154, 0.08)',
              stroke: 'none',
            });
        }
        if (Number.isFinite(slPx) && slPx < entryPx) {
          const b = boxCoords(chart, series, entryBarT, rightT, entryPx, slPx);
          if (b)
            drawRect(svg, {
              x: b.x,
              y: b.y,
              width: b.w,
              height: b.h,
              fill: 'rgba(239, 83, 80, 0.08)',
              stroke: 'none',
            });
        }
      } else if (side === 'sell') {
        if (Number.isFinite(tpPx) && tpPx < entryPx) {
          const b = boxCoords(chart, series, entryBarT, rightT, entryPx, tpPx);
          if (b)
            drawRect(svg, {
              x: b.x,
              y: b.y,
              width: b.w,
              height: b.h,
              fill: 'rgba(38, 166, 154, 0.08)',
              stroke: 'none',
            });
        }
        if (Number.isFinite(slPx) && slPx > entryPx) {
          const b = boxCoords(chart, series, entryBarT, rightT, slPx, entryPx);
          if (b)
            drawRect(svg, {
              x: b.x,
              y: b.y,
              width: b.w,
              height: b.h,
              fill: 'rgba(239, 83, 80, 0.08)',
              stroke: 'none',
            });
        }
      }
    });
  }

  function abortBracketDrag() {
    if (!_bracketDragState) return;
    const st = _bracketDragState;
    _bracketDragState = null;
    window.removeEventListener('pointermove', onBracketDragMove, true);
    window.removeEventListener('pointerup', onBracketDragUp, true);
    window.removeEventListener('pointercancel', onBracketDragUp, true);
    const chartDiv = window.__klineLw?.container;
    if (chartDiv) {
      try {
        chartDiv.releasePointerCapture(st.pointerId);
      } catch (_) {}
    }
  }

  function clearKlineOrderOverlays() {
    abortBracketDrag();
    _bracketDragHandles = [];
    clearPriceLines();
    clearSvg();
    _bracketRightState.clear();
    const series = window.__klineLw?.candleSeries;
    if (series) {
      try {
        series.setMarkers([]);
      } catch (_) {}
    }
    if (_pollTimer) {
      clearInterval(_pollTimer);
      _pollTimer = null;
    }
  }

  function scheduleRefresh() {
    if (!_lastSymbol) return;
    refreshKlineOrderOverlays(_lastSymbol, _lastInterval, _lastMarket);
  }

  /** 供 kline-chart 在维护 _chartData 时同步一份时间戳供 overlay 计算右边界 */
  window._klineSyncChartDataSnapshot = function (arr) {
    try {
      window._klineChartDataSnapshot = (arr || []).map((d) => ({ time: d.time }));
    } catch (_) {
      window._klineChartDataSnapshot = [];
    }
  };

  window.refreshKlineOrderOverlays = function (symbol, interval, market) {
    refreshKlineOrderOverlays(symbol, interval, market);
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(() => {
      if (shouldPausePolling()) return;
      if (window.getDashboardCurrentSymbol?.() === symbol) scheduleRefresh();
    }, 12000);
  };

  window.clearKlineOrderOverlays = clearKlineOrderOverlays;

  window.addEventListener('dashboard-kline-layout', () => scheduleRefresh());
  window.addEventListener('dashboard-kline-new-bar', () => scheduleRefresh());
  window.addEventListener('dashboard-bracket-refresh', () => scheduleRefresh());

  window.addEventListener('dashboard-kline-ready', () => {
    const sym = window.getDashboardCurrentSymbol?.();
    const iv = window.getDashboardCurrentInterval?.() || '1h';
    const m = window.getDashboardQuoteMarket?.() === 'futures' ? 'futures' : 'spot';
    if (sym) refreshKlineOrderOverlays(sym, iv, m);
  });
})();
