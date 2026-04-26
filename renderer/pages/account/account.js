/** 账户总览 - 模拟/实盘切换时实时刷新 */
const NA = '--';  // 暂无数据时显示
const ACCOUNT_SCOPE_KEY = 'dashboard_nav_account_scope';

let _navChart = null;
let _navSeries = null;

function destroyNavChart() {
  if (_navChart) {
    try { _navChart.remove(); } catch (_) {}
  }
  _navChart = null;
  _navSeries = null;
}

function renderNavChart(points, opts) {
  const host = document.getElementById('nav-chart');
  const capEl = document.getElementById('nav-chart-caption');
  if (!host) return;
  const arr = Array.isArray(points) ? points.filter(p => Number.isFinite(Number(p?.nav))) : [];
  if (!arr.length || typeof LightweightCharts === 'undefined') {
    destroyNavChart();
    host.classList.remove('has-data');
    host.innerHTML = `<p class="chart-placeholder">${opts?.placeholder || NA}</p>`;
    if (capEl) { capEl.style.display = 'none'; capEl.textContent = ''; }
    return;
  }
  destroyNavChart();
  host.innerHTML = '<div class="nav-chart-canvas"></div>';
  host.classList.add('has-data');
  const canvas = host.querySelector('.nav-chart-canvas');
  _navChart = LightweightCharts.createChart(canvas, {
    layout: {
      background: { color: '#f8f9fa' },
      textColor: '#1a1a2e',
      attributionLogo: false,
    },
    grid: { vertLines: { color: '#e9ecef' }, horzLines: { color: '#e9ecef' } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
    width: canvas.clientWidth || 600,
    height: 260,
  });
  _navSeries = _navChart.addAreaSeries({
    lineColor: '#e6ac00',
    topColor: 'rgba(255, 193, 7, 0.35)',
    bottomColor: 'rgba(255, 193, 7, 0.02)',
    lineWidth: 2,
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
  });
  const seen = new Set();
  const data = [];
  for (const p of arr) {
    const t = Number(p.t || p.ts || 0);
    if (!Number.isFinite(t) || t <= 0 || seen.has(t)) continue;
    seen.add(t);
    data.push({ time: t, value: Number(p.nav) });
  }
  data.sort((a, b) => a.time - b.time);
  if (!data.length) {
    destroyNavChart();
    host.classList.remove('has-data');
    host.innerHTML = `<p class="chart-placeholder">${opts?.placeholder || NA}</p>`;
    if (capEl) { capEl.style.display = 'none'; capEl.textContent = ''; }
    return;
  }
  _navSeries.setData(data);
  _navChart.timeScale().fitContent();
  if (capEl) {
    const caption = opts?.caption || '';
    capEl.style.display = caption ? 'block' : 'none';
    capEl.textContent = caption;
  }
  window.addEventListener('resize', () => {
    if (_navChart && canvas) {
      try { _navChart.applyOptions({ width: canvas.clientWidth || 600 }); } catch (_) {}
    }
  }, { once: true });
}

async function queryMirrorStatus() {
  if (!window.api?.simulatedMirror?.status) return null;
  try {
    const res = await window.api.simulatedMirror.status();
    const d = res?.data || {};
    return d.enabled && d.backtest_run_id ? d : null;
  } catch (_) {
    return null;
  }
}

function getAccountScope() {
  try {
    return localStorage.getItem(ACCOUNT_SCOPE_KEY) === 'futures' ? 'futures' : 'spot';
  } catch (_) {
    return 'spot';
  }
}
function fmt(v, type) {
  if (v === null || v === undefined) return NA;
  if (type === 'pct') return (v * 100).toFixed(2) + '%';
  if (type === 'num4') return Number(v).toFixed(4);
  if (type === 'num2') return Number(v).toFixed(2);
  return String(v);
}

let _lastToast = 0;
function showToast(msg, duration = 3000) {
  if (Date.now() - _lastToast < 2000) return;  // 2 秒内不重复弹
  _lastToast = Date.now();
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.remove(); }, duration);
}

