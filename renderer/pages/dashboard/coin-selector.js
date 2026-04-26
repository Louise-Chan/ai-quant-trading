/** 筛选 / 行情标的列表（仅显示标的，无最新价与 24h 涨跌）+ Agent 筛选 + 交易开关 */

function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function getCurrentMode() {
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

async function addToWatchlist(symbol, quoteMarket) {
  if (!window.api) return;
  try {
    const qm = quoteMarket === 'futures' ? 'futures' : 'spot';
    await window.api.dashboard.addWatchlist(symbol, qm);
    if (window.loadWatchlist) window.loadWatchlist();
  } catch (e) {
    alert(e.message);
  }
}

/* ---------- 行情标的（现货 / 合约、搜索、刷新、点行 K 线、+自选） ---------- */
let currentQuoteMarket = 'spot';
let _marketQuotesLoading = false;
let _coinSearchTimer = null;
// PERF_BOOST_KEY 已由 kline-chart.js 在全局作用域声明（同一 index.html 先加载），此处复用避免重复 const。

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

function getCoinListEl() {
  return document.getElementById('coin-list');
}

function syncQuoteRowSelection() {
  const list = getCoinListEl();
  if (!list) return;
  const sym =
    typeof window.getDashboardCurrentSymbol === 'function' ? window.getDashboardCurrentSymbol() : null;
  const market = window._klineQuoteMarket === 'futures' ? 'futures' : 'spot';
  list.querySelectorAll('.market-row').forEach((row) => {
    const rs = row.dataset.symbol;
    const rm = row.dataset.market || 'spot';
    row.classList.toggle('is-selected', !!sym && rs === sym && rm === market);
  });
}

function renderMarketQuoteRows(rows) {
  const list = getCoinListEl();
  if (!list) return;
  if (!rows?.length) {
    list.innerHTML = '<p class="market-placeholder">暂无标的，请检查网络或刷新</p>';
    syncQuoteRowSelection();
    return;
  }
  const mkt = currentQuoteMarket === 'futures' ? 'futures' : 'spot';
  list.innerHTML = rows
    .map(
      (r) => `
    <div class="market-row" role="option" data-symbol="${esc(r.symbol)}" data-market="${esc(mkt)}">
      <span class="col-symbol" title="${esc(r.symbol)}">${esc(r.symbol)}</span>
      <span class="col-action">
        <button type="button" class="btn-add-watch" data-symbol="${esc(r.symbol)}" title="加入自选">+自选</button>
      </span>
    </div>
  `
    )
    .join('');

  list.querySelectorAll('.market-row').forEach((row) => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('.btn-add-watch')) return;
      const symbol = row.dataset.symbol;
      const mk = row.dataset.market === 'futures' ? 'futures' : 'spot';
      if (symbol && typeof window.loadKlineFromQuote === 'function') {
        window.loadKlineFromQuote(symbol, mk);
      }
    });
  });
  list.querySelectorAll('.btn-add-watch').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const row = btn.closest('.market-row');
      const symbol = btn.dataset.symbol || row?.dataset?.symbol;
      const mk = row?.dataset?.market === 'futures' ? 'futures' : 'spot';
      if (symbol) addToWatchlist(symbol, mk);
    });
  });
  syncQuoteRowSelection();
}

async function loadMarketQuotes() {
  if (!window.api?.dashboard?.marketQuotes || _marketQuotesLoading) return;
  const list = getCoinListEl();
  if (!list) return;
  _marketQuotesLoading = true;
  list.innerHTML = '<p class="market-placeholder">加载中…</p>';
  try {
    const mode = await getCurrentMode();
    const kw = document.getElementById('coin-search')?.value?.trim() || '';
    const res = await window.api.dashboard.marketQuotes(currentQuoteMarket, kw, mode, 800);
    if (!res?.success) {
      list.innerHTML = `<p class="market-placeholder">${esc(res?.message || '加载失败')}</p>`;
      return;
    }
    const raw = res?.data?.list ?? res?.data?.rows ?? res?.data;
    const arr = Array.isArray(raw) ? raw : [];
    renderMarketQuoteRows(arr);
  } catch (e) {
    list.innerHTML = `<p class="market-placeholder">加载失败：${esc(e?.message || '未知错误')}</p>`;
  } finally {
    _marketQuotesLoading = false;
  }
}

function scheduleMarketQuotesSearch() {
  if (_coinSearchTimer) clearTimeout(_coinSearchTimer);
  _coinSearchTimer = setTimeout(() => {
    _coinSearchTimer = null;
    loadMarketQuotes();
  }, 280);
}

document.getElementById('btn-refresh-coins')?.addEventListener('click', () => loadMarketQuotes());

document.querySelectorAll('.market-quote-tabs .market-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    const m = tab.dataset.market === 'futures' ? 'futures' : 'spot';
    currentQuoteMarket = m;
    document.querySelectorAll('.market-quote-tabs .market-tab').forEach((t) => {
      const on = t === tab;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    loadMarketQuotes();
  });
});

document.getElementById('coin-search')?.addEventListener('input', () => scheduleMarketQuotesSearch());

