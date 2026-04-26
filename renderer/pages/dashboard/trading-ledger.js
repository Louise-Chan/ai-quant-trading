/**
 * K 线下方：当前委托 / 历史委托 / 成交 / 资产；审核栏下方：资产净值轮询
 */
(function () {
  const wrap = document.getElementById('ledger-table-wrap');
  const typeFilters = document.getElementById('ledger-type-filters');
  const filterSymbolCb = document.getElementById('ledger-filter-symbol');
  let activeTab = 'open';
  let otypeFilter = 'all';
  let _ledgerTimer = null;
  let _navTimer = null;
  const NAV_SCOPE_KEY = 'dashboard_nav_account_scope';
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

  function markPerfBoost(ms) {
    const ttl = Number.isFinite(ms) ? ms : 5000;
    try {
      localStorage.setItem(PERF_BOOST_KEY, String(Date.now() + ttl));
    } catch (_) {}
  }

  function getNavAccountScope() {
    try {
      const s = localStorage.getItem(NAV_SCOPE_KEY);
      return s === 'futures' ? 'futures' : 'spot';
    } catch (_) {
      return 'spot';
    }
  }

  function setNavAccountScope(scope) {
    const s = scope === 'futures' ? 'futures' : 'spot';
    try {
      localStorage.setItem(NAV_SCOPE_KEY, s);
    } catch (_) {}
  }

  function syncNavScopeUi() {
    const sc = getNavAccountScope();
    document.querySelectorAll('.nav-scope-btn').forEach((btn) => {
      btn.classList.toggle('active', (btn.getAttribute('data-nav-scope') || 'spot') === sc);
    });
  }

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function getMode() {
    try {
      if (window.api?.broker?.status) {
        const r = await window.api.broker.status();
        return r?.data?.current_mode || 'real';
      }
    } catch (_) {}
    try {
      const electron = window.electronAPI || window.parent?.electronAPI;
      if (electron?.store?.get) return (await electron.store.get('trading_mode')) || 'real';
    } catch (_) {}
    return localStorage.getItem('trading_mode') || 'real';
  }

  function formatTs(t) {
    if (t == null || t === '') return '—';
    const n = Number(t);
    if (!Number.isFinite(n)) return esc(String(t));
    const ms = n > 1e12 ? n : n * 1000;
    const d = new Date(ms);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString('zh-CN', { hour12: false });
  }

  function isMarketOrder(o) {
    const p = parseFloat(String(o.price ?? '0').replace(/,/g, ''));
    return !Number.isFinite(p) || p === 0;
  }

  function filterRows(list) {
    let rows = list || [];
    if (filterSymbolCb?.checked) {
      const sym = window.getDashboardCurrentSymbol?.();
      if (sym) rows = rows.filter((x) => String(x.symbol || '').toUpperCase() === String(sym).toUpperCase());
    }
    if (activeTab === 'open' || activeTab === 'history') {
      if (otypeFilter === 'limit') rows = rows.filter((o) => !isMarketOrder(o));
      else if (otypeFilter === 'market') rows = rows.filter((o) => isMarketOrder(o));
    }
    return rows;
  }

  function sideClass(side) {
    const s = String(side || '').toLowerCase();
    if (s === 'buy') return 'ledger-side-buy';
    if (s === 'sell') return 'ledger-side-sell';
    return '';
  }

  function renderOpenOrders(list) {
    const rows = filterRows(list);
    if (!rows.length) {
      wrap.innerHTML = '<p class="ledger-placeholder">暂无当前委托</p>';
      return;
    }
    let html =
      '<table class="ledger-table"><thead><tr><th>市场</th><th>时间</th><th>方向</th><th>价格</th><th>剩余/委托</th><th>操作</th></tr></thead><tbody>';
    rows.forEach((o) => {
      const sym = esc(o.symbol || '');
      const id = esc(o.id);
      html += `<tr><td>${sym}</td><td>${formatTs(o.create_time)}</td><td class="${sideClass(o.side)}">${esc(
        o.side || ''
      )}</td><td>${esc(o.price)}</td><td>${esc(o.left)} / ${esc(o.amount)}</td><td>`;
      if (o.id && o.symbol) {
        html += `<button type="button" class="btn-ledger-cancel" data-oid="${id}" data-sym="${sym}">撤单</button>`;
      }
      html += '</td></tr>';
    });
    html += '</tbody></table>';
    wrap.innerHTML = html;
    wrap.querySelectorAll('.btn-ledger-cancel').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const oid = btn.getAttribute('data-oid');
        const sym = btn.getAttribute('data-sym');
        if (!oid || !sym || !window.api?.trading?.cancelOrder) return;
        if (!confirm(`撤销订单 ${oid}？`)) return;
        markPerfBoost(6000);
        try {
          await window.api.trading.cancelOrder(oid, sym);
          await refreshLedger();
        } catch (e) {
          alert(e.message || '撤单失败');
        }
      });
    });
  }

  function renderHistoryOrders(list) {
    const rows = filterRows(list);
    if (!rows.length) {
      wrap.innerHTML = '<p class="ledger-placeholder">暂无历史委托</p>';
      return;
    }
    let html =
      '<table class="ledger-table"><thead><tr><th>市场</th><th>时间</th><th>方向</th><th>价格</th><th>成交/委托</th><th>状态</th></tr></thead><tbody>';
    rows.forEach((o) => {
      html += `<tr><td>${esc(o.symbol)}</td><td>${formatTs(o.create_time)}</td><td class="${sideClass(o.side)}">${esc(
        o.side || ''
      )}</td><td>${esc(o.price)}</td><td>${esc(o.filled_amount || '0')} / ${esc(o.amount)}</td><td>${esc(
        o.finish_as || o.status || ''
      )}</td></tr>`;
    });
    html += '</tbody></table>';
    wrap.innerHTML = html;
  }

  function renderTrades(list) {
    const rows = filterRows(list);
    if (!rows.length) {
      wrap.innerHTML = '<p class="ledger-placeholder">暂无成交记录</p>';
      return;
    }
    let html =
      '<table class="ledger-table"><thead><tr><th>市场</th><th>时间</th><th>方向</th><th>价格</th><th>数量</th><th>手续费</th></tr></thead><tbody>';
    rows.forEach((t) => {
      html += `<tr><td>${esc(t.symbol)}</td><td>${formatTs(t.create_time)}</td><td class="${sideClass(t.side)}">${esc(
        t.side || ''
      )}</td><td>${esc(t.price)}</td><td>${esc(t.amount)}</td><td>${esc(t.fee)}</td></tr>`;
    });
    html += '</tbody></table>';
    wrap.innerHTML = html;
  }

  function renderAssets(positions, balance) {
    let html =
      '<table class="ledger-table"><thead><tr><th>交易对</th><th>币种</th><th>数量</th><th>估值(USDT)</th></tr></thead><tbody>';
    const pos = filterRows(positions);
    pos.forEach((p) => {
      html += `<tr><td>${esc(p.symbol)}</td><td>${esc(p.currency)}</td><td>${esc(p.amount)}</td><td>${Number(
        p.value_usdt || 0
      ).toFixed(2)}</td></tr>`;
    });
    if (balance?.total != null) {
      html += `<tr><td colspan="3"><strong>账户总估值 (USDT)</strong></td><td><strong>${Number(balance.total).toFixed(
        4
      )}</strong></td></tr>`;
      html += `<tr><td colspan="3">可用 / 冻结</td><td>${Number(balance.available || 0).toFixed(4)} / ${Number(
        balance.frozen || 0
      ).toFixed(4)}</td></tr>`;
    }
    html += '</tbody></table>';
    if (!pos.length && balance?.total == null) {
      wrap.innerHTML = '<p class="ledger-placeholder">暂无持仓或未绑定交易所</p>';
      return;
    }
    wrap.innerHTML = html;
  }

  async function refreshLedger() {
    if (!wrap || !window.api?.trading) return;
    const mode = await getMode();
    try {
      if (activeTab === 'open') {
        const res = await window.api.trading.orders(mode, 'open', null, 1, 50);
        renderOpenOrders(res.data?.list || []);
      } else if (activeTab === 'history') {
        const res = await window.api.trading.orders(mode, 'finished', null, 1, 50);
        renderHistoryOrders(res.data?.list || []);
      } else if (activeTab === 'trades') {
        const sym = filterSymbolCb?.checked ? window.getDashboardCurrentSymbol?.() : null;
        const res = await window.api.trading.trades(mode, sym, 1, 50);
        renderTrades(res.data?.list || []);
      } else if (activeTab === 'assets') {
        const [pres, bres] = await Promise.all([
          window.api.trading.positions(mode),
          window.api.assets.balance(mode).catch(() => ({ data: null })),
        ]);
        renderAssets(pres.data?.list || [], bres.data || null);
      }
    } catch (e) {
      wrap.innerHTML = `<p class="ledger-placeholder">${esc(e.message || '加载失败')}</p>`;
    }
  }

  function updateTypeFiltersVisibility() {
    if (!typeFilters) return;
    typeFilters.classList.toggle('hidden', activeTab !== 'open' && activeTab !== 'history');
  }

  async function refreshNav() {
    const elCur = document.getElementById('nav-current');
    const elRet = document.getElementById('nav-return');
    const elIni = document.getElementById('nav-initial');
    const elFoot = document.getElementById('nav-foot');
    if (!elCur || !window.api?.portfolio?.summary) return;
    const mode = await getMode();
    const accountScope = getNavAccountScope();
    try {
      const res = await window.api.portfolio.summary(mode, accountScope);
      const d = res.data || {};
      const nav = d.current_nav;
      elCur.textContent = nav != null ? Number(nav).toFixed(4) : '--';
      elIni.textContent = d.initial_capital != null ? Number(d.initial_capital).toFixed(2) : '--';
      const tr = d.total_return;
      elRet.classList.remove('positive', 'negative');
      if (tr == null) {
        elRet.textContent = '累计收益率 --';
      } else {
        const pct = (Number(tr) * 100).toFixed(2);
        elRet.textContent = `累计 ${pct}%`;
        elRet.classList.add(Number(tr) >= 0 ? 'positive' : 'negative');
      }
      elFoot.textContent = `上次更新：${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`;
    } catch (_) {
      elCur.textContent = '--';
      elRet.textContent = '累计收益率 --';
      elRet.classList.remove('positive', 'negative');
      try {
        const msg = _?.message ? String(_.message) : '';
        elFoot.textContent = msg ? `无法获取净值：${msg}` : '无法获取净值（请检查账户范围、模式与 Gate 连接）';
      } catch {
        elFoot.textContent = '无法获取净值（请检查账户范围、模式与 Gate 连接）';
      }
    }
  }

  document.querySelectorAll('.ledger-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      activeTab = btn.getAttribute('data-ledger-tab') || 'open';
      document.querySelectorAll('.ledger-tab').forEach((b) => b.classList.toggle('active', b === btn));
      updateTypeFiltersVisibility();
      wrap.innerHTML = '<p class="ledger-placeholder">加载中…</p>';
      refreshLedger();
    });
  });

  document.querySelectorAll('.ledger-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      otypeFilter = btn.getAttribute('data-otype') || 'all';
      document.querySelectorAll('.ledger-chip').forEach((b) => b.classList.toggle('active', b === btn));
      refreshLedger();
    });
  });

  filterSymbolCb?.addEventListener('change', () => refreshLedger());
  document.getElementById('btn-refresh-ledger')?.addEventListener('click', () => {
    refreshLedger();
    refreshNav();
  });

  function startTimers() {
    if (_ledgerTimer) clearInterval(_ledgerTimer);
    if (_navTimer) clearInterval(_navTimer);
    _ledgerTimer = setInterval(() => {
      if (shouldPausePolling()) return;
      refreshLedger();
    }, 15000);
    _navTimer = setInterval(() => {
      if (shouldPausePolling()) return;
      refreshNav();
    }, 12000);
  }

  document.querySelectorAll('.nav-scope-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      setNavAccountScope(btn.getAttribute('data-nav-scope') || 'spot');
      syncNavScopeUi();
      refreshNav();
    });
  });
  syncNavScopeUi();

  if (wrap) {
    updateTypeFiltersVisibility();
    refreshLedger();
    refreshNav();
    startTimers();
  }
})();