let _mirrorDefaultApplied = false;

async function refreshAll() {
  await loadBrokerStatus();
  const mirror = await queryMirrorStatus();
  if (mirror && !_mirrorDefaultApplied) {
    const openBtn = document.querySelector('.filter-btn[data-status="open"]');
    const finBtn = document.querySelector('.filter-btn[data-status="finished"]');
    if (openBtn && finBtn) {
      openBtn.classList.remove('active');
      finBtn.classList.add('active');
      _mirrorDefaultApplied = true;
    }
  } else if (!mirror) {
    _mirrorDefaultApplied = false;
  }
  const mode = currentMode;
  loadPortfolio(mode);
  loadBalance(mode);
  loadOrders(mode);
  const tab = document.querySelector('.tab.active');
  if (tab?.dataset?.tab === 'positions') loadPositions(mode);
}

let currentMode = 'simulated';
async function loadBrokerStatus() {
  if (!window.api) return;
  try {
    const res = await window.api.broker.status();
    currentMode = res.data?.current_mode || 'simulated';
    const modeLabel = document.getElementById('account-mode-label');
    if (modeLabel) modeLabel.textContent = currentMode === 'real' ? '实盘账户' : '模拟账户';
  } catch (_) {}
}

async function loadPortfolio(mode) {
  if (!window.api) return;
  const el = document.getElementById('portfolio-summary');
  const emptyHtml = `<div class="stat"><span>初始资金</span><strong>${NA}</strong></div><div class="stat"><span>当前净值</span><strong>${NA}</strong></div><div class="stat"><span>累计收益</span><strong>${NA}</strong></div><div class="stat"><span>年化收益</span><strong>${NA}</strong></div><div class="stat"><span>最大回撤</span><strong>${NA}</strong></div><div class="stat"><span>夏普比率</span><strong>${NA}</strong></div><div class="stat"><span>Beta</span><strong>${NA}</strong></div><div class="stat"><span>Alpha</span><strong>${NA}</strong></div>`;
  try {
    const res = await window.api.portfolio.summary(mode || currentMode, getAccountScope());
    const d = res.data || {};
    if (d.current_nav == null && d.initial_capital == null) {
      el.innerHTML = emptyHtml;
      renderNavChart(null, { placeholder: NA });
      showToast(res.message || '无法获取账户信息', 3000);
      return;
    }
    el.innerHTML = `
      <div class="stat"><span>初始资金</span><strong>${fmt(d.initial_capital, 'num2')}</strong></div>
      <div class="stat"><span>当前净值</span><strong>${fmt(d.current_nav, 'num4')}</strong></div>
      <div class="stat"><span>累计收益</span><strong>${fmt(d.total_return, 'pct')}</strong></div>
      <div class="stat"><span>年化收益</span><strong>${fmt(d.annual_return, 'pct')}</strong></div>
      <div class="stat"><span>最大回撤</span><strong>${fmt(d.max_drawdown, 'pct')}</strong></div>
      <div class="stat"><span>夏普比率</span><strong>${fmt(d.sharpe, 'num2')}</strong></div>
      <div class="stat"><span>Beta</span><strong>${fmt(d.beta, 'num2')}</strong></div>
      <div class="stat"><span>Alpha</span><strong>${fmt(d.alpha, 'pct')}</strong></div>
    `;
    await loadNavHistory(mode);
  } catch (e) {
    el.innerHTML = emptyHtml;
    renderNavChart(null, { placeholder: NA });
    showToast(e.message || '无法获取账户信息', 3000);
  }
}