window.addEventListener('dashboard-kline-symbol', () => syncQuoteRowSelection());

// 一键选币：先进入调节页面，底部选币按钮才输出结果
document.getElementById('btn-smart-select')?.addEventListener('click', () => {
  showRuleSettingsModal();
});

function showDeepseekBindModal(onSuccess) {
  const modal = document.createElement('div');
  modal.className = 'smart-select-modal deepseek-bind-modal';
  modal.innerHTML = `
    <div class="smart-select-modal-content">
      <h3>绑定 DeepSeek API</h3>
      <p class="smart-select-summary">Agent 选币需调用 DeepSeek API（与官方文档一致：<a href="https://api-docs.deepseek.com/zh-cn/" target="_blank" rel="noopener">api-docs.deepseek.com</a>）。Key 保存在本机后端。</p>
      <input type="password" id="modal-deepseek-key" class="deepseek-key-input" style="width:100%;box-sizing:border-box;margin:0.5rem 0;padding:0.5rem;border:1px solid #dee2e6;border-radius:6px;" placeholder="DeepSeek API Key" autocomplete="off" />
      <div class="smart-select-actions">
        <button type="button" class="btn-cancel">取消</button>
        <button type="button" class="btn-do-select" id="modal-deepseek-save">保存并继续</button>
      </div>
    </div>
  `;
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:10000;';
  const content = modal.querySelector('.smart-select-modal-content');
  if (content) content.style.cssText = 'background:#fff;border-radius:12px;padding:1.5rem;max-width:420px;box-shadow:0 4px 20px rgba(0,0,0,0.15);';
  document.body.appendChild(modal);
  modal.querySelector('.btn-cancel')?.addEventListener('click', () => modal.remove());
  modal.querySelector('#modal-deepseek-save')?.addEventListener('click', async () => {
    const v = modal.querySelector('#modal-deepseek-key')?.value?.trim() || '';
    if (!v) {
      alert('请输入 API Key');
      return;
    }
    try {
      markPerfBoost(5000);
      await window.api.users.updatePreferences({ deepseek_api_key: v });
      modal.remove();
      if (typeof onSuccess === 'function') onSuccess();
    } catch (e) {
      alert(e?.message || '保存失败');
    }
  });
}

async function runAgentSelectFlow() {
  if (!window.api?.dashboard?.agentSelect) return;
  const pref = prompt('可选：输入选币偏好（如：偏稳健、主流币、DeFi）', '');
  const btn = document.getElementById('btn-agent-select');
  const origText = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '分析中...';
  }
  try {
    markPerfBoost(7000);
    const mode = await getCurrentMode();
    const res = await window.api.dashboard.agentSelect({ preference: pref || undefined, top_n: 10, mode });
    if (!res?.success) {
      if (res?.data?.needs_deepseek) {
        showDeepseekBindModal(() => runAgentSelectFlow());
        return;
      }
      alert(res?.message || 'Agent 选币失败');
      return;
    }
    if (res?.data?.symbols?.length) {
      showSmartSelectResultModal(res.data.symbols, res.data.source || 'deepseek_agent', res.data.summary);
    } else {
      alert(res?.data?.summary || '暂无推荐标的');
    }
  } catch (e) {
    alert(e?.message || 'Agent 选币失败');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText || 'Agent筛选';
    }
  }
}

document.getElementById('btn-agent-select')?.addEventListener('click', () => {
  runAgentSelectFlow();
});

// 调节页面：规则参数 + 底部选币按钮
function showRuleSettingsModal() {
  const modal = document.createElement('div');
  modal.className = 'smart-select-modal rule-settings-modal';
  modal.innerHTML = `
    <div class="smart-select-modal-content">
      <h3>选币规则调节</h3>
      <div class="rule-form">
        <div class="rule-row">
          <label>最低成交额（万 USDT）</label>
          <select id="rule-min-volume">
            <option value="1">1</option>
            <option value="5" selected>5</option>
            <option value="10">10</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </div>
        <div class="rule-row">
          <label>24h 涨跌幅上限（%）</label>
          <select id="rule-max-change">
            <option value="0.5">50</option>
            <option value="1" selected>100</option>
            <option value="2">200</option>
            <option value="5">500</option>
          </select>
        </div>
        <div class="rule-row">
          <label>推荐数量</label>
          <select id="rule-top-n">
            <option value="5">5</option>
            <option value="10" selected>10</option>
            <option value="15">15</option>
            <option value="20">20</option>
          </select>
        </div>
      </div>
      <div class="smart-select-actions">
        <button class="btn-cancel">取消</button>
        <button class="btn-do-select">筛选</button>
      </div>
    </div>
  `;
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;';
  const content = modal.querySelector('.smart-select-modal-content');
  if (content) content.style.cssText = 'background:#fff;border-radius:12px;padding:1.5rem;max-width:380px;box-shadow:0 4px 20px rgba(0,0,0,0.15);';
  document.body.appendChild(modal);

  modal.querySelector('.btn-cancel')?.addEventListener('click', () => modal.remove());
  modal.querySelector('.btn-do-select')?.addEventListener('click', async () => {
    const minVol = parseInt(modal.querySelector('#rule-min-volume')?.value || '5', 10) * 10000;
    const maxChg = parseFloat(modal.querySelector('#rule-max-change')?.value || '1');
    const topN = parseInt(modal.querySelector('#rule-top-n')?.value || '10', 10);
    modal.remove();
    await doSmartSelectAndShowResults({ min_quote_volume: minVol, max_change_24h: maxChg, top_n: topN });
  });
}

