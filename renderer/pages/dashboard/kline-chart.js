/** K 线图表 - LightweightCharts，支持增量实时刷新 */
let _chartInstance = null;
let _candlestickSeries = null;
let _volumeSeries = null;
let _priceLine = null;
let _realtimeTimer = null;
let _realtimeSymbol = null;
let _realtimeInterval = null;
let _realtimeAbortController = null;  // 用于取消进行中的实时请求
let _resizeObserver = null;
let _chartData = [];   // 维护的 K 线数据，用于滑动窗口
let _volumeData = [];  // 成交量数据
const REALTIME_INTERVAL_MS = 333;  // 约 1/3 秒

const toTime = (t) => (t || 0) > 1e12 ? Math.floor((t || 0) / 1000) : (t || 0);

function _updatePriceDisplay(price, changePct) {
  const el = document.getElementById('kline-realtime-price');
  if (!el) return;
  if (price == null || price === '') {
    el.textContent = '';
    el.className = 'kline-realtime-price';
    return;
  }
  const p = Number(price);
  const chg = parseFloat(changePct || 0);
  el.textContent = p.toFixed(p >= 1000 ? 2 : 4);
  el.className = 'kline-realtime-price ' + (chg > 0 ? 'up' : chg < 0 ? 'down' : 'flat');
}

function _stopRealtime() {
  if (_realtimeTimer) {
    clearInterval(_realtimeTimer);
    _realtimeTimer = null;
  }
  if (_realtimeAbortController) {
    _realtimeAbortController.abort();
    _realtimeAbortController = null;
  }
  document.removeEventListener('visibilitychange', _onVisibilityChange);
  _realtimeSymbol = null;
  _realtimeInterval = null;
  _updatePriceDisplay(null);
}

async function _fetchLatestAndUpdate() {
  if (!_realtimeSymbol || !_realtimeInterval || !window.api || !_candlestickSeries || !_volumeSeries || !_realtimeAbortController) return;
  if (document.visibilityState === 'hidden') return;  // 页面不可见时跳过，节省请求
  const sig = _realtimeAbortController.signal;
  try {
    const [candleRes, tickerRes] = await Promise.all([
      window.api.market.candlesticks(_realtimeSymbol, _realtimeInterval, null, null, 2, { signal: sig }),
      window.api.dashboard.tickers(_realtimeSymbol, undefined, { signal: sig }),
    ]);
    const candles = candleRes?.data || [];
    const tickerMap = tickerRes?.data || {};
    const ticker = tickerMap[_realtimeSymbol] || tickerMap[_realtimeSymbol?.toUpperCase?.()] || tickerMap[_realtimeSymbol?.toLowerCase?.()];
    const lastPrice = ticker?.last ? parseFloat(ticker.last) : null;
    const changePct = ticker?.change_pct != null ? parseFloat(ticker.change_pct) : 0;

    _updatePriceDisplay(lastPrice, changePct);
    if (lastPrice == null && candles.length > 0) {
      const last = candles[candles.length - 1];
      _updatePriceDisplay(Number(last.close) || 0, 0);
    }

    if (candles.length === 0 || _chartData.length === 0) return;
    const last = candles[candles.length - 1];
    const t = toTime(last.time);
    const o = Number(last.open) || 0;
    const h = Number(last.high) || 0;
    const l = Number(last.low) || 0;
    const c = lastPrice != null ? lastPrice : (Number(last.close) || 0);
    const v = Number(last.volume) || 0;
    if (!t || c <= 0) return;

    const lastChartTime = _chartData[_chartData.length - 1]?.time;
    const isNewCandle = lastChartTime !== t;

    if (isNewCandle) {
      // 新蜡烛出现：前一根已固定，移除最左侧蜡烛释放资源，添加新蜡烛
      _chartData.shift();
      _volumeData.shift();
      _chartData.push({ time: t, open: o, high: h, low: l, close: c, volume: v });
      _volumeData.push({
        time: t,
        value: v,
        color: c >= o ? 'rgba(38, 166, 154, 0.6)' : 'rgba(239, 83, 80, 0.6)',
      });
      _candlestickSeries.setData(_chartData.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));
      _volumeSeries.setData(_volumeData);
    } else {
      // 同一根蜡烛：仅增量更新最后一根
      const idx = _chartData.length - 1;
      _chartData[idx] = { ..._chartData[idx], open: o, high: h, low: l, close: c, volume: v };
      _volumeData[idx] = { time: t, value: v, color: c >= o ? 'rgba(38, 166, 154, 0.6)' : 'rgba(239, 83, 80, 0.6)' };
      _candlestickSeries.update({ time: t, open: o, high: h, low: l, close: c });
      _volumeSeries.update(_volumeData[idx]);
    }

    if (_priceLine) {
      _priceLine.applyOptions({ price: c });
    } else if (_candlestickSeries.createPriceLine) {
      _priceLine = _candlestickSeries.createPriceLine({
        price: c,
        color: c >= o ? '#26a69a' : '#ef5350',
        lineWidth: 1,
        axisLabelVisible: true,
      });
    }
  } catch (e) {
    if (e?.name === 'AbortError') return;  // 切换时段主动取消，忽略
    if (typeof console !== 'undefined' && console.warn) console.warn('[K线] 实时更新失败:', e?.message || e);
  }
}