async function loadNavHistory(mode) {
  if (!window.api?.portfolio?.navHistory) {
    renderNavChart(null, { placeholder: '净值走势（暂无历史数据）' });
    return;
  }
  try {
    const res = await window.api.portfolio.navHistory(mode || currentMode, getAccountScope());
    const list = Array.isArray(res?.data) ? res.data : [];
    const src = (res?.meta?.data_source) || '';
    const pts = list
      .map(p => ({ t: Number(p.ts || p.t || 0), nav: Number(p.nav) }))
      .filter(p => Number.isFinite(p.nav));
    if (pts.length >= 2) {
      renderNavChart(pts, {
        caption: src === 'simulated_mirror' ? '数据来自回测镜像：按当前净值等比缩放的回测净值曲线' : '',
      });
    } else {
      renderNavChart(null, { placeholder: '净值走势（暂无历史数据）' });
    }
  } catch (_) {
    renderNavChart(null, { placeholder: '净值走势（暂无历史数据）' });
  }
}

async function loadBalance(mode) {
  if (!window.api) return;
  const el = document.getElementById('assets-balance');
  const emptyHtml = `<div class="stat"><span>USDT余额</span><strong>${NA}</strong></div><div class="stat"><span>今日盈亏</span><strong>${NA}</strong></div>`;
  try {
    const res = await window.api.assets.balance(mode || currentMode, getAccountScope());
    const d = res.data || {};
    if (d.available == null && d.total == null) {
      el.innerHTML = emptyHtml;
      showToast(res.message || '无法获取账户信息', 3000);
      return;
    }
    const av = d.available != null && d.available !== '' ? Number(d.available) : null;
    const pnl = d.today_pnl != null && d.today_pnl !== '' ? Number(d.today_pnl) : null;
    el.innerHTML = `
      <div class="stat"><span>USDT余额</span><strong>${fmt(av, 'num2')}</strong></div>
      <div class="stat"><span>今日盈亏</span><strong>${fmt(pnl, 'num2')}</strong></div>
    `;
  } catch (e) {
    el.innerHTML = emptyHtml;
    showToast(e.message || '无法获取账户信息', 3000);
  }
}

async function loadOrders(mode) {
  if (!window.api) return;
  const filterEl = document.getElementById('orders-filter');
  const activeFilter = document.querySelector('.filter-btn.active');
  const status = activeFilter?.dataset?.status || 'open';
  if (filterEl) filterEl.style.display = document.querySelector('.tab.active')?.dataset?.tab === 'orders' ? 'flex' : 'none';
  try {
    const res = await window.api.trading.orders(mode || currentMode, status, null, 1, 20);
    const list = res.data?.list || [];
    document.getElementById('orders-list').innerHTML = list.length
      ? list.map(o => {
          const cancelBtn = o.status === 'open' ? `<button class="btn-cancel" data-id="${o.id}" data-symbol="${o.symbol || ''}">撤单</button>` : '';
          return `<div class="order-item">${o.symbol || NA} ${o.side || NA} ${o.amount || o.filled_amount || NA} @ ${o.price || NA} ${o.create_time || ''} ${cancelBtn}</div>`;
        }).join('')
      : `<p class="empty">${NA}</p>`;
    document.getElementById('orders-list').querySelectorAll('.btn-cancel').forEach(btn => {
      btn.addEventListener('click', () => cancelOrder(btn.dataset.id, btn.dataset.symbol));
    });
  } catch (e) {
    document.getElementById('orders-list').innerHTML = `<p class="empty">${NA}</p><p class="error-hint">${e.message || '加载失败'}</p>`;
  }
}

async function cancelOrder(orderId, symbol) {
  if (!window.api || !orderId || !symbol) return;
  try {
    await window.api.trading.cancelOrder(orderId, symbol);
    loadOrders();
  } catch (e) {
    alert(e.message);
  }
}

