/** K 线图表 - 使用 LightweightCharts 渲染，含成交量 */
let _chartInstance = null;

window.createChart = function createChart(container, data) {
  if (!container || !data || data.length === 0) return;
  if (typeof LightweightCharts === 'undefined') {
    console.warn('LightweightCharts 未加载');
    return;
  }
  if (_chartInstance) {
    _chartInstance.remove();
    _chartInstance = null;
  }
  container.innerHTML = '';
  const toTime = (t) => (t || 0) > 1e12 ? Math.floor((t || 0) / 1000) : (t || 0);
  const chartData = data.map(d => ({
    time: toTime(d.time),
    open: Number(d.open) || 0,
    high: Number(d.high) || 0,
    low: Number(d.low) || 0,
    close: Number(d.close) || 0,
    volume: Number(d.volume) || 0,
  })).filter(d => d.time && d.close > 0);
  if (chartData.length === 0) return;

  const chartDiv = document.createElement('div');
  chartDiv.className = 'kline-chart';
  chartDiv.style.width = '100%';
  chartDiv.style.height = '340px';
  container.appendChild(chartDiv);

  _chartInstance = LightweightCharts.createChart(chartDiv, {
    layout: { background: { color: '#ffffff' }, textColor: '#1a1a2e', attributionLogo: false },
    grid: { vertLines: { color: '#f0f2f5' }, horzLines: { color: '#f0f2f5' } },
    width: chartDiv.clientWidth,
    height: 340,
    rightPriceScale: { borderColor: '#e9ecef' },
    timeScale: { borderColor: '#e9ecef', timeVisible: true, secondsVisible: false },
  });

  const candlestickSeries = _chartInstance.addCandlestickSeries({
    upColor: '#26a69a',
    downColor: '#ef5350',
    borderUpColor: '#26a69a',
    borderDownColor: '#ef5350',
    wickUpColor: '#26a69a',
    wickDownColor: '#ef5350',
  });
  // K 线占上方 60%，为成交量留出底部空间
  candlestickSeries.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.4 } });
  candlestickSeries.setData(chartData.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));

  // 成交量柱状图（overlay 模式）：占底部 30%，涨绿跌红
  const volumeSeries = _chartInstance.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: '',  // 空字符串 = overlay，与 K 线同窗格
  });
  volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.7, bottom: 0 } });
  const volumeData = chartData.map(d => ({
    time: d.time,
    value: d.volume,
    color: d.close >= d.open ? 'rgba(38, 166, 154, 0.6)' : 'rgba(239, 83, 80, 0.6)',
  }));
  volumeSeries.setData(volumeData);

  _chartInstance.timeScale().fitContent();
};