// 执行选币并展示结果（结果页单选入自选）
async function doSmartSelectAndShowResults(params) {
  if (!window.api?.dashboard?.smartSelect) return;
  const btn = document.getElementById('btn-smart-select');
  const origText = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '加载中...';
  }
  try {
    markPerfBoost(7000);
    const mode = await getCurrentMode();
    const res = await window.api.dashboard.smartSelect({ ...params, mode });
    if (res?.success && res?.data?.symbols?.length) {
      showSmartSelectResultModal(res.data.symbols, res.data.source || 'rule_engine', res.data.summary);
    } else {
      alert(res?.message || '暂无推荐，请稍后重试');
    }
  } catch (e) {
    alert(e?.message || '选币服务暂未就绪');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText || '筛选';
    }
  }
}

// 结果页：每个币种可单选加入自选（规则选币 / Agent 选币共用）
function showSmartSelectResultModal(symbols, source, summary) {
  const modal = document.createElement('div');
  modal.className = 'smart-select-modal result-modal';
  modal.innerHTML = `
    <div class="smart-select-modal-content">
      <h3>选币结果</h3>
      <p class="smart-select-source">来源：${esc(source)}</p>
      ${summary ? `<p class="smart-select-summary">${esc(summary)}</p>` : ''}
      <div class="smart-select-list">
        ${symbols.map((s) => `
          <div class="smart-select-result-item" data-symbol="${esc(s.symbol)}">
            <span class="symbol">${esc(s.symbol)}</span>
            ${s.reason ? `<small>${esc(s.reason)}</small>` : ''}
            <button class="btn-add-single">+ 自选</button>
          </div>
        `).join('')}
      </div>
      <div class="smart-select-actions">
        <button class="btn-close">关闭</button>
      </div>
    </div>
  `;
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;';
  const content = modal.querySelector('.smart-select-modal-content');
  if (content) content.style.cssText = 'background:#fff;border-radius:12px;padding:1.5rem;max-width:420px;max-height:85vh;overflow:auto;box-shadow:0 4px 20px rgba(0,0,0,0.15);';
  document.body.appendChild(modal);

  modal.querySelector('.btn-close')?.addEventListener('click', () => modal.remove());
  modal.querySelectorAll('.btn-add-single').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const item = btn.closest('.smart-select-result-item');
      const symbol = item?.dataset?.symbol;
      if (!symbol || !window.api) return;
      btn.disabled = true;
      try {
        await window.api.dashboard.addWatchlist(symbol, 'spot');
        if (window.loadWatchlist) window.loadWatchlist();
        btn.textContent = '已添加';
        btn.classList.add('added');
      } catch (e) {
        btn.disabled = false;
        alert(e?.message || '添加失败');
      }
    });
  });
}

async function refreshTradingStatus() {
  const label = document.getElementById('trading-status-label');
  const btnToggle = document.getElementById('btn-trading-toggle');
  if (!label || !window.api?.dashboard?.tradingState) return;
  try {
    markPerfBoost(5000);
    const res = await window.api.dashboard.tradingState();
    const d = res.data || {};
    const running = !!d.trading_running;
    const name = d.active_strategy_name || '';
    const sid = d.active_subscription_id;
    let text = running ? `交易：运行中` : '交易：未运行';
    if (sid && name) text += ` · ${name} (#${sid})`;
    else if (sid) text += ` · 订阅 #${sid}`;
    if (d.mode_mismatch) text += ' （警告：与当前模式不一致）';
    label.textContent = text;
    if (btnToggle) {
      btnToggle.classList.remove('btn-ui-loading');
      btnToggle.dataset.running = running ? 'true' : 'false';
      btnToggle.textContent = running ? '停止交易' : '开始交易';
      btnToggle.disabled = false;
    }
    try {
      window.__syncOrderAuditTrading?.(running);
    } catch (_) {}
    try {
      window.refreshCustodyUi?.();
    } catch (_) {}
  } catch (_) {
    label.textContent = '交易：未登录或状态未知';
    const b = document.getElementById('btn-trading-toggle');
    if (b) {
      b.classList.remove('btn-ui-loading');
      b.textContent = '开始交易';
      b.dataset.running = 'false';
    }
  }
}

/** 供 order-audit.js 在开始/停止交易后同步标签与按钮 */
window.refreshDashboardTradingStatus = refreshTradingStatus;

refreshTradingStatus();
setInterval(() => {
  if (shouldPausePolling()) return;
  refreshTradingStatus();
}, 15000);

loadMarketQuotes();