async function loadPositions(mode) {
  if (!window.api) return;
  try {
    const res = await window.api.trading.positions(mode || currentMode);
    const list = res.data?.list || [];
    document.getElementById('positions-list').innerHTML = list.length
      ? list.map(p => `<div class="position-item">${p.symbol || NA} 数量: ${p.amount ?? NA} 市值: ${p.value_usdt != null ? Number(p.value_usdt).toFixed(2) : NA} USDT</div>`).join('')
      : `<p class="empty">${NA}</p>`;
  } catch (e) {
    document.getElementById('positions-list').innerHTML = `<p class="empty">${NA}</p><p class="error-hint">${e.message || '加载失败'}</p>`;
  }
}

document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('orders-list').classList.toggle('hidden', t.dataset.tab !== 'orders');
    document.getElementById('positions-list').classList.toggle('hidden', t.dataset.tab !== 'positions');
    if (t.dataset.tab === 'positions') loadPositions();
    else loadOrders();
  });
});
document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(x => x.classList.remove('active'));
    btn.classList.add('active');
    loadOrders();
  });
});

refreshAll();

// 监听交易模式切换（模拟/实盘）与回测镜像启用/关闭，实时刷新账户数据
window.addEventListener('message', (e) => {
  const t = e?.data?.type;
  if (t === 'trading-mode-changed' || t === 'simulated-mirror-changed') {
    refreshAll();
  } else if (t === 'page-activated' && e?.data?.page === 'account') {
    // 父窗口通知"账户 tab 被激活" → 强制拉取最新数据，兜底所有广播失效的场景
    refreshAll();
  }
});
// 主通道：BroadcastChannel 收到镜像变更
try {
  const bc = new BroadcastChannel('simulated-mirror');
  bc.addEventListener('message', (e) => {
    if (e?.data?.type === 'simulated-mirror-changed') refreshAll();
  });
} catch (_) {}
// 跟随仪表盘资产净值切换（spot/futures），以及镜像变更的 storage 信号
window.addEventListener('storage', (e) => {
  if (e.key === ACCOUNT_SCOPE_KEY) refreshAll();
  if (e.key === 'simulated-mirror-bump') refreshAll();
});
// 最后兜底：账户 iframe 可见时，若镜像状态与上次不同则刷新
let _lastMirrorRunId = 0;
(async () => {
  const s0 = await queryMirrorStatus();
  _lastMirrorRunId = s0 ? Number(s0.backtest_run_id || 0) : 0;
})();
async function pollMirrorChange() {
  if (document.hidden) return;
  const s = await queryMirrorStatus();
  const rid = s ? Number(s.backtest_run_id || 0) : 0;
  if (rid !== _lastMirrorRunId) {
    _lastMirrorRunId = rid;
    refreshAll();
  }
}
setInterval(pollMirrorChange, 3000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) pollMirrorChange();
});
window.addEventListener('focus', () => refreshAll());

// 暴露给父窗口：切换到账户页时也可触发刷新
window.refreshAccountData = refreshAll;

// 各区块刷新按钮
document.getElementById('btn-refresh-portfolio')?.addEventListener('click', () => loadPortfolio(currentMode));
document.getElementById('btn-refresh-assets')?.addEventListener('click', () => loadBalance(currentMode));
document.getElementById('btn-refresh-trading')?.addEventListener('click', () => {
  const tab = document.querySelector('.tab.active');
  if (tab?.dataset?.tab === 'positions') loadPositions(currentMode);
  else loadOrders(currentMode);
});

