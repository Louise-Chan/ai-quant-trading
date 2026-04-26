/**
 * 订单审核：DeepSeek 绑定、拉取列表、通过/拒绝；开始交易后自动批量审核自选，状态栏显示进度。
 */
(function () {
  const listEl = document.getElementById('order-audit-list');
  const keyInput = document.getElementById('deepseek-key-input');
  const btnSave = document.getElementById('btn-save-deepseek');
  const keyStatus = document.getElementById('deepseek-key-status');
  const statusBarEl = document.getElementById('order-audit-status-bar');
  const PERF_BOOST_KEY = 'dashboard_perf_boost_until';

  let _pollTimer = null;
  let _lastListMaxId = 0;
  /** 通过/拒绝请求进行中：暂停定时刷新，避免把「审核中」状态冲掉 */
  let _auditGateActionBusy = false;
  /** 首次进入仪表盘：审核列表滚到底并滚入视口，优先看到底部审核条 */
  let _didInitialAuditScroll = false;

  /** 批量生成审核：正在跑策略+DeepSeek */
  let _auditBatchInProgress = false;
  let _auditBatchAbort = false;
  let _batchCurrent = 0;
  let _batchTotal = 0;
  const _batchIdleWaiters = [];
  /** 交易运行期间，用户曾打开过 K 线的自选标的（去重），用于「审核中 opened/total」 */
  const _klineOpenedDistinct = new Set();
  let _watchlistTotal = 0;

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

  function tradingLoadingHtml() {
    return 'Loading<span class="loading-ellipsis" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>';
  }

  function isTradingRunning() {
    const btn = document.getElementById('btn-trading-toggle');
    return btn?.dataset.running === 'true';
  }

  function finishBatchAndNotifyWaiters() {
    _auditBatchInProgress = false;
    _batchCurrent = 0;
    _batchTotal = 0;
    const ws = _batchIdleWaiters.splice(0);
    ws.forEach((r) => {
      try {
        r();
      } catch (_) {}
    });
    updateAuditStatusBar();
  }

  async function waitUntilAuditBatchIdle() {
    if (!_auditBatchInProgress) return;
    await new Promise((r) => _batchIdleWaiters.push(r));
  }

  function updateAuditStatusBar() {
    if (!statusBarEl) return;
    if (!isTradingRunning()) {
      statusBarEl.textContent = '审核已停止';
      statusBarEl.className = 'order-audit-status-bar order-audit-status-bar--stopped';
      return;
    }
    if (_auditBatchInProgress && _batchTotal > 0) {
      statusBarEl.textContent = `审核中 ${_batchCurrent}/${_batchTotal}`;
      statusBarEl.className = 'order-audit-status-bar order-audit-status-bar--running';
      return;
    }
    const n = Math.max(0, _watchlistTotal || 0);
    const opened = _klineOpenedDistinct.size;
    if (n <= 0) {
      statusBarEl.textContent = '审核中（请先添加自选标的）';
    } else {
      statusBarEl.textContent = `审核中 ${opened}/${n}`;
    }
    statusBarEl.className = 'order-audit-status-bar order-audit-status-bar--running';
  }

  window.__syncOrderAuditTrading = function (running) {
    if (!running) {
      _auditBatchAbort = true;
      _klineOpenedDistinct.clear();
    }
    updateAuditStatusBar();
  };

  window.__onWatchlistCountUpdated = function (count) {
    const n = parseInt(String(count), 10);
    _watchlistTotal = Number.isFinite(n) && n >= 0 ? n : 0;
    updateAuditStatusBar();
  };

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function displayStr(v) {
    if (v == null || v === 'null' || v === undefined) return '';
    return String(v);
  }

  function escAttr(s) {
    return esc(displayStr(s));
  }

  /** 通过/不通过处理中：黑色「审核中」+ 省略号（不用 Loading 字样） */
  function reviewingDotsHtml() {
    return '审核中<span class="loading-ellipsis" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>';
  }

  /** 待处理卡片：处理中禁用表单、隐藏通过/不通过，在底部居中显示黑色「审核中」 */
  function setAuditCardBusy(card, busy) {
    if (!card) return;
    card.querySelectorAll('.audit-inp-price, .audit-inp-sl, .audit-inp-tp, .audit-sel-order-type').forEach((el) => {
      el.disabled = !!busy;
    });
    const loadingEl = card.querySelector('.order-audit-actions-loading');
    const ap = card.querySelector('.btn-audit-approve');
    const rj = card.querySelector('.btn-audit-reject');
    if (busy) {
      card.classList.add('is-audit-busy');
      if (loadingEl) {
        loadingEl.innerHTML = reviewingDotsHtml();
        loadingEl.setAttribute('aria-hidden', 'false');
      }
      if (ap) ap.disabled = true;
      if (rj) rj.disabled = true;
    } else {
      card.classList.remove('is-audit-busy');
      if (loadingEl) {
        loadingEl.innerHTML = '';
        loadingEl.setAttribute('aria-hidden', 'true');
      }
      if (ap) {
        ap.disabled = false;
        ap.textContent = '通过';
      }
      if (rj) {
        rj.disabled = false;
        rj.textContent = '不通过';
      }
    }
  }

  function resetAuditForm(card) {
    if (!card) return;
    const p = card.getAttribute('data-orig-price');
    const sl = card.getAttribute('data-orig-sl');
    const tp = card.getAttribute('data-orig-tp');
    const typ = (card.getAttribute('data-orig-type') || 'limit').toLowerCase();
    const inpP = card.querySelector('.audit-inp-price');
    const inpSl = card.querySelector('.audit-inp-sl');
    const inpTp = card.querySelector('.audit-inp-tp');
    const sel = card.querySelector('.audit-sel-order-type');
    if (inpP) inpP.value = p != null ? p : '';
    if (inpSl) inpSl.value = sl != null ? sl : '';
    if (inpTp) inpTp.value = tp != null ? tp : '';
    if (sel) sel.value = typ === 'market' ? 'market' : 'limit';
    sel?.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function syncPriceInputForOrderType(selectEl) {
    const card = selectEl?.closest?.('.order-audit-card');
    const inp = card?.querySelector('.audit-inp-price');
    if (!inp) return;
    if (selectEl.value === 'market') {
      inp.placeholder = '市价可留空';
      inp.removeAttribute('required');
    } else {
      inp.placeholder = '限价必填';
      inp.setAttribute('required', 'required');
    }
  }

  function sideColoredHtml(side) {
    const s = String(side || '').toLowerCase().trim();
    if (s === 'buy') return '<span class="audit-side-buy">buy</span>';
    if (s === 'sell') return '<span class="audit-side-sell">sell</span>';
    return esc(side || '—');
  }

  /** 一句话要点，悬停卡片或理由可看全文 */
  function summarizeReason(text) {
    let t = String(text || '').trim().replace(/\s+/g, ' ');
    if (!t) return '';
    const m = t.match(/^.{1,200}?[。．\.!?？；;]/);
    if (m && m[0].length >= 12) return m[0].trim();
    if (t.length <= 120) return t;
    return t.slice(0, 117).trim() + '…';
  }

  function strategySnippet(item) {
    const se = item.context?.signal?.strategy_engine;
    if (!se || !se.ok) return '';
    const dir = se.signal_direction || '';
    const sc = se.composite_score != null ? se.composite_score : '';
    const ml = se.machine_learning?.p_up != null ? `p↑${se.machine_learning.p_up}` : '';
    const bt = se.backtest?.ok ? `夏普≈${se.backtest.sharpe_approx}` : '';
    const dirHtml =
      String(dir).toLowerCase() === 'buy'
        ? '<span class="audit-side-buy">buy</span>'
        : String(dir).toLowerCase() === 'sell'
          ? '<span class="audit-side-sell">sell</span>'
          : esc(dir);
    return `<div class="order-audit-strategy-snippet" title="策略引擎摘要">${dirHtml} · 得分${esc(sc)}${ml ? ' · ' + esc(ml) : ''}${bt ? ' · ' + esc(bt) : ''}</div>`;
  }

  function statusLabel(st) {
    const m = {
      pending: '待处理',
      executed: '已执行',
      rejected: '不通过',
      failed: '执行失败',
    };
    return m[st] || st;
  }

  function scrollAuditToBottom(smooth) {
    if (!listEl) return;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        listEl.scrollTo({
          top: listEl.scrollHeight,
          behavior: smooth ? 'smooth' : 'auto',
        });
        if (!smooth) listEl.scrollTop = listEl.scrollHeight;
      });
    });
  }

  /** 将审核列表区域滚入 iframe 视口底部，便于默认看到最新审核条 */
  function scrollAuditListIntoViewBottom() {
    if (!listEl) return;
    try {
      listEl.scrollIntoView({ block: 'end', behavior: 'auto' });
    } catch (_) {
      try {
        listEl.scrollIntoView(false);
      } catch (_) {}
    }
  }

  function renderCard(item, isNew) {
    const ao = item.audited_order || {};
    const conf = String(item.confidence || 'medium').toLowerCase();
    const confBand =
      conf === 'high' ? 'order-audit-card--conf-high' : conf === 'low' ? 'order-audit-card--conf-low' : 'order-audit-card--conf-mid';
    const confCls =
      conf === 'high' ? 'conf-high' : conf === 'low' ? 'conf-low' : 'conf-mid';
    const pending = item.status === 'pending';
    const anim = isNew ? ' order-audit-card--pop' : '';
    const reasonFull = String(item.agent_reason || '');
    const reasonShort = summarizeReason(reasonFull);
    const openS = String(ao.open_time_suggestion || '').trim();
    const closeS = String(ao.close_time_suggestion || '').trim();
    const origPrice = displayStr(ao.price);
    const origSl = displayStr(ao.stop_loss_price);
    const origTp = displayStr(ao.take_profit_price);
    const origType = String(ao.order_type || 'limit').toLowerCase();
    const typeSelMarket = origType === 'market' ? ' selected' : '';
    const typeSelLimit = origType !== 'market' ? ' selected' : '';
    const cardTitle = [
      ao.symbol,
      ao.side,
      ao.price,
      ao.amount,
      openS,
      closeS,
      reasonFull,
    ]
      .filter(Boolean)
      .join(' · ');

    const instTag = ao.instrument_type
      ? `<span class="audit-instrument-type">${esc(ao.instrument_type)}</span>`
      : '';
    const pendingEditBlock = pending
      ? `
        <div class="order-audit-row-main order-audit-row-main--pending">
          <span class="audit-symbol">${esc(ao.symbol || '—')}</span>
          ${instTag}
          ${sideColoredHtml(ao.side)}
          <span class="audit-amt-only">数量 ${esc(ao.amount)}</span>
        </div>
        <div class="order-audit-edit-fields">
          <div class="order-audit-field">
            <label for="audit-price-${item.id}">委托价格</label>
            <input type="text" id="audit-price-${item.id}" class="audit-inp-price" value="${escAttr(
              origPrice
            )}" autocomplete="off" />
          </div>
          <div class="order-audit-spacer" aria-hidden="true"></div>
          <div class="order-audit-field">
            <label for="audit-sl-${item.id}">止损价</label>
            <input type="text" id="audit-sl-${item.id}" class="audit-inp-sl" value="${escAttr(origSl)}" autocomplete="off" />
          </div>
          <div class="order-audit-field">
            <label for="audit-tp-${item.id}">止盈价</label>
            <input type="text" id="audit-tp-${item.id}" class="audit-inp-tp" value="${escAttr(origTp)}" autocomplete="off" />
          </div>
          <div class="order-audit-field order-audit-field--full">
            <label for="audit-type-${item.id}">订单类型</label>
            <select id="audit-type-${item.id}" class="audit-sel-order-type">
              <option value="limit"${typeSelLimit}>限价 limit</option>
              <option value="market"${typeSelMarket}>市价 market</option>
            </select>
          </div>
        </div>`
      : `
        <div class="order-audit-row-main">
          <span class="audit-symbol">${esc(ao.symbol || '—')}</span>
          ${instTag}
          ${sideColoredHtml(ao.side)}
          <span class="audit-otype">${esc(ao.order_type || '')}</span>
          <span class="audit-px-amt">${esc(ao.price)} × ${esc(ao.amount)}</span>
        </div>
        <div class="order-audit-row-sl">损 ${esc(ao.stop_loss_price)} · 盈 ${esc(ao.take_profit_price)}</div>`;

    return `
      <article class="order-audit-card ${confBand}${anim}" data-id="${item.id}" title="${esc(cardTitle)}"
        data-orig-price="${escAttr(origPrice)}"
        data-orig-sl="${escAttr(origSl)}"
        data-orig-tp="${escAttr(origTp)}"
        data-orig-type="${escAttr(origType)}">
        <div class="order-audit-card-top">
          <span class="order-audit-status status-${esc(item.status)}">${esc(statusLabel(item.status))}</span>
          <span class="order-audit-confidence ${confCls}">${esc(item.confidence_label || '')}</span>
        </div>
        <div class="order-audit-meta">${esc((item.created_at || '').replace('T', ' ').slice(0, 16))} · ${esc(item.mode || '')}</div>
        ${pendingEditBlock}
        ${strategySnippet(item)}
        <p class="order-audit-reason" title="${esc(reasonFull)}"><span class="order-audit-reason-label">要点</span> ${esc(reasonShort)}</p>
        ${item.exchange_order_id ? `<p class="order-audit-ex">单号 ${esc(item.exchange_order_id)}</p>` : ''}
        ${item.error_message ? `<p class="order-audit-err">${esc(item.error_message)}</p>` : ''}
        ${
          pending
            ? `<div class="order-audit-actions-footer">
            <div class="order-audit-actions">
              <button type="button" class="btn-audit-approve" data-id="${item.id}">通过</button>
              <button type="button" class="btn-audit-reject" data-id="${item.id}">不通过</button>
            </div>
            <p class="order-audit-actions-loading" aria-live="polite" aria-hidden="true"></p>
          </div>`
            : ''
        }
      </article>
    `;
  }

  async function refreshList(scrollBottom, forceNewAnim) {
    if (!listEl || !window.api?.orderAudit) return;
    if (listEl.querySelector('.order-audit-card input:focus, .order-audit-card select:focus')) {
      return;
    }
    try {
      const res = await window.api.orderAudit.list(null, 100);
      const list = res.data?.list || [];
      let maxId = 0;
      list.forEach((x) => {
        if (x.id > maxId) maxId = x.id;
      });
      const prevMax = _lastListMaxId;
      const hasNew = forceNewAnim || (maxId > prevMax && prevMax > 0);
      _lastListMaxId = maxId;

      listEl.innerHTML = list.map((item) => renderCard(item, hasNew && item.id === maxId)).join('');
      listEl.querySelectorAll('.btn-audit-approve').forEach((btn) => {
        btn.addEventListener('click', () => doApprove(Number(btn.dataset.id)));
      });
      listEl.querySelectorAll('.btn-audit-reject').forEach((btn) => {
        btn.addEventListener('click', () => doReject(Number(btn.dataset.id)));
      });
      listEl.querySelectorAll('.audit-sel-order-type').forEach((sel) => {
        syncPriceInputForOrderType(sel);
      });

      if (scrollBottom || hasNew) {
        const snapToBottom = scrollBottom && !_didInitialAuditScroll;
        if (scrollBottom) _didInitialAuditScroll = true;
        scrollAuditToBottom(!snapToBottom);
        if (snapToBottom) {
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              if (!listEl) return;
              listEl.scrollTop = listEl.scrollHeight;
              scrollAuditListIntoViewBottom();
            });
          });
        }
      }
    } catch (e) {
      if (listEl && !listEl.querySelector('.order-audit-card')) {
        listEl.innerHTML = `<p class="order-audit-empty">${esc(e.message || '加载失败')}</p>`;
      }
    }
  }

  async function doApprove(id) {
    if (!window.api?.orderAudit || !listEl) return;
    if (_auditGateActionBusy) return;
    const card = listEl.querySelector(`article.order-audit-card[data-id="${id}"]`);
    const price = card?.querySelector('.audit-inp-price')?.value?.trim() ?? '';
    const stop_loss_price = card?.querySelector('.audit-inp-sl')?.value?.trim() ?? '';
    const take_profit_price = card?.querySelector('.audit-inp-tp')?.value?.trim() ?? '';
    const order_type = card?.querySelector('.audit-sel-order-type')?.value ?? 'limit';
    if (order_type === 'limit' && !price) {
      alert('限价单请填写委托价格');
      return;
    }
    _auditGateActionBusy = true;
    setAuditCardBusy(card, true);
    markPerfBoost(7000);
    try {
      await window.api.orderAudit.approve(id, {
        price,
        stop_loss_price,
        take_profit_price,
        order_type,
      });
      await refreshList(true, false);
    } catch (e) {
      alert(e.message || '执行失败');
      await refreshList(true, false);
    } finally {
      _auditGateActionBusy = false;
    }
  }

  async function doReject(id) {
    if (!window.api?.orderAudit || !listEl) return;
    if (_auditGateActionBusy) return;
    const card = listEl.querySelector(`article.order-audit-card[data-id="${id}"]`);
    _auditGateActionBusy = true;
    resetAuditForm(card);
    setAuditCardBusy(card, true);
    markPerfBoost(6000);
    try {
      await window.api.orderAudit.reject(id);
      await refreshList(true, false);
    } catch (e) {
      alert(e.message || '操作失败');
      await refreshList(true, false);
    } finally {
      _auditGateActionBusy = false;
    }
  }

  async function loadKeyStatus() {
    if (!keyStatus || !window.api?.users?.preferences) return;
    try {
      const res = await window.api.users.preferences();
      const has = res.data?.has_deepseek_key;
      keyStatus.textContent = has ? '已保存 API Key（仅保存在本机后端）' : '未绑定，请填写后保存';
      keyStatus.className = 'deepseek-key-status' + (has ? ' is-ok' : '');
    } catch (_) {
      keyStatus.textContent = '登录后可绑定';
    }
  }

  btnSave?.addEventListener('click', async () => {
    if (!window.api?.users?.updatePreferences) return;
    const v = (keyInput?.value || '').trim();
    try {
      await window.api.users.updatePreferences({ deepseek_api_key: v || '' });
      if (keyInput) keyInput.value = '';
      await loadKeyStatus();
    } catch (e) {
      alert(e.message || '保存失败');
    }
  });

  /**
   * 自选列表：逐标的运行策略引擎 + DeepSeek 审核；支持中止与状态栏进度。
   * @param {{ autoFromTrading?: boolean }} opts
   */
  async function runWatchlistOrderAuditCore(opts) {
    const o = opts || {};
    const autoFromTrading = !!o.autoFromTrading;
    if (!window.api?.orderAudit || !window.api?.dashboard?.watchlist) {
      finishBatchAndNotifyWaiters();
      return;
    }
    const wlRes = await window.api.dashboard.watchlist();
    const items =
      wlRes.data?.items ||
      (wlRes.data?.symbols || []).map((s) => ({ symbol: s, quote_market: 'spot' }));
    _watchlistTotal = items.length;
    updateAuditStatusBar();

    if (!items.length) {
      if (autoFromTrading) {
        alert('交易已开启，但自选列表为空。请先添加自选标的，然后停止并重新开始交易以运行订单审核。');
      } else {
        alert('请先在「自选」中添加至少一个标的');
      }
      finishBatchAndNotifyWaiters();
      return;
    }

    const curSym = window.getDashboardCurrentSymbol?.() || null;
    const interval = window.getDashboardCurrentInterval?.() || '1h';
    const priceEl = document.getElementById('kline-realtime-price');
    const lastForChart = priceEl?.textContent?.trim() || '';

    _auditBatchInProgress = true;
    _auditBatchAbort = false;
    _batchTotal = items.length;
    _batchCurrent = 0;
    updateAuditStatusBar();

    let ok = 0;
    let fail = 0;
    const errors = [];

    try {
      for (let i = 0; i < items.length; i += 1) {
        if (_auditBatchAbort) break;
        _batchCurrent = i + 1;
        updateAuditStatusBar();
        const sym = items[i].symbol;
        const qm = items[i].quote_market || 'spot';
        const base = {
          symbol: sym,
          interval,
          signal: {
            source: 'watchlist_strategy_engine_deepseek',
            note: '自选标的批量：多因子/评估/动态权重/ML/回测/仓位引擎 + DeepSeek 订单审核',
            quote_market: qm,
            watchlist_symbols: items.map((x) => x.symbol),
            audit_batch_index: i + 1,
            audit_batch_total: items.length,
            chart_last_price: sym === curSym && lastForChart ? lastForChart : undefined,
          },
        };
        try {
          await window.api.orderAudit.generateWithStrategyEngine(base);
          ok += 1;
        } catch (e) {
          fail += 1;
          errors.push(`${sym}: ${e.message || String(e)}`);
        }
      }
    } finally {
      finishBatchAndNotifyWaiters();
    }

    await refreshList(true, true);

    if (autoFromTrading && _auditBatchAbort) {
      return;
    }
    if (fail > 0) {
      const head = errors.slice(0, 6).join('\n');
      const more = errors.length > 6 ? `\n… 另有 ${errors.length - 6} 条` : '';
      alert(`批量审核结束：成功 ${ok}，失败 ${fail}。\n${head}${more}`);
    } else if (ok === 0) {
      alert('未生成任何审核单，请检查网络与后端日志。');
    }
  }

  document.getElementById('btn-trading-toggle')?.addEventListener('click', async () => {
    if (!window.api?.dashboard?.setTradingState) return;
    const btn = document.getElementById('btn-trading-toggle');
    if (!btn) return;
    const running = btn.dataset.running === 'true';
    btn.disabled = true;
    btn.classList.add('btn-ui-loading');
    btn.innerHTML = tradingLoadingHtml();
    markPerfBoost(8000);
    try {
      if (!running) {
        await window.api.dashboard.setTradingState({ trading_running: true });
        if (window.refreshDashboardTradingStatus) await window.refreshDashboardTradingStatus();
        _auditBatchAbort = false;
        _klineOpenedDistinct.clear();
        const cur = window.getDashboardCurrentSymbol?.();
        if (cur) _klineOpenedDistinct.add(String(cur).toUpperCase());
        updateAuditStatusBar();
        await runWatchlistOrderAuditCore({ autoFromTrading: true });
      } else {
        _auditBatchAbort = true;
        await waitUntilAuditBatchIdle();
        await window.api.dashboard.setTradingState({ trading_running: false });
        _klineOpenedDistinct.clear();
        if (window.refreshDashboardTradingStatus) await window.refreshDashboardTradingStatus();
      }
    } catch (e) {
      alert(e?.message || (running ? '无法停止交易' : '无法开始交易'));
    } finally {
      if (window.refreshDashboardTradingStatus) await window.refreshDashboardTradingStatus();
      btn.classList.remove('btn-ui-loading');
      btn.disabled = false;
      updateAuditStatusBar();
    }
  });

  window.addEventListener('dashboard-kline-symbol', () => {
    if (!isTradingRunning()) return;
    const s = window.getDashboardCurrentSymbol?.();
    if (s) {
      _klineOpenedDistinct.add(String(s).toUpperCase());
      updateAuditStatusBar();
    }
  });

  function startPoll() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(() => {
      if (shouldPausePolling()) return;
      if (_auditGateActionBusy) return;
      refreshList(false, false);
    }, 12000);
  }

  async function syncWatchlistCountOnce() {
    try {
      if (!window.api?.dashboard?.watchlist) return;
      const r = await window.api.dashboard.watchlist();
      const n = (r.data?.items || r.data?.symbols || []).length;
      _watchlistTotal = n;
    } catch (_) {}
    updateAuditStatusBar();
  }

  const btnCustodyStart = document.getElementById('btn-custody-start');
  const btnCustodyStop = document.getElementById('btn-custody-stop');
  const custodyStatusEl = document.getElementById('custody-status-text');
  const custodyMaxInput = document.getElementById('custody-max-opens-input');
  const custodyExecutedTodayEl = document.getElementById('custody-executed-today');
  const btnCustodySaveLimit = document.getElementById('btn-custody-save-limit');

  async function refreshCustodyUi() {
    if (!window.api?.orderAudit?.custodyStatus) return;
    try {
      const r = await window.api.orderAudit.custodyStatus();
      const d = r.data || {};
      const cr = !!d.custody_running;
      const cap = Number(d.custody_max_opens_per_day) || 0;
      const ex = Number(d.custody_executed_today) || 0;
      if (custodyMaxInput) custodyMaxInput.value = String(cap);
      if (custodyExecutedTodayEl) {
        custodyExecutedTodayEl.textContent =
          cap > 0 ? `今日托管已成交 ${ex} / ${cap}` : `今日托管已成交 ${ex} 次`;
      }
      if (btnCustodyStart) btnCustodyStart.hidden = cr;
      if (btnCustodyStop) btnCustodyStop.hidden = !cr;
      if (custodyStatusEl) {
        custodyStatusEl.textContent = cr
          ? '托管运行中：按策略中心所选订阅的用户策略执行（无人工审核）'
          : '';
      }
    } catch (_) {
      if (custodyStatusEl) custodyStatusEl.textContent = '';
    }
  }
  window.refreshCustodyUi = refreshCustodyUi;

  btnCustodySaveLimit?.addEventListener('click', async () => {
    if (!window.api?.orderAudit?.custodySettings) return;
    try {
      const raw = parseInt(custodyMaxInput?.value || '0', 10);
      const n = Number.isFinite(raw) && raw >= 0 ? Math.min(9999, raw) : 0;
      const r = await window.api.orderAudit.custodySettings({ custody_max_opens_per_day: n });
      if (r.success === false) throw new Error(r.message || '保存失败');
      await refreshCustodyUi();
    } catch (e) {
      alert(e?.message || String(e));
    }
  });

  btnCustodyStart?.addEventListener('click', async () => {
    if (!window.api?.orderAudit?.custodyStart) return;
    try {
      const r = await window.api.orderAudit.custodyStart();
      if (r.success === false) throw new Error(r.message || '开启失败');
      await refreshCustodyUi();
    } catch (e) {
      alert(e?.message || String(e));
    }
  });
  btnCustodyStop?.addEventListener('click', async () => {
    if (!window.api?.orderAudit?.custodyStop) return;
    try {
      const r = await window.api.orderAudit.custodyStop();
      if (r.success === false) throw new Error(r.message || '停止失败');
      await refreshCustodyUi();
    } catch (e) {
      alert(e?.message || String(e));
    }
  });

  void refreshCustodyUi();

  if (listEl) {
    listEl.addEventListener('change', (e) => {
      const t = e.target;
      if (t && t.classList && t.classList.contains('audit-sel-order-type')) {
        syncPriceInputForOrderType(t);
      }
    });
    loadKeyStatus();
    refreshList(true, false);
    startPoll();
    syncWatchlistCountOnce();
  }
})();