window.createChart = function createChart(container, data, symbol) {
  if (!container) return;
  if (typeof LightweightCharts === 'undefined') {
    console.warn('LightweightCharts 未加载');
    return;
  }
  _stopRealtime();
  if (_resizeObserver) {
    _resizeObserver.disconnect();
    _resizeObserver = null;
  }
  if (_chartInstance) {
    _chartInstance.remove();
    _chartInstance = null;
  }
  _candlestickSeries = null;
  _volumeSeries = null;
  _priceLine = null;
  _chartData = [];
  _volumeData = [];
  container.innerHTML = '';
  const chartData = (data || []).map(d => ({
    time: toTime(d.time),
    open: Number(d.open) || 0,
    high: Number(d.high) || 0,
    low: Number(d.low) || 0,
    close: Number(d.close) || 0,
    volume: Number(d.volume) || 0,
  })).filter(d => d.time && d.close > 0);
  if (chartData.length === 0) {
    container.innerHTML = '<p class="kline-loading">暂无数据</p>';
    return;
  }

  const chartDiv = document.createElement('div');
  chartDiv.className = 'kline-chart';
  chartDiv.style.width = '100%';
  chartDiv.style.height = '340px';
  container.appendChild(chartDiv);
  const w = chartDiv.clientWidth || container.clientWidth || 600;

  _chartInstance = LightweightCharts.createChart(chartDiv, {
    layout: { background: { color: '#ffffff' }, textColor: '#1a1a2e', attributionLogo: false },
    grid: { vertLines: { color: '#f0f2f5' }, horzLines: { color: '#f0f2f5' } },
    width: w,
    height: 340,
    rightPriceScale: { borderColor: '#e9ecef' },
    timeScale: { borderColor: '#e9ecef', timeVisible: true, secondsVisible: false },
  });

  _candlestickSeries = _chartInstance.addCandlestickSeries({
    upColor: '#26a69a',
    downColor: '#ef5350',
    borderUpColor: '#26a69a',
    borderDownColor: '#ef5350',
    wickUpColor: '#26a69a',
    wickDownColor: '#ef5350',
  });
  _candlestickSeries.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.4 } });
  _chartData = chartData.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume }));
  _volumeData = chartData.map(d => ({
    time: d.time,
    value: d.volume,
    color: d.close >= d.open ? 'rgba(38, 166, 154, 0.6)' : 'rgba(239, 83, 80, 0.6)',
  }));
  _candlestickSeries.setData(_chartData.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));

  _volumeSeries = _chartInstance.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: '',
  });
  _volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.7, bottom: 0 } });
  _volumeSeries.setData(_volumeData);

  _chartInstance.timeScale().fitContent();

  const lastCandle = chartData[chartData.length - 1];
  if (lastCandle && lastCandle.close > 0) {
    _updatePriceDisplay(lastCandle.close, 0);
  }

  if (typeof ResizeObserver !== 'undefined') {
    _resizeObserver = new ResizeObserver(entries => {
      const e = entries[0];
      if (!e || !_chartInstance) return;
      const { width, height } = e.contentRect;
      if (width > 0 && height > 0) _chartInstance.resize(width, height);
    });
    _resizeObserver.observe(chartDiv);
  }
  return { candlestickSeries: _candlestickSeries, volumeSeries: _volumeSeries };
};

window.startRealtimeUpdate = function startRealtimeUpdate(symbol, interval) {
  _stopRealtime();
  _realtimeAbortController = new AbortController();
  _realtimeSymbol = symbol;
  _realtimeInterval = interval;
  _fetchLatestAndUpdate();
  _realtimeTimer = setInterval(_fetchLatestAndUpdate, REALTIME_INTERVAL_MS);
  document.addEventListener('visibilitychange', _onVisibilityChange);
};

function _onVisibilityChange() {
  if (document.visibilityState === 'visible' && _realtimeSymbol) _fetchLatestAndUpdate();
}

window.stopRealtimeUpdate = function stopRealtimeUpdate() {
  _stopRealtime();
};

/** 立即关闭图表、停止实时更新、释放上一时段数据，切换时段时调用 */
window.destroyChart = function destroyChart() {
  _stopRealtime();  // 停止定时器并取消进行中的实时请求
  if (_resizeObserver) {
    _resizeObserver.disconnect();
    _resizeObserver = null;
  }
  if (_chartInstance) {
    _chartInstance.remove();
    _chartInstance = null;
  }
  _candlestickSeries = null;
  _volumeSeries = null;
  _priceLine = null;
  _chartData = [];
  _volumeData = [];
  _updatePriceDisplay(null);
};