// 诊断按钮：输出完整请求/响应到页面和控制台，并测试 portfolio、assets、test-gate
document.getElementById('btn-debug')?.addEventListener('click', async (e) => {
  e.preventDefault();
  const outEl = document.getElementById('diagnose-output');
  if (!outEl) return;

  const log = (msg) => {
    const s = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
    outEl.textContent += s + '\n';
    console.log('[诊断]', msg);
  };

  outEl.classList.remove('hidden');
  outEl.textContent = '诊断中...\n';

  const API_BASE = window.API_BASE || 'http://127.0.0.1:8081/api/v1';
  const mode = currentMode || 'simulated';

  // 0. 先检查后端版本（若含 backend_version:gate-v2 则说明运行的是本仓库最新代码）
  const verRes = await fetch(API_BASE + '/debug/version', { method: 'GET', cache: 'no-store' });
  const verText = await verRes.text();
  log('========== debug/version（后端版本） ==========');
  log('URL: ' + API_BASE + '/debug/version');
  log('HTTP: ' + verRes.status + ' ' + verRes.statusText);
  log('响应: ' + verText);
  try {
    const v = JSON.parse(verText);
    if (v.data?.backend_version === 'gate-v2') {
      log('✓ 后端为最新版本（gate-v2），portfolio/assets 应从 Gate 获取真实数据');
    } else {
      log('⚠ 若 backend_version 不是 gate-v2，请：1) 关闭所有后端窗口 2) 删除 backend/__pycache__ 3) 重新运行 启动-后端.bat');
    }
  } catch (_) {}

  let token = null;
  try {
    let electron = window.electronAPI;
    if (!electron && window.parent && window.parent !== window) {
      try { electron = window.parent.electronAPI; } catch (_) {}
    }
    if (electron?.store?.get) token = await electron.store.get('token');
    if (!token) token = localStorage.getItem('token');
  } catch (err) {
    log('获取Token失败: ' + err.message);
  }
  const headers = { 'Authorization': token ? 'Bearer ' + token : '', 'Content-Type': 'application/json' };

  async function fetchAndLog(name, url) {
    log('\n========== ' + name + ' ==========');
    log('URL: ' + url);
    try {
      const res = await fetch(url, { method: 'GET', headers, cache: 'no-store' });
      const text = await res.text();
      log('HTTP: ' + res.status + ' ' + res.statusText);
      log('响应: ' + text);
      return { ok: res.ok, text };
    } catch (err) {
      log('请求异常: ' + err.message);
      return { ok: false };
    }
  }

  // 1. broker/status
  await fetchAndLog('broker/status', API_BASE + '/broker/status');

  // 2. broker/testgate（直接调用 Gate API 原始数据）
  const testGateRes = await fetchAndLog('broker/testgate（Gate 原始数据）', API_BASE + '/broker/testgate?mode=' + mode);
  try {
    const tg = JSON.parse(testGateRes.text || '{}');
    if (tg.success && tg.data?.raw_accounts) {
      log('\n--- Gate 账户原始余额 ---');
      tg.data.raw_accounts.forEach(a => log(`  ${a.currency}: available=${a.available} locked=${a.locked}`));
      if (tg.data.computed) log('计算总资产(USDT): ' + JSON.stringify(tg.data.computed));
    }
  } catch (_) {}

  // 3. portfolio/summary（界面投资组合数据来源）
  const portRes = await fetchAndLog('portfolio/summary（投资组合）', API_BASE + '/portfolio/summary?mode=' + mode);
  try {
    const p = JSON.parse(portRes.text || '{}');
    if (p.success && p.data) {
      log('\n--- 投资组合解析 ---');
      log('累计收益: ' + (p.data.total_return != null ? (p.data.total_return * 100).toFixed(2) + '%' : 'null'));
      log('当前净值: ' + (p.data.current_nav ?? 'null'));
    }
  } catch (_) {}

  // 4. assets/balance（界面资产净值数据来源）
  await fetchAndLog('assets/balance（资产净值）', API_BASE + '/assets/balance?mode=' + mode);

  log('\n========== 诊断完成 ==========');
  log('若 debug/version 或 testgate 返回 404，说明运行的是旧后端。请：');
  log('1. 关闭所有后端窗口（Ctrl+C）');
  log('2. 重新运行 启动-后端.bat');
  log('3. 确认后端窗口显示 "gate-v2" 相关日志');
});

// 定时刷新，保持数据实时性（每 30 秒）
setInterval(refreshAll, 30000);
