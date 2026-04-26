/** 策略页 · 可视化组合回测（Lightweight Charts） */
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function getBrokerMode() {
  try {
    if (window.api?.broker?.status) {
      const r = await window.api.broker.status();
      return r?.data?.current_mode || 'simulated';
    }
  } catch (_) {}
  return localStorage.getItem('trading_mode') || 'simulated';
}

/** 与策略中心、strategy_definitions 一致（内置策略订阅展示） */
const BT_BUILTIN_NAMES = { 1: '稳健增长', 2: '积极进取' };
const BT_USER_CAPS = { max_position_pct: 0.3, max_single_order_pct: 0.1 };
/** 与 backend services/strategy_engine/factors.py DEFAULT_BUILTIN_FACTOR_IDS 一致 */
const BT_BUILTIN_DEFAULT_FACTORS = ['rev_1', 'vol_20', 'vol_z'];

function btSubscriptionLabel(sub, userList) {
  const usid =
    sub.user_strategy_id != null && Number(sub.user_strategy_id) > 0 ? Number(sub.user_strategy_id) : null;
  const sid = sub.strategy_id != null ? Number(sub.strategy_id) : 0;
  let namePart;
  if (usid) {
    const r = userList.find((x) => x.id === usid);
    namePart = r ? r.name : `策略#${usid}`;
  } else if (sid > 0) {
    namePart = BT_BUILTIN_NAMES[sid] || `内置策略#${sid}`;
  } else {
    namePart = '订阅';
  }
  return `${namePart} · 模式 ${sub.mode} · 订阅 #${sub.id}`;
}

async function btSubscribeBuiltin(strategyId) {
  const mode = await getBrokerMode();
  if (!window.api?.strategies?.subscribe) return;
  try {
    await window.api.strategies.subscribe({ strategy_id: strategyId, mode, params: {} });
    alert('订阅成功');
    await loadUserStrategyList();
  } catch (e) {
    alert(e.message || String(e));
  }
}

const LS_FAV = 'backtest_factor_favorites';
const LS_ACTIVE = 'backtest_active_factors';
const LS_BT_INTERVAL = 'backtest_last_interval';
const LS_BT_MAX_OPENS_DAY = 'backtest_max_opens_day';
const LS_BT_AVG_DAILY_MODE = 'backtest_avg_daily_mode';

let _btFactorMeta = [];

/** 回测日期：null = 使用后端「最近 2000 根」；否则 { startDate, endDate } YYYY-MM-DD */
const BT_RANGE_LS = 'backtest_range_ymd';
let _btRangeStart = null;
let _btRangeEnd = null;
let _btCalLeftY = 0;
let _btCalLeftM0 = 0;
let _btEditWhich = 'start';

function formatZhYmd(ymd) {
  if (!ymd || ymd.length < 10) return ymd;
  const [ys, ms, ds] = ymd.split('-');
  const y = parseInt(ys, 10);
  const m = parseInt(ms, 10);
  const d = parseInt(ds, 10);
  const dt = new Date(y, m - 1, d);
  const wk = ['日', '一', '二', '三', '四', '五', '六'][dt.getDay()];
  return `${y}年${m}月${d}日 周${wk}`;
}

function loadBacktestRangeFromLS() {
  try {
    const raw = localStorage.getItem(BT_RANGE_LS);
    if (!raw) return;
    const j = JSON.parse(raw);
    if (j && j.start && j.end) {
      _btRangeStart = j.start;
      _btRangeEnd = j.end;
    }
  } catch (_) {}
}

function saveBacktestRangeToLS() {
  if (_btRangeStart && _btRangeEnd) {
    localStorage.setItem(BT_RANGE_LS, JSON.stringify({ start: _btRangeStart, end: _btRangeEnd }));
  } else {
    localStorage.removeItem(BT_RANGE_LS);
  }
}

function syncRangeChips() {
  const cs = document.getElementById('bt-chip-start');
  const ce = document.getElementById('bt-chip-end');
  if (!cs || !ce) return;
  if (_btRangeStart && _btRangeEnd) {
    cs.textContent = formatZhYmd(_btRangeStart);
    ce.textContent = formatZhYmd(_btRangeEnd);
  } else {
    cs.textContent = '自动（最近）';
    ce.textContent = '约 2000 根 K 线';
  }
}

function getBacktestRangeForApi() {
  if (_btRangeStart && _btRangeEnd) return { startDate: _btRangeStart, endDate: _btRangeEnd };
  return {};
}

function markBacktestReportStale() {
  if (!window._lastBacktestData) return;
  window._lastBacktestStale = true;
  const b = document.getElementById('bt-stale-banner');
  if (b) b.hidden = false;
}

function clearStaleBanner() {
  window._lastBacktestStale = false;
  const b = document.getElementById('bt-stale-banner');
  if (b) b.hidden = true;
}

function setRangePopoverTabs(which) {
  _btEditWhich = which === 'end' ? 'end' : 'start';
  document.querySelectorAll('.bt-range-tab').forEach((btn) => {
    const w = btn.getAttribute('data-which');
    const on = w === _btEditWhich;
    btn.classList.toggle('is-active', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  const t = document.getElementById('bt-range-pop-title');
  if (t) t.textContent = _btEditWhich === 'start' ? '选择回测开始日期' : '选择回测结束日期';
  const pop = document.getElementById('bt-range-popover');
  if (pop && !pop.hidden) renderRangeCalendars();
}

function anchorCalToRangeStart() {
  const now = new Date();
  if (_btRangeStart) {
    const p = _btRangeStart.split('-').map((x) => parseInt(x, 10));
    _btCalLeftY = p[0];
    _btCalLeftM0 = p[1] - 1;
  } else {
    _btCalLeftY = now.getFullYear();
    _btCalLeftM0 = now.getMonth();
  }
}

function shiftCalAnchor(dm) {
  const d = new Date(_btCalLeftY, _btCalLeftM0 + dm, 1);
  _btCalLeftY = d.getFullYear();
  _btCalLeftM0 = d.getMonth();
  renderRangeCalendars();
}

function renderMonthTable(y, m0) {
  const firstDow = new Date(y, m0, 1).getDay();
  const dim = new Date(y, m0 + 1, 0).getDate();
  const weeks = [];
  let row = new Array(7).fill(null);
  let col = firstDow;
  for (let day = 1; day <= dim; day++) {
    row[col] = day;
    col++;
    if (col === 7) {
      weeks.push(row);
      row = new Array(7).fill(null);
      col = 0;
    }
  }
  if (row.some((x) => x != null)) weeks.push(row);
  const head = ['日', '一', '二', '三', '四', '五', '六']
    .map((h) => `<th>${h}</th>`)
    .join('');
  const body = weeks
    .map((r) => {
      const cells = r
        .map((day) => {
          if (day == null) return '<td class="bt-cal-empty"></td>';
          const ymd = `${y}-${String(m0 + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
          let cls = 'bt-cal-day';
          if (_btRangeStart && _btRangeEnd) {
            if (ymd === _btRangeStart) cls += ' is-range-start';
            if (ymd === _btRangeEnd) cls += ' is-range-end';
            if (ymd > _btRangeStart && ymd < _btRangeEnd) cls += ' is-in-range';
          }
          return `<td><button type="button" class="${cls}" data-ymd="${ymd}">${day}</button></td>`;
        })
        .join('');
      return `<tr>${cells}</tr>`;
    })
    .join('');
  return `<table class="bt-cal-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderRangeCalendars() {
  const w0 = document.getElementById('bt-cal-wrap-0');
  const w1 = document.getElementById('bt-cal-wrap-1');
  const nav = document.getElementById('bt-cal-nav-label');
  if (!w0 || !w1) return;
  const y0 = _btCalLeftY;
  const m0 = _btCalLeftM0;
  const d1 = new Date(y0, m0 + 1, 1);
  const y1 = d1.getFullYear();
  const m1 = d1.getMonth();
  if (nav) nav.textContent = `${monthTitle(y0, m0)}　·　${monthTitle(y1, m1)}`;
  w0.innerHTML = `<div class="bt-cal-head">${monthTitle(y0, m0)}</div>${renderMonthTable(y0, m0)}`;
  w1.innerHTML = `<div class="bt-cal-head">${monthTitle(y1, m1)}</div>${renderMonthTable(y1, m1)}`;
  w0.querySelectorAll('.bt-cal-day').forEach((btn) => {
    btn.addEventListener('click', () => onPickYmd(btn.getAttribute('data-ymd')));
  });
  w1.querySelectorAll('.bt-cal-day').forEach((btn) => {
    btn.addEventListener('click', () => onPickYmd(btn.getAttribute('data-ymd')));
  });
}

function monthTitle(y, m0) {
  return `${y}年${m0 + 1}月`;
}

function onPickYmd(ymd) {
  if (!ymd) return;
  if (_btEditWhich === 'start') {
    _btRangeStart = ymd;
    if (_btRangeEnd && _btRangeEnd < _btRangeStart) {
      const t = _btRangeEnd;
      _btRangeEnd = _btRangeStart;
      _btRangeStart = t;
    }
    setRangePopoverTabs('end');
  } else {
    _btRangeEnd = ymd;
    if (_btRangeStart && _btRangeEnd < _btRangeStart) {
      const t = _btRangeStart;
      _btRangeStart = _btRangeEnd;
      _btRangeEnd = t;
    }
  }
  syncRangeChips();
  renderRangeCalendars();
}

function openRangePopover(which) {
  setRangePopoverTabs(which || 'start');
  anchorCalToRangeStart();
  const pop = document.getElementById('bt-range-popover');
  const bd = document.getElementById('bt-range-backdrop');
  if (pop) pop.hidden = false;
  if (bd) bd.hidden = false;
  renderRangeCalendars();
}

function closeRangePopover() {
  const pop = document.getElementById('bt-range-popover');
  const bd = document.getElementById('bt-range-backdrop');
  if (pop) pop.hidden = true;
  if (bd) bd.hidden = true;
}

function initBacktestRangeUI() {
  loadBacktestRangeFromLS();
  syncRangeChips();

  // 初始化 interval：用于与启动时因子库刷新对齐
  try {
    const ivEl = document.getElementById('bt-interval');
    const saved = localStorage.getItem(LS_BT_INTERVAL);
    if (ivEl && saved && typeof saved === 'string') ivEl.value = saved;
  } catch (_) {}
  try {
    const moEl = document.getElementById('bt-max-opens-day');
    const savedMo = localStorage.getItem(LS_BT_MAX_OPENS_DAY);
    if (moEl && savedMo != null && savedMo !== '') moEl.value = savedMo;
  } catch (_) {}
  try {
    const dmEl = document.getElementById('bt-avg-daily-mode');
    const savedDm = localStorage.getItem(LS_BT_AVG_DAILY_MODE);
    if (dmEl && (savedDm === 'trading' || savedDm === 'natural')) dmEl.value = savedDm;
  } catch (_) {}

  const pop = document.getElementById('bt-range-popover');
  if (pop && !document.getElementById('bt-cal-nav-bar')) {
    const tabs = pop.querySelector('.bt-range-pop-tabs');
    if (tabs) {
      const bar = document.createElement('div');
      bar.id = 'bt-cal-nav-bar';
      bar.className = 'bt-cal-nav-bar';
      bar.innerHTML =
        '<button type="button" class="bt-cal-nav-btn" id="bt-cal-prev" aria-label="上一组月份">‹</button><span id="bt-cal-nav-label" class="bt-cal-nav-label"></span><button type="button" class="bt-cal-nav-btn" id="bt-cal-next" aria-label="下一组月份">›</button>';
      tabs.insertAdjacentElement('afterend', bar);
      document.getElementById('bt-cal-prev')?.addEventListener('click', () => shiftCalAnchor(-1));
      document.getElementById('bt-cal-next')?.addEventListener('click', () => shiftCalAnchor(1));
    }
  }
  document.getElementById('bt-chip-start')?.addEventListener('click', () => openRangePopover('start'));
  document.getElementById('bt-chip-end')?.addEventListener('click', () => openRangePopover('end'));
  document.getElementById('bt-open-range-pop')?.addEventListener('click', () => openRangePopover('start'));
  document.getElementById('bt-range-pop-close')?.addEventListener('click', () => closeRangePopover());
  document.getElementById('bt-range-backdrop')?.addEventListener('click', () => closeRangePopover());
  document.querySelectorAll('.bt-range-tab').forEach((btn) => {
    btn.addEventListener('click', () => setRangePopoverTabs(btn.getAttribute('data-which') || 'start'));
  });
  document.getElementById('bt-range-apply')?.addEventListener('click', () => {
    saveBacktestRangeToLS();
    markBacktestReportStale();
    closeRangePopover();
  });
  document.getElementById('bt-range-recent')?.addEventListener('click', () => {
    _btRangeStart = null;
    _btRangeEnd = null;
    saveBacktestRangeToLS();
    syncRangeChips();
    markBacktestReportStale();
    closeRangePopover();
  });
}

function loadFavoriteIds() {
  try {
    const raw = localStorage.getItem(LS_FAV);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.map(String) : [];
  } catch (_) {
    return [];
  }
}

function saveFavoriteIds(ids) {
  localStorage.setItem(LS_FAV, JSON.stringify([...new Set(ids)]));
}

function loadActiveIdsFromLS(allIdsSet) {
  try {
    const raw = localStorage.getItem(LS_ACTIVE);
    if (!raw) return null;
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return null;
    const f = arr.map(String).filter((x) => allIdsSet.has(x));
    return f.length ? f : null;
  } catch (_) {
    return null;
  }
}

function saveActiveIds(ids) {
  localStorage.setItem(LS_ACTIVE, JSON.stringify(ids));
}

function collectActiveFactorIds() {
  const nodes = document.querySelectorAll('.bt-fac-cb:checked');
  return Array.from(nodes)
    .map((n) => n.getAttribute('data-id'))
    .filter(Boolean);
}

function applyFactorSelection(selectedIds) {
  const allow = new Set((selectedIds || []).map(String));
  document.querySelectorAll('.bt-fac-cb').forEach((el) => {
    const id = el.getAttribute('data-id');
    el.checked = allow.has(id);
  });
  ensureAtLeastOneFactor();
  saveActiveIds(collectActiveFactorIds());
  syncFavoriteCheckboxes();
  markBacktestReportStale();
}

function resetBacktestEditorToDefaults(preferredFactorIds) {
  const s = document.getElementById('bt-symbols');
  if (s) s.value = '';
  const iv = document.getElementById('bt-interval');
  if (iv) iv.value = '1h';
  const mo = document.getElementById('bt-max-opens-day');
  if (mo) mo.value = '0';
  const adm = document.getElementById('bt-avg-daily-mode');
  if (adm) adm.value = 'trading';
  if (preferredFactorIds && preferredFactorIds.length) {
    applyFactorSelection(preferredFactorIds);
  } else {
    applyFactorSelection([]);
  }
  renderFavorites();
  markBacktestReportStale();
  try {
    window._lastBacktestData = null;
  } catch (_) {}
}

function ensureAtLeastOneFactor() {
  if (collectActiveFactorIds().length) return;
  const first = document.querySelector('.bt-fac-cb');
  if (first) first.checked = true;
  saveActiveIds(collectActiveFactorIds());
}

function syncFavoriteCheckboxes() {
  const active = new Set(collectActiveFactorIds());
  document.querySelectorAll('.bt-fav-cb').forEach((el) => {
    const id = el.getAttribute('data-id');
    el.checked = active.has(id);
  });
}

function onLibraryCheckboxChange() {
  saveActiveIds(collectActiveFactorIds());
  syncFavoriteCheckboxes();
  markBacktestReportStale();
}

function renderFavorites() {
  const wrap = document.getElementById('bt-factor-fav');
  if (!wrap) return;
  const fav = loadFavoriteIds().filter((id) => _btFactorMeta.some((x) => x.id === id));
  if (fav.length === 0) {
    wrap.innerHTML = '<p class="backtest-hint">暂无自选，请在因子库点击「加入自选」。</p>';
    return;
  }
  const active = new Set(collectActiveFactorIds());
  wrap.innerHTML = fav
    .map((id) => {
      const meta = _btFactorMeta.find((x) => x.id === id);
      const name = meta ? meta.name : id;
      const ck = active.has(id) ? ' checked' : '';
      return `<div class="bt-fav-row">
  <label><input type="checkbox" class="bt-fav-cb" data-id="${esc(id)}"${ck} /> ${esc(name)}</label>
  <span class="bt-fac-id">${esc(id)}</span>
  <button type="button" class="bt-fav-remove" data-rm-fav="${esc(id)}">移除自选</button>
</div>`;
    })
    .join('');

  wrap.querySelectorAll('.bt-fav-cb').forEach((el) => {
    el.addEventListener('change', () => {
      const id = el.getAttribute('data-id');
      const lib = id ? document.getElementById(`bt-fac-${id}`) : null;
      if (lib) {
        lib.checked = el.checked;
        if (!collectActiveFactorIds().length) {
          lib.checked = true;
          el.checked = true;
        }
      }
      onLibraryCheckboxChange();
    });
  });
  wrap.querySelectorAll('[data-rm-fav]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const id = btn.getAttribute('data-rm-fav');
      if (!id) return;
      saveFavoriteIds(loadFavoriteIds().filter((x) => x !== id));
      renderFavorites();
    });
  });
}

function renderFactorLibrary() {
  const wrap = document.getElementById('bt-factor-lib');
  if (!wrap || !_btFactorMeta.length) {
    if (wrap) wrap.innerHTML = '<p class="backtest-hint">加载因子库中…</p>';
    return;
  }
  const allIds = _btFactorMeta.map((f) => f.id);
  const idSet = new Set(allIds);
  let active = loadActiveIdsFromLS(idSet);
  if (!active) active = [...allIds];

  wrap.innerHTML = _btFactorMeta
    .map((f) => {
      const ck = active.includes(f.id) ? ' checked' : '';
      return `<label class="bt-fac-row">
  <input type="checkbox" class="bt-fac-cb" data-id="${esc(f.id)}" id="bt-fac-${esc(f.id)}"${ck} />
  <span class="bt-fac-name">${esc(f.name || f.id)}</span>
  <span class="bt-fac-id">${esc(f.id)}</span>
  <button type="button" class="bt-fac-add-fav" data-add-fav="${esc(f.id)}">加入自选</button>
</label>
<div class="bt-fac-desc">${esc(f.description || '')}</div>`;
    })
    .join('');

  wrap.querySelectorAll('.bt-fac-cb').forEach((el) => {
    el.addEventListener('change', () => {
      if (!collectActiveFactorIds().length) {
        el.checked = true;
      }
      onLibraryCheckboxChange();
    });
  });
  wrap.querySelectorAll('[data-add-fav]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const id = btn.getAttribute('data-add-fav');
      if (!id) return;
      const fav = loadFavoriteIds();
      if (!fav.includes(id)) {
        fav.push(id);
        saveFavoriteIds(fav);
        renderFavorites();
      }
    });
  });
  saveActiveIds(collectActiveFactorIds());
  renderFavorites();
}

async function initFactorPanel() {
  const wrap = document.getElementById('bt-factor-lib');
  if (!window.api?.strategyEngine?.factorLibrary) {
    if (wrap) wrap.innerHTML = '<p class="backtest-hint">API 不支持因子库</p>';
    return;
  }
  try {
    const res = await window.api.strategyEngine.factorLibrary();
    if (!res.success || !res.data?.factors) throw new Error(res.message || '加载失败');
    _btFactorMeta = res.data.factors;
    renderFactorLibrary();
  } catch (e) {
    if (wrap) wrap.innerHTML = `<p class="analytics-err" style="display:block">${esc(e.message)}</p>`;
  }
}

async function pollFactorRefresh(jobId, timeoutMs = 8 * 60 * 1000) {
  const notice = document.getElementById('bt-factor-refresh-notice');
  const t0 = Date.now();
  while (true) {
    if (Date.now() - t0 > timeoutMs) {
      if (notice) {
        notice.hidden = false;
        notice.textContent = '因子库更新超时，请稍后再试';
      }
      return { done: false, status: 'timeout' };
    }
    const res = await window.api.strategyEngine.factorLibraryRefreshStatus(jobId);
    if (!res.success) throw new Error(res.message || '查询刷新状态失败');
    const d = res.data || {};
    const st = d.status || '';
    if (notice) {
      notice.hidden = false;
      if (st === 'running') notice.textContent = '正在挖掘/评估因子，请稍等…';
      else if (st === 'pending') notice.textContent = '因子库刷新已提交，排队中…';
      else if (st === 'failed') notice.textContent = d.error_message ? `刷新失败：${d.error_message}` : '刷新失败';
      else if (st === 'done') {
        notice.textContent = d.user_message ? String(d.user_message) : '因子库更新完成';
      } else notice.textContent = `因子库刷新状态：${st || '—'}`;
    }
    if (st === 'done') return { done: true, status: st, data: d };
    if (st === 'failed') return { done: true, status: st, data: d };
    await new Promise((r) => setTimeout(r, 2000));
  }
}

document.getElementById('bt-mine-factors-btn')?.addEventListener('click', async () => {
  const btn = document.getElementById('bt-mine-factors-btn');
  if (!btn || !window.api?.strategyEngine?.factorLibraryRefreshAsync) return;
  const notice = document.getElementById('bt-factor-refresh-notice');
  try {
    btn.disabled = true;
    if (notice) {
      notice.hidden = false;
      notice.textContent = '正在提交因子库刷新任务…';
    }
    const interval = document.getElementById('bt-interval')?.value || '1h';
    const res = await window.api.strategyEngine.factorLibraryRefreshAsync({
      interval,
      candidate_count: 50,
      top_keep: 10,
      lib_cap_n: 30,
      user_prompt: '', // 当前页先不收集挖掘需求文本；可后续扩展
    });
    if (!res.success || !res.data?.job_id) throw new Error(res.message || '提交失败');
    const jobId = res.data.job_id;
    markBacktestReportStale();
    const out = await pollFactorRefresh(jobId);
    if (out?.status === 'done') {
      await initFactorPanel();
      markBacktestReportStale();
    }
  } catch (e) {
    if (notice) {
      notice.hidden = false;
      notice.textContent = e?.message || String(e);
    }
  } finally {
    if (btn) btn.disabled = false;
  }
});

function compactBacktestSummary(d) {
  if (!d) return {};
  const p = d.portfolio || {};
  return {
    portfolio_ok: p.ok,
    portfolio_reason: p.reason,
    bars: p.bars,
    open_count_total: p.open_count_total,
    open_count_mean: p.open_count_mean,
    avg_daily_open_count: p.avg_daily_open_count,
    total_return: p.total_return,
    sharpe_approx: p.sharpe_approx,
    alpha_vs_buyhold: p.alpha_vs_buyhold,
    max_drawdown: p.max_drawdown,
    benchmark_total_return: p.benchmark_total_return,
    symbols_in_portfolio: p.symbols_in_portfolio,
    active_factors_used: d.active_factors_used || [],
    factor_impact_scores: (d.factor_impact_scores || []).map((x) => ({
      factor: x.factor,
      impact_score: x.impact_score,
      avg_icir: x.avg_icir,
      suggest_remove_factor: x.suggest_remove_factor,
    })),
    insignificant_symbols_analysis: (d.insignificant_symbols_analysis || []).slice(0, 14).map((r) => ({
      symbol: r.symbol,
      open_count: r.open_count,
      t_statistic: r.t_statistic,
      cumulative_return: r.cumulative_return,
      suggest_remove_from_portfolio: r.suggest_remove_from_portfolio,
      verdict: r.verdict,
    })),
  };
}

async function runDeepseekFactor(mode, extraPrompt) {
  const out = document.getElementById('bt-ds-out');
  const promptEl = document.getElementById('bt-ds-prompt');
  const userPrompt = [extraPrompt || '', promptEl?.value || ''].filter(Boolean).join('\n').trim();
  if (out) {
    out.hidden = false;
    out.textContent = '请求 DeepSeek 中…';
  }
  let summary;
  if (mode === 'optimize') {
    summary = compactBacktestSummary(window._lastBacktestData);
  }
  const res = await window.api.strategyEngine.deepseekFactorScreen({
    mode,
    user_prompt: userPrompt,
    current_factors: collectActiveFactorIds(),
    backtest_summary: summary,
  });
  if (!res.success) {
    if (out) out.textContent = res.message || '失败';
    return;
  }
  const data = res.data || {};
  applyFactorSelection(data.selected_factors || []);
  renderFavorites();
  const lines = [
    data.strategy_summary && `【策略摘要】${data.strategy_summary}`,
    data.rationale && `【说明】${data.rationale}`,
    data.changes && data.changes.length && `【变更】${data.changes.join('；')}`,
    `【已勾选因子】${(data.selected_factors || []).join(', ')}`,
  ].filter(Boolean);
  if (out) out.textContent = lines.join('\n\n');
}

let _btChart = null;

function destroyBacktestChart() {
  if (_btChart) {
    try {
      _btChart.remove();
    } catch (_) {}
    _btChart = null;
  }
}

/** 主窗口从侧边栏切离「策略」模块时，清空回测图表与报告，避免 iframe 隐藏后仍保留旧结果 */
function resetBacktestVisualState() {
  window._lastBacktestData = null;
  clearStaleBanner();
  destroyBacktestChart();
  const wrap = document.getElementById('backtest-chart-wrap');
  if (wrap) wrap.innerHTML = '';
  const cap = document.getElementById('bt-chart-caption');
  if (cap) {
    cap.hidden = true;
    cap.textContent = '';
  }
  const st = document.getElementById('bt-status');
  if (st) {
    st.textContent =
      '请设置标的与因子后点击「运行回测」；长区间拉 K 线时仪表盘非必要轮询会自动暂停。';
  }
  const met = document.getElementById('bt-metrics');
  if (met) {
    met.style.display = 'none';
    met.innerHTML = '';
  }
  const errEl = document.getElementById('bt-err');
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = '';
  }
  renderSigTable([]);
  renderFactorTable([]);
  const secBr = document.getElementById('bt-brinson-section');
  const secFr = document.getElementById('bt-formal-risk-section');
  if (secBr) secBr.style.display = 'none';
  if (secFr) secFr.style.display = 'none';
  const disc = document.getElementById('bt-disclaimer');
  if (disc) disc.textContent = '';
  _btvWindow = null;
  _btvYmdStart = null;
  _btvYmdEnd = null;
  syncBtvChips();
  const btvSec = document.getElementById('bt-verify-section');
  if (btvSec) btvSec.style.display = 'none';
  destroyBtVerifyChart();
  const btvWrap = document.getElementById('bt-verify-chart-wrap');
  if (btvWrap) btvWrap.innerHTML = '';
  const btvLab = document.getElementById('bt-verify-seg-label');
  if (btvLab) btvLab.textContent = '';
  const repOut = document.getElementById('bt-report-out');
  if (repOut) {
    repOut.hidden = true;
    repOut.textContent = '';
  }
  const dsOut = document.getElementById('bt-ds-out');
  if (dsOut) {
    dsOut.hidden = true;
    dsOut.textContent = '';
  }
  destroyBtVerifyChart();
  const vwrap = document.getElementById('bt-verify-chart-wrap');
  if (vwrap) vwrap.innerHTML = '';
  const vsec = document.getElementById('bt-verify-section');
  if (vsec) vsec.style.display = 'none';
  const vst = document.getElementById('bt-verify-status');
  if (vst) vst.textContent = '';
  const vseg = document.getElementById('bt-verify-seg-label');
  if (vseg) vseg.textContent = '';
}

window.addEventListener('message', (ev) => {
  if (ev.data?.type === 'strategy-iframe-hidden') {
    resetBacktestVisualState();
  }
});

function drawEquityChart(portfolio) {
  const wrap = document.getElementById('backtest-chart-wrap');
  const cap = document.getElementById('bt-chart-caption');
  if (cap) {
    const tot = portfolio.open_count_total;
    const mean = portfolio.open_count_mean;
    const daily = portfolio.avg_daily_open_count;
    const dailyMode = portfolio.avg_daily_mode === 'natural' ? '自然日' : '交易日';
    if (tot != null && mean != null) {
      cap.hidden = false;
      cap.textContent = `开仓次数：合计 ${tot} 次（各标的平均 ${mean} 次，平均每日${dailyMode} ${daily != null ? daily : '—'} 次；信号由空转多计一次）`;
    } else {
      cap.hidden = true;
      cap.textContent = '';
    }
  }
  if (!wrap || typeof LightweightCharts === 'undefined') return;
  destroyBacktestChart();
  wrap.innerHTML = '';
  const ec = portfolio.equity_curve || [];
  const bc = portfolio.benchmark_curve || [];
  if (!ec.length) {
    wrap.innerHTML = '<p class="empty">无净值曲线数据</p>';
    if (cap) cap.hidden = true;
    return;
  }
  const w = Math.max(280, wrap.clientWidth || 600);
  const h = 300;
  _btChart = LightweightCharts.createChart(wrap, {
    layout: { background: { color: '#ffffff' }, textColor: '#1a1a2e', attributionLogo: false },
    grid: { vertLines: { color: '#f0f2f5' }, horzLines: { color: '#f0f2f5' } },
    width: w,
    height: h,
    rightPriceScale: { borderColor: '#e9ecef' },
    timeScale: { borderColor: '#e9ecef' },
  });
  const sStrat = _btChart.addLineSeries({ color: '#26a69a', lineWidth: 2 });
  const sBench = _btChart.addLineSeries({ color: '#90a4ae', lineWidth: 1, lineStyle: 2 });
  const baseT = Math.floor(Date.now() / 1000) - 86400 * 400;
  sStrat.setData(ec.map((p) => ({ time: baseT + (p.i || 0), value: p.v })));
  if (bc.length) {
    sBench.setData(bc.map((p) => ({ time: baseT + (p.i || 0), value: p.v })));
  }
  _btChart.timeScale().fitContent();
}

let _btVerifyChart = null;
let _btVerifyCandleSeries = null;

// K 线验真时段选择（起止日期，UTC 日界；跨度 1~7 日，且必须落在本次回测区间内）
const BTV_MAX_SPAN_DAYS = 7;
const BTV_MIN_SPAN_DAYS = 1;
let _btvYmdStart = null; // 'YYYY-MM-DD'
let _btvYmdEnd = null; // 'YYYY-MM-DD'
let _btvWindow = null; // { startYmd, endYmd, fromTs, toTs }
let _btvEditWhich = 'start';
let _btvCalLeftY = 0;
let _btvCalLeftM0 = 0;

function btNormTs(t) {
  const n = Number(t);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n > 1e12 ? Math.floor(n / 1000) : Math.floor(n);
}

function btPickDetailInterval(mainIv) {
  const m = { '1d': '4h', '4h': '1h', '1h': '15m', '15m': '5m', '5m': '1m', '30m': '5m', '1m': '1m' };
  return m[String(mainIv || '')] || '15m';
}

function btvYmdFromUtcSec(sec) {
  const n = btNormTs(sec);
  if (n == null) return null;
  return new Date(n * 1000).toISOString().slice(0, 10);
}

function btvUtcSecFromYmd(ymd, endOfDay) {
  if (!ymd || ymd.length < 10) return null;
  const p = ymd.split('-').map((x) => parseInt(x, 10));
  if (p.length !== 3 || p.some((n) => !Number.isFinite(n))) return null;
  const base = Date.UTC(p[0], p[1] - 1, p[2]) / 1000;
  return endOfDay ? base + 86399 : base;
}

function btvYmdAddDays(ymd, n) {
  const base = btvUtcSecFromYmd(ymd, false);
  if (base == null) return ymd;
  return btvYmdFromUtcSec(base + Math.round(n) * 86400);
}

function btvDaysBetweenInclusive(a, b) {
  if (!a || !b) return 0;
  const sa = btvUtcSecFromYmd(a, false);
  const sb = btvUtcSecFromYmd(b, false);
  if (sa == null || sb == null) return 0;
  return Math.floor((sb - sa) / 86400) + 1;
}

function btvClampYmd(ymd, win) {
  if (!ymd || !win) return ymd;
  if (ymd < win.startYmd) return win.startYmd;
  if (ymd > win.endYmd) return win.endYmd;
  return ymd;
}

function btvFormatSpanHint() {
  if (!_btvYmdStart || !_btvYmdEnd) return '';
  const n = btvDaysBetweenInclusive(_btvYmdStart, _btvYmdEnd);
  return `当前跨度 ${n} 日`;
}

function destroyBtVerifyChart() {
  if (_btVerifyChart) {
    try {
      _btVerifyChart.remove();
    } catch (_) {}
    _btVerifyChart = null;
    _btVerifyCandleSeries = null;
  }
}

function getBtVerifyRows(d) {
  return (d?.per_symbol || []).filter((x) => x.ok && x.symbol);
}

function findBtVerifyRow(d, symbol) {
  const u = String(symbol || '').trim().toUpperCase();
  return getBtVerifyRows(d).find((r) => String(r.symbol).toUpperCase() === u);
}

function snapMarkerTime(sortedTimes, t) {
  const tt = btNormTs(t);
  if (tt == null || !sortedTimes.length) return null;
  let best = sortedTimes[0];
  for (let i = 0; i < sortedTimes.length; i++) {
    if (sortedTimes[i] <= tt) best = sortedTimes[i];
    else break;
  }
  return best;
}

/** 同一细 K 上多条同类事件时保留最后一次，避免重复 time */
function dedupeBtLinePts(pts) {
  const map = new Map();
  for (const p of pts) map.set(p.time, p);
  return [...map.keys()]
    .sort((a, b) => a - b)
    .map((t) => map.get(t));
}

async function refreshBtVerifyChart() {
  const wrap = document.getElementById('bt-verify-chart-wrap');
  const st = document.getElementById('bt-verify-status');
  const segLab = document.getElementById('bt-verify-seg-label');
  const d = window._lastBacktestData;
  const symSel = document.getElementById('bt-verify-symbol');
  const symbol = (symSel?.value || '').trim();
  if (!wrap || !d || !symbol) {
    if (st) st.textContent = '';
    return;
  }
  const row = findBtVerifyRow(d, symbol);
  const sr = row?.series_range;
  if (!sr || sr.from_ts == null || sr.to_ts == null) {
    if (st) st.textContent = '该标的缺少时间范围，无法拉取细周期（请确认 K 线含 time 字段）。';
    destroyBtVerifyChart();
    wrap.innerHTML = '';
    return;
  }
  if (!_btvWindow || !_btvYmdStart || !_btvYmdEnd) {
    if (st) st.textContent = '请选择验真时段起止日期';
    return;
  }
  const sFromSec = Math.max(btvUtcSecFromYmd(_btvYmdStart, false), Number(sr.from_ts));
  const sToSec = Math.min(btvUtcSecFromYmd(_btvYmdEnd, true), Number(sr.to_ts));
  if (!(sFromSec < sToSec)) {
    if (st) st.textContent = '所选时段与该标的 K 线范围无交集';
    destroyBtVerifyChart();
    wrap.innerHTML = '';
    return;
  }
  const seg = { from_ts: sFromSec, to_ts: sToSec };
  const mainIv = document.getElementById('bt-interval')?.value || '1h';
  const manualIv = (document.getElementById('bt-verify-detail-iv')?.value || '').trim();
  const detailIv = manualIv || btPickDetailInterval(mainIv);
  if (segLab) {
    const fa = new Date(seg.from_ts * 1000).toISOString().slice(0, 16).replace('T', ' ');
    const fb = new Date(seg.to_ts * 1000).toISOString().slice(0, 16).replace('T', ' ');
    const days = btvDaysBetweenInclusive(_btvYmdStart, _btvYmdEnd);
    segLab.textContent = `选定 ${_btvYmdStart} ～ ${_btvYmdEnd}（${days} 日，UTC ${fa} ～ ${fb}） · 细周期 ${detailIv}（回测周期 ${mainIv}）`;
  }
  if (st) st.textContent = '正在拉取细周期 K 线…';
  if (!window.api?.market?.candlesticks) {
    if (st) st.textContent = 'API 未就绪';
    return;
  }
  let mode;
  try {
    mode = await getBrokerMode();
  } catch (_) {
    mode = 'simulated';
  }
  try {
    const res = await window.api.market.candlesticks(
      symbol,
      detailIv,
      seg.from_ts,
      seg.to_ts,
      1000,
      { timeout_ms: 120000, mode }
    );
    const raw = res?.data || [];
    const candles = raw
      .map((c) => {
        const time = btNormTs(c.time);
        if (time == null) return null;
        const o = parseFloat(c.open);
        const h = parseFloat(c.high);
        const low = parseFloat(c.low);
        const cl = parseFloat(c.close);
        if (![o, h, low, cl].every((x) => Number.isFinite(x))) return null;
        return { time, open: o, high: h, low, close: cl };
      })
      .filter(Boolean)
      .sort((x, y) => x.time - y.time);
    if (!candles.length) {
      destroyBtVerifyChart();
      wrap.innerHTML = '<p class="empty">本时段无 K 线数据</p>';
      if (st) st.textContent = '无数据';
      return;
    }
    const times = candles.map((x) => x.time);
    const evs = Array.isArray(row.trade_events) ? row.trade_events : [];
    const buyPts = [];
    const sellPts = [];
    for (const ev of evs) {
      const et = btNormTs(ev.time);
      if (et == null || et < seg.from_ts || et > seg.to_ts) continue;
      const mt = snapMarkerTime(times, et);
      if (mt == null) continue;
      const bar = candles.find((c) => c.time === mt);
      let pv = null;
      if (ev.kind === 'open' && bar) pv = bar.open;
      else if (ev.kind === 'close' && bar) pv = bar.close;
      if (pv == null || !Number.isFinite(pv)) {
        const rp = parseFloat(ev.price);
        if (Number.isFinite(rp)) pv = rp;
        else if (bar && Number.isFinite(bar.close)) pv = bar.close;
      }
      if (pv == null || !Number.isFinite(pv)) continue;
      if (ev.kind === 'open') buyPts.push({ time: mt, value: pv });
      else if (ev.kind === 'close') sellPts.push({ time: mt, value: pv });
    }
    const buyFinal = dedupeBtLinePts(buyPts);
    const sellFinal = dedupeBtLinePts(sellPts);
    if (typeof LightweightCharts === 'undefined') {
      if (st) st.textContent = '图表库未加载';
      return;
    }
    destroyBtVerifyChart();
    wrap.innerHTML = '';
    const w = Math.max(280, wrap.clientWidth || 600);
    const h = 340;
    _btVerifyChart = LightweightCharts.createChart(wrap, {
      layout: { background: { color: '#ffffff' }, textColor: '#1a1a2e', attributionLogo: false },
      grid: { vertLines: { color: '#f0f2f5' }, horzLines: { color: '#f0f2f5' } },
      width: w,
      height: h,
      rightPriceScale: { borderColor: '#e9ecef' },
      timeScale: { borderColor: '#e9ecef', timeVisible: true, secondsVisible: false },
    });
    _btVerifyCandleSeries = _btVerifyChart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderUpColor: '#26a69a',
      borderDownColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });
    _btVerifyCandleSeries.setData(candles);
    const candleMrk = [];
    for (const p of buyFinal) {
      candleMrk.push({
        time: p.time,
        position: 'belowBar',
        shape: 'arrowUp',
        color: '#1b5e20',
        text: 'Buy',
        size: 1,
      });
    }
    for (const p of sellFinal) {
      candleMrk.push({
        time: p.time,
        position: 'aboveBar',
        shape: 'arrowDown',
        color: '#7f1d1d',
        text: 'Sell',
        size: 1,
      });
    }
    candleMrk.sort((a, b) => a.time - b.time);
    if (candleMrk.length) _btVerifyCandleSeries.setMarkers(candleMrk);
    const dotLineBase = {
      lineVisible: false,
      lineWidth: 1,
      pointMarkersVisible: true,
      pointMarkersRadius: 4,
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    };
    if (buyFinal.length) {
      _btVerifyChart.addLineSeries({ ...dotLineBase, color: '#0d3b0d' }).setData(buyFinal);
    }
    if (sellFinal.length) {
      _btVerifyChart.addLineSeries({ ...dotLineBase, color: '#6b1010' }).setData(sellFinal);
    }
    _btVerifyChart.timeScale().fitContent();
    const nMarks = buyFinal.length + sellFinal.length;
    const trunc = row.trade_events_truncated ? '（Buy/Sell 已截断，详见后端 trade_events 上限）' : '';
    if (st) {
      st.textContent = `已加载 ${candles.length} 根 · 箭头/文字在 K 线下方(Buy)或上方(Sell)；深绿/深红圆点为对应价位（Buy=该根开盘价，Sell=该根收盘价）${trunc}`;
    }
  } catch (e) {
    destroyBtVerifyChart();
    wrap.innerHTML = '';
    if (st) st.textContent = e.message || String(e);
  }
}

function btvComputeWindowFromData(d) {
  const rows = getBtVerifyRows(d);
  let from = null;
  let to = null;
  for (const r of rows) {
    const sr = r?.series_range;
    if (!sr) continue;
    const a = btNormTs(sr.from_ts);
    const b = btNormTs(sr.to_ts);
    if (a != null) from = from == null ? a : Math.min(from, a);
    if (b != null) to = to == null ? b : Math.max(to, b);
  }
  if (from == null || to == null || to <= from) {
    const rng = d?.backtest_range || {};
    const a = btNormTs(rng.from_ts);
    const b = btNormTs(rng.to_ts);
    if (a != null && b != null && b > a) {
      from = a;
      to = b;
    }
  }
  if (from == null || to == null || to <= from) return null;
  return {
    fromTs: from,
    toTs: to,
    startYmd: btvYmdFromUtcSec(from),
    endYmd: btvYmdFromUtcSec(to),
  };
}

function syncBtvChips() {
  const cs = document.getElementById('bt-verify-chip-start');
  const ce = document.getElementById('bt-verify-chip-end');
  if (cs) cs.textContent = _btvYmdStart ? formatZhYmd(_btvYmdStart) : '选择日期';
  if (ce) ce.textContent = _btvYmdEnd ? formatZhYmd(_btvYmdEnd) : '选择日期';
}

function initBtVerifyAfterBacktest(d) {
  const sec = document.getElementById('bt-verify-section');
  const symSel = document.getElementById('bt-verify-symbol');
  if (!sec || !symSel) return;
  if (!d?.portfolio?.ok) {
    sec.style.display = 'none';
    destroyBtVerifyChart();
    const wrap = document.getElementById('bt-verify-chart-wrap');
    if (wrap) wrap.innerHTML = '';
    const st = document.getElementById('bt-verify-status');
    if (st) st.textContent = '';
    const sl = document.getElementById('bt-verify-seg-label');
    if (sl) sl.textContent = '';
    _btvWindow = null;
    _btvYmdStart = null;
    _btvYmdEnd = null;
    syncBtvChips();
    return;
  }
  const rows = getBtVerifyRows(d);
  if (!rows.length) {
    sec.style.display = 'none';
    destroyBtVerifyChart();
    _btvWindow = null;
    return;
  }
  sec.style.display = 'block';
  symSel.innerHTML = rows.map((r) => `<option value="${esc(r.symbol)}">${esc(r.symbol)}</option>`).join('');

  const win = btvComputeWindowFromData(d);
  _btvWindow = win;
  if (win) {
    const end = win.endYmd;
    let start = btvYmdAddDays(end, -(Math.min(BTV_MAX_SPAN_DAYS, 3) - 1));
    start = btvClampYmd(start, win);
    _btvYmdStart = start;
    _btvYmdEnd = end;
  } else {
    _btvYmdStart = null;
    _btvYmdEnd = null;
  }
  syncBtvChips();
  void refreshBtVerifyChart();
}

function renderSigTable(rows) {
  const tb = document.querySelector('#tbl-sig tbody');
  if (!tb) return;
  if (!rows || !rows.length) {
    tb.innerHTML = '<tr><td colspan="9">无数据（需至少 1 个有效标的）</td></tr>';
    return;
  }
  tb.innerHTML = rows
    .map(
      (r) => `
    <tr>
      <td>${esc(r.symbol)}</td>
      <td>${r.open_count != null ? r.open_count : '—'}</td>
      <td>${r.t_statistic != null ? r.t_statistic : '—'}</td>
      <td>${r.cumulative_return != null ? r.cumulative_return : '—'}</td>
      <td>${r.correlation_with_portfolio != null ? r.correlation_with_portfolio : '—'}</td>
      <td>${r.pnl_share_vs_portfolio_abs != null ? r.pnl_share_vs_portfolio_abs : '—'}</td>
      <td>${esc(r.luck_risk || '')}</td>
      <td class="${r.suggest_remove_from_portfolio ? 'cell-warn' : 'cell-ok'}">${r.suggest_remove_from_portfolio ? '是' : '否'}</td>
      <td>${esc(r.verdict || '')}</td>
    </tr>`
    )
    .join('');
}

function renderFactorTable(rows) {
  const tb = document.querySelector('#tbl-factors tbody');
  if (!tb) return;
  if (!rows || !rows.length) {
    tb.innerHTML = '<tr><td colspan="7">无因子数据（请确认已勾选因子并完成回测）</td></tr>';
    return;
  }
  tb.innerHTML = rows
    .map(
      (r) => `
    <tr>
      <td>${esc(r.factor)}</td>
      <td>${r.avg_icir != null ? r.avg_icir : '—'}</td>
      <td>${r.avg_ic_mean != null ? r.avg_ic_mean : '—'}</td>
      <td>${r.avg_weight != null ? r.avg_weight : '—'}</td>
      <td><strong>${r.impact_score != null ? r.impact_score : '—'}</strong></td>
      <td class="${r.suggest_remove_factor ? 'cell-warn' : 'cell-ok'}">${r.suggest_remove_factor ? '可考虑移除' : '保留'}</td>
      <td>${esc(r.note || '')}</td>
    </tr>`
    )
    .join('');
}

function renderBacktestReport(d, opts) {
  const met = document.getElementById('bt-metrics');
  const factorIdsFallback = Array.isArray(opts?.factorIdsFallback) ? opts.factorIdsFallback : [];
  const p = (d && d.portfolio) || {};
  const rng = (d && d.backtest_range) || {};
  let rangeLine = '';
  if (rng.mode === 'date_range' && rng.start_date && rng.end_date) {
    const clipNote = rng.lookback_clipped && rng.requested_start_date && rng.requested_start_date !== rng.start_date
      ? ` <span style="color:#b26a00;">（所选开始日 ${esc(rng.requested_start_date)} 早于 Gate 允许的最近 ${rng.max_lookback_bars || 10000} 根上限，已自动从 ${esc(rng.start_date)} 起算）</span>`
      : '';
    rangeLine = `<span>回测区间: <strong>${esc(rng.start_date)}</strong> ～ <strong>${esc(rng.end_date)}</strong>（UTC 日界）${clipNote}</span>`;
  } else if (rng.mode === 'recent') {
    rangeLine = `<span>回测区间: <strong>最近约 ${rng.bars_limit || 2000} 根 K 线</strong></span>`;
  }
  if (met) {
    met.style.display = 'flex';
    const facLine = (d?.active_factors_used || []).length
      ? d.active_factors_used.join(', ')
      : factorIdsFallback.join(', ');
    if (p.ok) {
      met.innerHTML = `
        ${rangeLine}
        <span>组合标的: <strong>${esc((p.symbols_in_portfolio || []).join(', ') || '—')}</strong></span>
        <span>参与因子: <strong>${esc(facLine)}</strong></span>
        <span>样本根数: <strong>${p.bars != null ? p.bars : '—'}</strong></span>
        <span>组合总收益: <strong>${p.total_return != null ? p.total_return : '—'}</strong></span>
        <span>基准收益: <strong>${p.benchmark_total_return != null ? p.benchmark_total_return : '—'}</strong></span>
        <span>Alpha(对买入持有): <strong>${p.alpha_vs_buyhold != null ? p.alpha_vs_buyhold : '—'}</strong></span>
        <span>夏普(近似): <strong>${p.sharpe_approx != null ? p.sharpe_approx : '—'}</strong></span>
        <span>最大回撤: <strong>${p.max_drawdown != null ? p.max_drawdown : '—'}</strong></span>
        <span>开仓次数: <strong>${p.open_count_total != null ? p.open_count_total : '—'}</strong> 次合计 · 标的平均 <strong>${p.open_count_mean != null ? p.open_count_mean : '—'}</strong></span>
        <span>平均每日开仓(${p.avg_daily_mode === 'natural' ? '自然日' : '交易日'}): <strong>${p.avg_daily_open_count != null ? p.avg_daily_open_count : '—'}</strong> 次/日</span>
        <span>每天最多开仓设置: <strong>${p.max_opens_per_day != null ? p.max_opens_per_day : 0}</strong>（0=不限制）</span>`;
    } else {
      met.innerHTML = `${rangeLine}<span>${esc(p.reason || '组合回测未完成')}</span>`;
    }
  }
  const capEl = document.getElementById('bt-chart-caption');
  if (capEl && !p.ok) {
    capEl.hidden = true;
    capEl.textContent = '';
  }
  if (p.ok) drawEquityChart(p);
  else destroyBacktestChart();
  initBtVerifyAfterBacktest(p.ok ? d : null);

  renderSigTable(d?.insignificant_symbols_analysis || []);
  renderFactorTable(d?.factor_impact_scores || []);

  const br = d?.brinson_attribution;
  const fr = d?.formal_risk_model;
  const secBr = document.getElementById('bt-brinson-section');
  const secFr = document.getElementById('bt-formal-risk-section');
  if (br?.ok && secBr) {
    secBr.style.display = 'block';
    const bbp = document.getElementById('bt-brinson-bench');
    if (bbp) bbp.textContent = br.benchmark_description || '';
    const tr = document.querySelector('#tbl-bt-brinson tbody tr');
    const c = br.cumulative || {};
    if (tr) {
      tr.innerHTML = `<td>${c.allocation_effect ?? '—'}</td><td>${c.selection_effect ?? '—'}</td><td>${c.interaction_effect ?? '—'}</td><td>${c.active_return ?? '—'}</td>`;
    }
  } else if (secBr) secBr.style.display = 'none';
  if (fr?.ok && secFr) {
    secFr.style.display = 'block';
    const tr2 = document.querySelector('#tbl-bt-risk tbody tr');
    const top = (fr.top_risk_contributors || []).map((x) => `${esc(x.asset)} ${x.contrib_pct}`).join('；') || '—';
    if (tr2) {
      tr2.innerHTML = `<td>${fr.portfolio_vol_1bar ?? '—'}</td><td>${fr.tracking_error_1bar ?? '—'}</td><td>${fr.var_95_normal_1bar ?? '—'}</td><td>${top}</td>`;
    }
  } else if (secFr) secFr.style.display = 'none';
  const disc = document.getElementById('bt-disclaimer');
  if (disc) disc.textContent = d?.disclaimer || '';
}

async function saveBacktestRunToServer(d, payload) {
  if (!window.api?.backtestRuns?.save || !d) return null;
  try {
    const body = {
      user_strategy_id:
        _btCurrentUserStrategyId && Number(_btCurrentUserStrategyId) > 0
          ? Number(_btCurrentUserStrategyId)
          : null,
      name: payload?.name || '',
      interval: payload?.interval || '',
      symbols: payload?.symbols || [],
      factors: payload?.factors || [],
      range: d.backtest_range || {},
      summary: compactBacktestSummary(d),
      result: d,
    };
    const res = await window.api.backtestRuns.save(body);
    return res?.data?.id || null;
  } catch (_) {
    return null;
  }
}

let _btActiveRunId = null;
let _btMirrorRunId = null;

// 暴露到全局：在 DevTools Console 里直接调用这些就能定位到底是哪一步卡住
const MIRROR_VERSION = 'mirror-v3-flip-2026-04-23';
const mirrorProbe = async () => {
  const out = { version: MIRROR_VERSION, hasApi: !!window.api?.simulatedMirror };
  if (!out.hasApi) {
    console.warn('[mirror probe] window.api.simulatedMirror NOT AVAILABLE — 渲染器还在跑旧版本 api.js，请 Ctrl+Shift+R 强刷或重启 Electron');
  } else {
    try { out.status = (await window.api.simulatedMirror.status()).data; } catch (e) { out.statusErr = String(e); }
    try { out.enable = await window.api.simulatedMirror.enable(11, 5921.363, 'spot'); } catch (e) { out.enableErr = String(e); }
    try { out.summary = (await window.api.portfolio.summary('simulated', 'spot')).data; } catch (e) { out.sumErr = String(e); }
  }
  console.log('[mirror probe]', out);
  return out;
};
const mirrorVersion = () => MIRROR_VERSION;

// 同时挂到本 frame 和顶层 window（这样无论 DevTools 在哪个 context 都能直接调用）
try {
  const assignToWindow = (w) => {
    if (!w) return;
    try {
      w.mirrorProbe = mirrorProbe;
      w.mirrorVersion = mirrorVersion;
      w.__mirrorProbe = mirrorProbe;
      w.__mirrorVersion = mirrorVersion;
    } catch (_) {}
  };
  assignToWindow(window);
  assignToWindow(window.top);
  assignToWindow(window.parent);
  console.log('[mirror] script loaded', MIRROR_VERSION, '— 在 Console 里可直接用 mirrorProbe() / mirrorVersion()');
} catch (_) {}

function notifyAccountPageMirrorChanged() {
  const payload = { type: 'simulated-mirror-changed', ts: Date.now() };
  // 主通道：BroadcastChannel（同源跨 frame 最可靠，Electron Chromium 原生支持）
  try {
    const bc = new BroadcastChannel('simulated-mirror');
    bc.postMessage(payload);
    try { bc.close(); } catch (_) {}
  } catch (_) {}
  // 二路：localStorage 变更事件（同源下会在其他 frame 触发 storage 事件）
  try {
    localStorage.setItem('simulated-mirror-bump', String(payload.ts));
  } catch (_) {}
  // 三路兜底：postMessage 广播到父窗口及其全部子 frame
  try {
    window.postMessage(payload, '*');
    if (window.parent && window.parent !== window) window.parent.postMessage(payload, '*');
    try {
      const topFrames = (window.parent || window).frames || window.frames;
      for (let i = 0; i < topFrames.length; i++) {
        try { topFrames[i].postMessage(payload, '*'); } catch (_) {}
      }
    } catch (_) {}
    // 直接拿到 account iframe 的 contentWindow 再发一次（最稳）
    try {
      const iframe = (window.parent || window).document.getElementById('page-account');
      if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage(payload, '*');
    } catch (_) {}
  } catch (_) {}
}

function btFormatRunRange(rng) {
  if (!rng) return '—';
  if (rng.mode === 'date_range' && rng.start_date && rng.end_date) {
    return `${rng.start_date} ～ ${rng.end_date}`;
  }
  if (rng.mode === 'recent') return `最近 ${rng.bars_limit || 2000} 根`;
  return '—';
}

function btFormatRunTime(ts) {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleString();
  } catch (_) {
    return String(ts);
  }
}

function renderBacktestRunsList(list) {
  const wrap = document.getElementById('bt-runs-list');
  if (!wrap) return;
  const items = Array.isArray(list) ? list : [];
  if (!items.length) {
    wrap.innerHTML = '<p class="bt-runs-empty">暂无历史回测；运行一次回测后会自动保存在这里。</p>';
    return;
  }
  wrap.innerHTML = items
    .map((r) => {
      const s = r.summary || {};
      const sym = (r.symbols || []).join(', ') || '—';
      const fac = (r.factors || []).join(', ') || '—';
      const tot = s.total_return != null ? s.total_return : '—';
      const bench = s.benchmark_total_return != null ? s.benchmark_total_return : '—';
      const alpha = s.alpha_vs_buyhold != null ? s.alpha_vs_buyhold : '—';
      const sp = s.sharpe_approx != null ? s.sharpe_approx : '—';
      const dd = s.max_drawdown != null ? s.max_drawdown : '—';
      const oc = s.open_count_total != null ? s.open_count_total : '—';
      const ok = s.portfolio_ok !== false;
      const rangeText = btFormatRunRange(r.range);
      const timeText = btFormatRunTime(r.created_at);
      const strategyName = r.user_strategy_name
        ? `${r.user_strategy_name}`
        : '（未关联保存策略）';
      const active = _btActiveRunId === r.id ? ' is-active' : '';
      return `
        <div class="bt-run-item${active}" data-run-id="${r.id}">
          <div class="bt-run-main">
            <div class="bt-run-title">${esc(strategyName)} · ${esc(r.interval || '')} · ${esc(sym)}</div>
            <div class="bt-run-meta">${esc(timeText)} · 区间 ${esc(rangeText)} · 因子 ${esc(fac)}${ok ? '' : ' · <span style="color:#c62828;">组合回测未完成</span>'}</div>
            <div class="bt-run-metrics">
              <span>总收益 <strong>${esc(String(tot))}</strong></span>
              <span>基准 <strong>${esc(String(bench))}</strong></span>
              <span>Alpha <strong>${esc(String(alpha))}</strong></span>
              <span>夏普 <strong>${esc(String(sp))}</strong></span>
              <span>最大回撤 <strong>${esc(String(dd))}</strong></span>
              <span>开仓 <strong>${esc(String(oc))}</strong></span>
            </div>
          </div>
          <div class="bt-run-actions">
            <button type="button" data-run-load="${r.id}">载入</button>
            ${_btMirrorRunId === r.id
              ? `<button type="button" class="btn-mirror-active" data-run-unmirror="${r.id}" title="关闭镜像，账户概览恢复展示真实数据">取消</button>`
              : `<button type="button" data-run-mirror="${r.id}" title="把该回测作为模拟账户的投资组合/交易记录在「账户概览」中展示">镜像</button>`}
            <button type="button" class="btn-danger" data-run-del="${r.id}">删除</button>
          </div>
        </div>`;
    })
    .join('');
  wrap.querySelectorAll('[data-run-load]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const id = parseInt(btn.getAttribute('data-run-load') || '0', 10);
      if (id > 0) void loadBacktestRunById(id);
    });
  });
  wrap.querySelectorAll('[data-run-mirror]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const id = parseInt(btn.getAttribute('data-run-mirror') || '0', 10);
      if (id > 0) void mirrorBacktestRunToAccount(id);
    });
  });
  wrap.querySelectorAll('[data-run-unmirror]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const id = parseInt(btn.getAttribute('data-run-unmirror') || '0', 10);
      if (id > 0) void unmirrorBacktestRun(id);
    });
  });
  wrap.querySelectorAll('[data-run-del]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const id = parseInt(btn.getAttribute('data-run-del') || '0', 10);
      if (id > 0) void deleteBacktestRunById(id);
    });
  });
}

// 不依赖整表重渲染：就地把某一行的镜像按钮在「镜像到账户」与「关闭镜像」之间切换
function flipRunMirrorButton(runId, toState /* 'on' | 'off' */) {
  const wrap = document.getElementById('bt-runs-list');
  if (!wrap || !runId) return;
  const ridStr = String(Number(runId));
  const sel = toState === 'on'
    ? `[data-run-mirror="${ridStr}"]`
    : `[data-run-unmirror="${ridStr}"]`;
  const oldBtn = wrap.querySelector(sel);
  if (!oldBtn) return;
  const next = document.createElement('button');
  next.type = 'button';
  if (toState === 'on') {
    // 当前是 镜像到账户 → 翻成 关闭镜像
    next.className = 'btn-mirror-active';
    next.setAttribute('data-run-unmirror', ridStr);
    next.title = '关闭镜像，账户概览恢复展示真实数据';
    next.textContent = '取消';
    next.addEventListener('click', (e) => {
      e.preventDefault();
      void unmirrorBacktestRun(Number(ridStr));
    });
  } else {
    // 当前是 关闭镜像 → 翻成 镜像到账户
    next.setAttribute('data-run-mirror', ridStr);
    next.title = '把该回测作为模拟账户的投资组合/交易记录在「账户概览」中展示';
    next.textContent = '镜像';
    next.addEventListener('click', (e) => {
      e.preventDefault();
      void mirrorBacktestRunToAccount(Number(ridStr));
    });
  }
  oldBtn.replaceWith(next);
}

/** Electron renderer 默认禁用 window.prompt()，这里用原生 DOM 自制一个净值输入弹窗。 */
function promptMirrorNav(defaultNav) {
  return new Promise((resolve) => {
    const mask = document.createElement('div');
    mask.style.cssText =
      'position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.45);display:flex;align-items:center;justify-content:center;';
    const box = document.createElement('div');
    box.style.cssText =
      'background:#fff;min-width:360px;max-width:480px;border-radius:8px;box-shadow:0 10px 40px rgba(0,0,0,0.25);padding:20px 22px;font-size:14px;color:#222;';
    box.innerHTML = `
      <div style="font-size:15px;font-weight:600;margin-bottom:8px;">把该回测作为账户展示源</div>
      <div style="color:#555;line-height:1.5;margin-bottom:12px;">
        请输入「当前净值（USDT）」作为账户概览中的固定数值。<br/>
        投资组合中的初始资金会按该净值和回测累计收益反推。
      </div>
      <input type="text" id="__mirror_nav_input" value="${defaultNav}" style="width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #ccc;border-radius:4px;font-size:14px;" />
      <div id="__mirror_nav_err" style="color:#c62828;font-size:12px;margin-top:6px;min-height:16px;"></div>
      <div style="text-align:right;margin-top:12px;">
        <button type="button" id="__mirror_nav_cancel" style="padding:6px 14px;margin-right:8px;background:#f5f5f5;border:1px solid #ddd;border-radius:4px;cursor:pointer;">取消</button>
        <button type="button" id="__mirror_nav_ok" style="padding:6px 16px;background:#1976d2;color:#fff;border:none;border-radius:4px;cursor:pointer;">确定</button>
      </div>
    `;
    mask.appendChild(box);
    document.body.appendChild(mask);
    const input = box.querySelector('#__mirror_nav_input');
    const errEl = box.querySelector('#__mirror_nav_err');
    const cleanup = () => { try { mask.remove(); } catch (_) {} };
    const submit = () => {
      const raw = String(input.value || '').trim().replace(/,/g, '');
      const n = Number(raw);
      if (!Number.isFinite(n) || n <= 0) {
        errEl.textContent = '请输入大于 0 的数字';
        input.focus();
        return;
      }
      cleanup();
      resolve(n);
    };
    box.querySelector('#__mirror_nav_cancel').addEventListener('click', () => { cleanup(); resolve(null); });
    box.querySelector('#__mirror_nav_ok').addEventListener('click', submit);
    mask.addEventListener('click', (e) => { if (e.target === mask) { cleanup(); resolve(null); } });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
      else if (e.key === 'Escape') { e.preventDefault(); cleanup(); resolve(null); }
    });
    setTimeout(() => { try { input.focus(); input.select(); } catch (_) {} }, 0);
  });
}

async function mirrorBacktestRunToAccount(id) {
  if (!window.api?.simulatedMirror?.enable) {
    alert(
      '当前渲染器加载的是旧版前端脚本，未注册 simulatedMirror API。\n\n' +
        '请完全关闭软件（Electron 窗口），再重新打开一次即可——或在开发者工具里 Ctrl+Shift+R 强制刷新。',
    );
    console.error('[mirror] window.api.simulatedMirror missing. api keys:', Object.keys(window.api || {}));
    return;
  }
  const nav = await promptMirrorNav('5921.3630');
  if (nav == null) return;
  console.log('[mirror] enabling backtest run', id, 'nav=', nav);
  try {
    const res = await window.api.simulatedMirror.enable(id, nav, 'spot');
    console.log('[mirror] /enable response:', res);
    if (!res?.success) throw new Error(res?.message || '设置失败');
    const s = res.data?.summary || {};
    _btMirrorRunId = Number(id);
    // 先就地翻面，避免等待列表刷新失败导致按钮卡住
    flipRunMirrorButton(id, 'on');
    notifyAccountPageMirrorChanged();
    // 整表刷新作为二次同步（失败不影响按钮状态）
    try { await loadBacktestRunsList(); } catch (err) { console.warn('[mirror] reload runs list failed', err); }
    alert(
      '已把该回测镜像到账户概览\n\n' +
        `当前净值：${s.current_nav ?? nav} USDT\n` +
        `初始资金：${s.initial_capital ?? '—'} USDT\n` +
        `累计收益：${s.total_return ?? '—'}\n` +
        `年化收益：${s.annual_return ?? '—'}\n` +
        '切到「账户概览」即可看到更新后的投资组合、净值曲线与交易流水。',
    );
  } catch (e) {
    console.error('[mirror] enable failed', e);
    alert('镜像失败：' + (e.message || String(e)));
  }
}

async function unmirrorBacktestRun(id) {
  if (!window.api?.simulatedMirror?.disable) return;
  if (!confirm('关闭镜像后，账户概览将恢复展示真实绑定账户数据。确认关闭？')) return;
  console.log('[mirror] disabling for run', id);
  try {
    const res = await window.api.simulatedMirror.disable();
    console.log('[mirror] /disable response:', res);
    if (!res?.success) throw new Error(res?.message || '关闭失败');
    _btMirrorRunId = null;
    // 先就地翻面，确保「镜像到账户」按钮立刻可点击，不依赖列表重渲染
    flipRunMirrorButton(id, 'off');
    notifyAccountPageMirrorChanged();
    try { await loadBacktestRunsList(); } catch (err) { console.warn('[mirror] reload runs list failed', err); }
  } catch (e) {
    console.error('[mirror] disable failed', e);
    alert('关闭镜像失败：' + (e.message || String(e)));
  }
}

async function refreshMirrorActiveId() {
  if (!window.api?.simulatedMirror?.status) {
    _btMirrorRunId = null;
    return;
  }
  try {
    const res = await window.api.simulatedMirror.status();
    const d = res?.data || {};
    _btMirrorRunId = d.enabled && d.backtest_run_id ? Number(d.backtest_run_id) : null;
  } catch (_) {
    _btMirrorRunId = null;
  }
}

async function loadBacktestRunsList() {
  const wrap = document.getElementById('bt-runs-list');
  if (!wrap || !window.api?.backtestRuns?.list) return;
  const onlyCurrent = !!document.getElementById('bt-runs-only-current')?.checked;
  const filterSid = onlyCurrent && _btCurrentUserStrategyId ? Number(_btCurrentUserStrategyId) : null;
  try {
    await refreshMirrorActiveId();
    const res = await window.api.backtestRuns.list(60, filterSid);
    if (!res?.success) throw new Error(res?.message || '加载失败');
    renderBacktestRunsList(res.data?.list || []);
  } catch (e) {
    wrap.innerHTML = `<p class="bt-runs-empty">${esc(e.message || '加载回测历史失败')}</p>`;
  }
}

async function loadBacktestRunById(id) {
  if (!window.api?.backtestRuns?.get) return;
  try {
    const res = await window.api.backtestRuns.get(id);
    if (!res?.success || !res.data) throw new Error(res?.message || '载入失败');
    const r = res.data;
    const d = r.result || null;
    if (!d) throw new Error('该记录缺少回测结果数据');
    // 恢复编辑器表单到记录时的设置
    try {
      const sEl = document.getElementById('bt-symbols');
      if (sEl) sEl.value = Array.isArray(r.symbols) ? r.symbols.join(',') : '';
      const ivEl = document.getElementById('bt-interval');
      if (ivEl && r.interval) ivEl.value = r.interval;
      const rng = r.range || {};
      if (rng.mode === 'date_range' && rng.start_date && rng.end_date) {
        _btRangeStart = rng.start_date;
        _btRangeEnd = rng.end_date;
      } else {
        _btRangeStart = null;
        _btRangeEnd = null;
      }
      saveBacktestRangeToLS();
      syncRangeChips();
      if (Array.isArray(r.factors) && r.factors.length) {
        applyFactorSelection(r.factors);
      }
      const p = d.portfolio || {};
      const moEl = document.getElementById('bt-max-opens-day');
      if (moEl && p.max_opens_per_day != null) moEl.value = String(p.max_opens_per_day);
      const admEl = document.getElementById('bt-avg-daily-mode');
      if (admEl && p.avg_daily_mode) admEl.value = p.avg_daily_mode === 'natural' ? 'natural' : 'trading';
    } catch (_) {}
    window._lastBacktestData = d;
    clearStaleBanner();
    renderBacktestReport(d, { factorIdsFallback: r.factors || [] });
    const st = document.getElementById('bt-status');
    if (st) {
      st.textContent = `已载入历史回测 · ${btFormatRunTime(r.created_at)} · 记录 #${r.id}`;
    }
    _btActiveRunId = r.id;
    void loadBacktestRunsList();
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function deleteBacktestRunById(id) {
  if (!window.api?.backtestRuns?.delete) return;
  if (!confirm('确定删除该历史回测记录？删除后不可恢复。')) return;
  try {
    await window.api.backtestRuns.delete(id);
    if (_btActiveRunId === id) _btActiveRunId = null;
    await loadBacktestRunsList();
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function runBacktest() {
  const btn = document.getElementById('btn-run-backtest');
  const errEl = document.getElementById('bt-err');
  const st = document.getElementById('bt-status');
  const met = document.getElementById('bt-metrics');
  if (!window.api?.strategyEngine?.backtestVisual) {
    alert('API 未就绪');
    return;
  }
  const symbols = (document.getElementById('bt-symbols')?.value || '').trim();
  const interval = document.getElementById('bt-interval')?.value || '1h';
  const maxOpensRaw = parseInt(document.getElementById('bt-max-opens-day')?.value || '0', 10);
  const maxOpensPerDay = Number.isFinite(maxOpensRaw) && maxOpensRaw > 0 ? maxOpensRaw : 0;
  const avgDailyMode = document.getElementById('bt-avg-daily-mode')?.value === 'natural' ? 'natural' : 'trading';
  const factorIds = collectActiveFactorIds();
  if (!factorIds.length) {
    alert('请至少勾选一个因子');
    return;
  }
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = '';
  }
  if (btn) btn.disabled = true;
  if (st) st.textContent = '正在拉取 K 线并回测…';
  const PERF_KEY = 'dashboard_perf_boost_until';
  const boostUntil = Date.now() + 35 * 60 * 1000;
  try {
    try {
      localStorage.setItem(PERF_KEY, String(boostUntil));
    } catch (_) {}
    const mode = await getBrokerMode();
    try {
      localStorage.setItem(LS_BT_MAX_OPENS_DAY, String(maxOpensPerDay || 0));
      localStorage.setItem(LS_BT_AVG_DAILY_MODE, avgDailyMode);
    } catch (_) {}
    const res = await window.api.strategyEngine.backtestVisual(
      symbols,
      interval,
      mode,
      factorIds,
      getBacktestRangeForApi(),
      maxOpensPerDay,
      avgDailyMode
    );
    if (!res.success || !res.data) throw new Error(res.message || '回测失败');
    const d = res.data;
    window._lastBacktestData = d;
    clearStaleBanner();
    renderBacktestReport(d, { factorIdsFallback: factorIds });
    if (st) {
      st.textContent = `完成 · ${d.generated_at ? new Date(d.generated_at).toLocaleString() : ''} · 请求标的: ${(d.symbols_requested || []).join(', ')}`;
    }
    _btActiveRunId = null;
    try {
      const savedId = await saveBacktestRunToServer(d, {
        interval,
        symbols: symbols ? symbols.split(',').map((x) => x.trim()).filter(Boolean) : (d?.symbols_requested || []),
        factors: factorIds,
      });
      if (savedId) _btActiveRunId = savedId;
    } catch (_) {}
    void loadBacktestRunsList();
  } catch (e) {
    window._lastBacktestData = null;
    clearStaleBanner();
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = e.message || String(e);
    }
    destroyBacktestChart();
    const capErr = document.getElementById('bt-chart-caption');
    if (capErr) {
      capErr.hidden = true;
      capErr.textContent = '';
    }
    if (met) met.style.display = 'none';
    if (st) st.textContent = '失败';
    initBtVerifyAfterBacktest(null);
  } finally {
    try {
      localStorage.removeItem(PERF_KEY);
    } catch (_) {}
    if (btn) btn.disabled = false;
  }
}

document.getElementById('btn-run-backtest')?.addEventListener('click', () => {
  void runBacktest();
});

document.getElementById('bt-interval')?.addEventListener('change', () => {
  try {
    const ivEl = document.getElementById('bt-interval');
    if (ivEl && ivEl.value) localStorage.setItem(LS_BT_INTERVAL, String(ivEl.value));
  } catch (_) {}
  markBacktestReportStale();
});

document.getElementById('bt-ds-run')?.addEventListener('click', async () => {
  const mode = document.getElementById('bt-ds-mode')?.value || 'screen';
  const btn = document.getElementById('bt-ds-run');
  if (!window.api?.strategyEngine?.deepseekFactorScreen) {
    alert('API 未就绪');
    return;
  }
  if (mode === 'optimize' && !window._lastBacktestData?.portfolio?.ok) {
    alert('请先完成一次成功的组合回测，再使用「优化因子集」。');
    return;
  }
  if (btn) btn.disabled = true;
  try {
    await runDeepseekFactor(mode, '');
  } catch (e) {
    const out = document.getElementById('bt-ds-out');
    if (out) {
      out.hidden = false;
      out.textContent = e.message || String(e);
    }
  } finally {
    if (btn) btn.disabled = false;
  }
});

document.getElementById('bt-ds-quick-gen')?.addEventListener('click', () => {
  const sel = document.getElementById('bt-ds-mode');
  if (sel) sel.value = 'generate';
  document.getElementById('bt-ds-run')?.click();
});

document.getElementById('bt-report-run')?.addEventListener('click', async () => {
  const btn = document.getElementById('bt-report-run');
  const out = document.getElementById('bt-report-out');
  const d = window._lastBacktestData;
  if (!d) {
    alert('请先点击「运行回测」并等待完成');
    return;
  }
  if (!window.api?.strategyEngine?.deepseekBacktestReport) {
    alert('API 未就绪');
    return;
  }
  const summary = compactBacktestSummary(d);
  if (!summary || Object.keys(summary).length === 0) {
    alert('无法构建回测摘要');
    return;
  }
  const interval = document.getElementById('bt-interval')?.value || '1h';
  const ctx = {
    symbols_requested: d.symbols_requested,
    interval,
    backtest_range: d.backtest_range,
    disclaimer: d.disclaimer,
    generated_at: d.generated_at,
  };
  const userPrompt = (document.getElementById('bt-report-prompt')?.value || '').trim();
  if (btn) btn.disabled = true;
  if (out) {
    out.hidden = false;
    out.textContent = '正在请求 DeepSeek 生成报告…';
  }
  try {
    const res = await window.api.strategyEngine.deepseekBacktestReport({
      user_prompt: userPrompt,
      backtest_summary: summary,
      context: ctx,
    });
    if (!res.success || !res.data?.report) throw new Error(res.message || '生成失败');
    if (out) out.textContent = res.data.report;
  } catch (e) {
    if (out) {
      out.hidden = false;
      out.textContent = e.message || String(e);
    }
  } finally {
    if (btn) btn.disabled = false;
  }
});

window.addEventListener('resize', () => {
  const wrap = document.getElementById('backtest-chart-wrap');
  if (_btChart && wrap) {
    _btChart.applyOptions({ width: Math.max(280, wrap.clientWidth || 600) });
  }
  const vw = document.getElementById('bt-verify-chart-wrap');
  if (_btVerifyChart && vw) {
    _btVerifyChart.applyOptions({ width: Math.max(280, vw.clientWidth || 600) });
  }
});

let _btCurrentUserStrategyId = null;
/** 从内置模板加载、尚未保存为用户策略时为 true */
let _btBuiltinEditorMode = false;

function buildWeightsFromLastBacktest() {
  const d = window._lastBacktestData;
  if (!d?.factor_impact_scores?.length) return {};
  const w = {};
  for (const r of d.factor_impact_scores) {
    if (r.factor != null && r.avg_weight != null) w[String(r.factor)] = Number(r.avg_weight);
  }
  const sum = Object.values(w).reduce((a, b) => a + Math.max(0, b), 0);
  if (sum <= 0) return {};
  const out = {};
  for (const k of Object.keys(w)) out[k] = Math.max(0, w[k]) / sum;
  return out;
}

function collectStrategyConfigObject() {
  const symbols = (document.getElementById('bt-symbols')?.value || '').trim();
  const interval = document.getElementById('bt-interval')?.value || '1h';
  const maxOpensRaw = parseInt(document.getElementById('bt-max-opens-day')?.value || '0', 10);
  const max_opens_per_day = Number.isFinite(maxOpensRaw) && maxOpensRaw > 0 ? maxOpensRaw : 0;
  const avg_daily_mode = document.getElementById('bt-avg-daily-mode')?.value === 'natural' ? 'natural' : 'trading';
  return {
    symbols,
    interval,
    max_opens_per_day,
    avg_daily_mode,
    active_factors: collectActiveFactorIds(),
  };
}

function btHasActiveUserStrategySubscription(usid, mode, subs) {
  const m = String(mode || 'simulated');
  return (subs || []).some(
    (s) =>
      s.status === 'active' &&
      Number(s.user_strategy_id) === Number(usid) &&
      String(s.mode) === m
  );
}

function btHasActiveBuiltinSubscription(strategyId, mode, subs) {
  const m = String(mode || 'simulated');
  return (subs || []).some(
    (s) =>
      s.status === 'active' &&
      (s.user_strategy_id == null || Number(s.user_strategy_id) <= 0) &&
      Number(s.strategy_id) === Number(strategyId) &&
      String(s.mode) === m
  );
}

function buildBtSingleBuiltinCardHtml(mode, activeSubs) {
  const builtinSubs = activeSubs.filter((s) => {
    const hasUs = s.user_strategy_id != null && Number(s.user_strategy_id) > 0;
    const sid = s.strategy_id != null ? Number(s.strategy_id) : 0;
    return !hasUs && sid > 0;
  });
  const metaLines = builtinSubs
    .map((sub) => `<p class="strategy-subscription-meta">${esc(btSubscriptionLabel(sub, []))}</p>`)
    .join('');
  const capHint =
    '稳健增长约 30% / 10% 单笔；积极进取约 55% / 18% 单笔（以策略中心风控为准）';
  const actions = [1, 2]
    .map((tid) => {
      const subbed = btHasActiveBuiltinSubscription(tid, mode, activeSubs);
      const nm = BT_BUILTIN_NAMES[tid];
      return subbed
        ? `<span class="btn-subscribe-pill is-subscribed">${esc(nm)} 已订阅</span>`
        : `<button type="button" class="btn-subscribe btn-subscribe-builtin" data-builtin-strategy-id="${tid}">订阅${esc(nm)}</button>`;
    })
    .join('');
  return `
      <div class="strategy-item strategy-item--builtin bt-builtin-card" role="button" tabindex="0">
        <div class="strategy-item-title-row">
          <h3>内置策略模板</h3>
          <span class="strategy-builtin-badge">内置</span>
        </div>
        <p>默认因子 <strong>rev_1</strong>、<strong>vol_20</strong>、<strong>vol_z</strong>（与注册时默认策略一致）。点击卡片加载到下方编辑器，可改名、回测后保存为自定义策略。</p>
        ${metaLines}
        <p class="strategy-caps-hint">${esc(capHint)}</p>
        <div class="strategy-builtin-actions">${actions}</div>
        <p class="bt-strategy-card-hint">点击卡片加载模板（按钮为订阅）</p>
      </div>`;
}

async function loadBuiltinTemplateForEditor() {
  _btCurrentUserStrategyId = null;
  _btBuiltinEditorMode = true;
  const nameEl = document.getElementById('bt-strategy-name');
  if (nameEl) nameEl.value = '内置策略（默认）';
  resetBacktestEditorToDefaults(BT_BUILTIN_DEFAULT_FACTORS);
  const msg = document.getElementById('bt-strategy-msg');
  if (msg) msg.textContent = '已加载内置模板（rev_1 / vol_20 / vol_z），可改名、修改参数并回测，保存后成为自定义策略';
  await loadUserStrategyList();
}

async function btSubscribeUser(usid) {
  const mode = await getBrokerMode();
  if (!window.api?.strategies?.subscribe) return;
  try {
    await window.api.strategies.subscribe({ user_strategy_id: usid, mode, params: {} });
    alert('订阅成功');
    await loadUserStrategyList();
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function btDeleteUserStrategy(id) {
  if (!window.api?.userStrategies?.delete) return;
  if (!confirm('确定删除该策略？删除后不可恢复。')) return;
  try {
    await window.api.userStrategies.delete(id);
    if (_btCurrentUserStrategyId === id) {
      _btCurrentUserStrategyId = null;
      _btBuiltinEditorMode = false;
      const nameEl = document.getElementById('bt-strategy-name');
      if (nameEl) nameEl.value = '';
      resetBacktestEditorToDefaults();
    }
    await loadUserStrategyList();
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function loadUserStrategyList() {
  const el = document.getElementById('bt-strategy-list');
  if (!el || !window.api?.userStrategies?.list) {
    if (el) el.innerHTML = '<p class="backtest-hint">登录后加载策略列表。</p>';
    return;
  }
  try {
    const mode = await getBrokerMode();
    const [ur, subRes] = await Promise.all([
      window.api.userStrategies.list(),
      window.api.strategies.subscriptions().catch(() => ({ data: { list: [] } })),
    ]);
    const list = ur.data?.list || [];
    const subs = subRes?.data?.list || [];
    const activeSubs = subs.filter((s) => s.status === 'active');
    const builtinCard = buildBtSingleBuiltinCardHtml(mode, activeSubs);
    const hint = !list.length
      ? '<p class="backtest-hint">暂无自定义策略，可从下方「内置策略模板」或「创建策略」开始。</p>'
      : '';
    const userCards = list
      .map((r) => {
        const lines = activeSubs
          .filter(
            (sub) =>
              sub.user_strategy_id != null &&
              Number(sub.user_strategy_id) > 0 &&
              Number(sub.user_strategy_id) === Number(r.id)
          )
          .map((sub) => `<p class="strategy-subscription-meta">${esc(btSubscriptionLabel(sub, list))}</p>`)
          .join('');
        const activeClass = r.id === _btCurrentUserStrategyId ? ' is-active' : '';
        const userSubbed = btHasActiveUserStrategySubscription(r.id, mode, activeSubs);
        const subBtn = userSubbed
          ? '<span class="btn-subscribe-pill is-subscribed">已订阅</span>'
          : `<button type="button" class="btn-subscribe bt-subscribe-user" data-usid="${r.id}">订阅</button>`;
        return `
      <div class="strategy-item bt-strategy-card${activeClass}" data-sid="${r.id}">
        <div class="strategy-item-title-row">
          <h3>${esc(r.name)}${r.in_use ? '<span class="badge-strategy-in-use">使用中</span>' : ''}</h3>
          <button type="button" class="btn-strategy-rename bt-strategy-rename" data-sid="${r.id}">改名</button>
        </div>
        <p>${esc(r.description || '回测页保存的策略')}</p>
        ${lines}
        <p class="strategy-caps-hint">仓位上限约 <strong>${((BT_USER_CAPS.max_position_pct || 0) * 100).toFixed(0)}%</strong> · 单笔上限约 <strong>${((BT_USER_CAPS.max_single_order_pct || 0) * 100).toFixed(0)}%</strong></p>
        <div class="strategy-card-actions">${subBtn}<button type="button" class="btn-strategy-delete bt-strategy-delete" data-sid="${r.id}">删除</button></div>
        <p class="bt-strategy-card-hint">点击卡片加载到下方编辑器</p>
      </div>`;
      })
      .join('');
    el.innerHTML = hint + userCards + builtinCard;
    el.querySelectorAll('.bt-strategy-card').forEach((card) => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-strategy-rename') || e.target.closest('.strategy-card-actions')) return;
        void loadUserStrategyById(parseInt(card.dataset.sid, 10));
      });
    });
    el.querySelectorAll('.bt-builtin-card').forEach((card) => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-subscribe-builtin') || e.target.closest('.strategy-builtin-actions')) return;
        void loadBuiltinTemplateForEditor();
      });
    });
    el.querySelectorAll('.bt-strategy-rename').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const id = parseInt(btn.dataset.sid, 10);
        void (async () => {
          try {
            const res = await window.api.userStrategies.get(id);
            const cur = res.data?.name || '';
            const name = prompt('新策略名称', cur);
            if (name == null || !String(name).trim()) return;
            await window.api.userStrategies.patchName(id, String(name).trim());
            if (_btCurrentUserStrategyId === id) {
              const ne = document.getElementById('bt-strategy-name');
              if (ne) ne.value = String(name).trim();
            }
            await loadUserStrategyList();
          } catch (err) {
            alert(err.message || String(err));
          }
        })();
      });
    });
    el.querySelectorAll('.btn-subscribe-builtin').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        void btSubscribeBuiltin(parseInt(btn.dataset.builtinStrategyId, 10));
      });
    });
    el.querySelectorAll('.bt-subscribe-user').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        void btSubscribeUser(parseInt(btn.dataset.usid, 10));
      });
    });
    el.querySelectorAll('.bt-strategy-delete').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        void btDeleteUserStrategy(parseInt(btn.dataset.sid, 10));
      });
    });
  } catch (e) {
    el.innerHTML = `<p class="backtest-hint">${esc(e.message || '加载失败')}</p>`;
  }
}

async function loadUserStrategyById(id) {
  if (!window.api?.userStrategies?.get) return;
  try {
    _btBuiltinEditorMode = false;
    const res = await window.api.userStrategies.get(id);
    if (!res.success || !res.data) return;
    _btCurrentUserStrategyId = id;
    const d = res.data;
    const nameEl = document.getElementById('bt-strategy-name');
    if (nameEl) nameEl.value = d.name || '';
    const cfg = d.config || {};
    const s = document.getElementById('bt-symbols');
    if (s) {
      s.value =
        typeof cfg.symbols === 'string' ? cfg.symbols : Array.isArray(cfg.symbols) ? cfg.symbols.join(',') : '';
    }
    const iv = document.getElementById('bt-interval');
    if (iv && cfg.interval) iv.value = cfg.interval;
    const mo = document.getElementById('bt-max-opens-day');
    if (mo) mo.value = cfg.max_opens_per_day != null ? String(cfg.max_opens_per_day) : '0';
    const adm = document.getElementById('bt-avg-daily-mode');
    if (adm) adm.value = cfg.avg_daily_mode === 'natural' ? 'natural' : 'trading';
    applyFactorSelection(cfg.active_factors || []);
    renderFavorites();
    markBacktestReportStale();
    void loadUserStrategyList();
    void loadBacktestRunsList();
    const msg = document.getElementById('bt-strategy-msg');
    if (msg) msg.textContent = `已加载策略 #${id}`;
  } catch (e) {
    alert(e.message || String(e));
  }
}

document.getElementById('bt-strategy-new')?.addEventListener('click', () => {
  const name = prompt('新策略名称', '');
  if (name == null || !String(name).trim()) return;
  _btCurrentUserStrategyId = null;
  _btBuiltinEditorMode = false;
  const nameEl = document.getElementById('bt-strategy-name');
  if (nameEl) nameEl.value = String(name).trim();
  resetBacktestEditorToDefaults();
  const msg = document.getElementById('bt-strategy-msg');
  if (msg) msg.textContent = '新建：调整参数后保存';
  void loadUserStrategyList();
});

document.getElementById('bt-strategy-save')?.addEventListener('click', async () => {
  const nameEl = document.getElementById('bt-strategy-name');
  const name = (nameEl?.value || '').trim();
  if (!name) {
    alert('请填写策略名称');
    return;
  }
  const cfg = collectStrategyConfigObject();
  const weights = buildWeightsFromLastBacktest();
  const summary = compactBacktestSummary(window._lastBacktestData);
  const body = {
    name,
    description: '',
    config_json: cfg,
    weights_json: weights,
    backtest_summary_json: Object.keys(summary).length ? summary : null,
  };
  try {
    if (_btCurrentUserStrategyId) {
      await window.api.userStrategies.update(_btCurrentUserStrategyId, body);
    } else {
      const res = await window.api.userStrategies.create(body);
      if (res.data?.id) {
        _btCurrentUserStrategyId = res.data.id;
        _btBuiltinEditorMode = false;
      }
    }
    const msg = document.getElementById('bt-strategy-msg');
    if (msg) msg.textContent = '已保存';
    await loadUserStrategyList();
  } catch (e) {
    alert(e.message || String(e));
  }
});

function btvRenderMonthTable(y, m0) {
  const firstDow = new Date(Date.UTC(y, m0, 1)).getUTCDay();
  const dim = new Date(Date.UTC(y, m0 + 1, 0)).getUTCDate();
  const weeks = [];
  let row = new Array(7).fill(null);
  let col = firstDow;
  for (let day = 1; day <= dim; day++) {
    row[col] = day;
    col++;
    if (col === 7) {
      weeks.push(row);
      row = new Array(7).fill(null);
      col = 0;
    }
  }
  if (row.some((x) => x != null)) weeks.push(row);
  const head = ['日', '一', '二', '三', '四', '五', '六']
    .map((h) => `<th>${h}</th>`)
    .join('');
  const body = weeks
    .map((r) => {
      const cells = r
        .map((day) => {
          if (day == null) return '<td class="bt-cal-empty"></td>';
          const ymd = `${y}-${String(m0 + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
          let cls = 'bt-cal-day';
          const outOfWin = _btvWindow && (ymd < _btvWindow.startYmd || ymd > _btvWindow.endYmd);
          if (outOfWin) cls += ' is-disabled';
          if (_btvYmdStart && _btvYmdEnd) {
            if (ymd === _btvYmdStart) cls += ' is-range-start';
            if (ymd === _btvYmdEnd) cls += ' is-range-end';
            if (ymd > _btvYmdStart && ymd < _btvYmdEnd) cls += ' is-in-range';
          }
          const dis = outOfWin ? 'disabled' : '';
          return `<td><button type="button" class="${cls}" data-ymd="${ymd}" ${dis}>${day}</button></td>`;
        })
        .join('');
      return `<tr>${cells}</tr>`;
    })
    .join('');
  return `<table class="bt-cal-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function btvRenderCalendars() {
  const w0 = document.getElementById('bt-verify-cal-wrap-0');
  const w1 = document.getElementById('bt-verify-cal-wrap-1');
  const nav = document.getElementById('bt-verify-cal-nav-label');
  if (!w0 || !w1) return;
  const y0 = _btvCalLeftY;
  const m0 = _btvCalLeftM0;
  const d1 = new Date(y0, m0 + 1, 1);
  const y1 = d1.getFullYear();
  const m1 = d1.getMonth();
  const titleA = `${y0}年${m0 + 1}月`;
  const titleB = `${y1}年${m1 + 1}月`;
  if (nav) nav.textContent = `${titleA}　·　${titleB}`;
  w0.innerHTML = `<div class="bt-cal-head">${titleA}</div>${btvRenderMonthTable(y0, m0)}`;
  w1.innerHTML = `<div class="bt-cal-head">${titleB}</div>${btvRenderMonthTable(y1, m1)}`;
  [w0, w1].forEach((w) => {
    w.querySelectorAll('.bt-cal-day').forEach((btn) => {
      btn.addEventListener('click', () => btvOnPickYmd(btn.getAttribute('data-ymd')));
    });
  });
  const hint = document.getElementById('bt-verify-foot-hint');
  if (hint) {
    hint.classList.remove('is-warn');
    hint.textContent = `跨度 ${BTV_MIN_SPAN_DAYS}～${BTV_MAX_SPAN_DAYS} 日，且必须落在回测区间内${btvFormatSpanHint() ? '；' + btvFormatSpanHint() : ''}`;
  }
}

function btvSetPopTabs(which) {
  _btvEditWhich = which === 'end' ? 'end' : 'start';
  document.querySelectorAll('#bt-verify-popover .bt-range-tab').forEach((btn) => {
    const w = btn.getAttribute('data-vwhich');
    const on = w === _btvEditWhich;
    btn.classList.toggle('is-active', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  const t = document.getElementById('bt-verify-pop-title');
  if (t) t.textContent = _btvEditWhich === 'start' ? '选择验真起始日期' : '选择验真结束日期';
}

function btvAnchorCal() {
  const anchor = (_btvEditWhich === 'end' ? _btvYmdEnd : _btvYmdStart) || _btvYmdStart || _btvWindow?.startYmd;
  if (anchor) {
    const [y, m] = anchor.split('-').map((x) => parseInt(x, 10));
    _btvCalLeftY = y;
    _btvCalLeftM0 = m - 1;
  } else {
    const now = new Date();
    _btvCalLeftY = now.getFullYear();
    _btvCalLeftM0 = now.getMonth();
  }
}

function btvShiftCal(dm) {
  const d = new Date(_btvCalLeftY, _btvCalLeftM0 + dm, 1);
  _btvCalLeftY = d.getFullYear();
  _btvCalLeftM0 = d.getMonth();
  btvRenderCalendars();
}

function btvOnPickYmd(ymd) {
  if (!ymd || !_btvWindow) return;
  if (ymd < _btvWindow.startYmd || ymd > _btvWindow.endYmd) return;
  if (_btvEditWhich === 'start') {
    _btvYmdStart = ymd;
    if (!_btvYmdEnd || _btvYmdEnd < _btvYmdStart) _btvYmdEnd = _btvYmdStart;
    const sp = btvDaysBetweenInclusive(_btvYmdStart, _btvYmdEnd);
    if (sp > BTV_MAX_SPAN_DAYS) {
      const cap = btvYmdAddDays(_btvYmdStart, BTV_MAX_SPAN_DAYS - 1);
      _btvYmdEnd = btvClampYmd(cap, _btvWindow);
    }
    btvSetPopTabs('end');
  } else {
    _btvYmdEnd = ymd;
    if (!_btvYmdStart || _btvYmdStart > _btvYmdEnd) _btvYmdStart = _btvYmdEnd;
    const sp = btvDaysBetweenInclusive(_btvYmdStart, _btvYmdEnd);
    if (sp > BTV_MAX_SPAN_DAYS) {
      const cap = btvYmdAddDays(_btvYmdEnd, -(BTV_MAX_SPAN_DAYS - 1));
      _btvYmdStart = btvClampYmd(cap, _btvWindow);
    }
  }
  syncBtvChips();
  btvRenderCalendars();
}

function openBtvPicker(which) {
  if (!_btvWindow) {
    alert('请先运行一次回测，再使用 K 线验真时段选择。');
    return;
  }
  btvSetPopTabs(which || 'start');
  btvAnchorCal();
  const pop = document.getElementById('bt-verify-popover');
  const bd = document.getElementById('bt-verify-backdrop');
  if (pop) pop.hidden = false;
  if (bd) bd.hidden = false;
  btvRenderCalendars();
}

function closeBtvPicker() {
  const pop = document.getElementById('bt-verify-popover');
  const bd = document.getElementById('bt-verify-backdrop');
  if (pop) pop.hidden = true;
  if (bd) bd.hidden = true;
}

document.getElementById('bt-verify-refresh')?.addEventListener('click', () => {
  void refreshBtVerifyChart();
});
document.getElementById('bt-verify-symbol')?.addEventListener('change', () => {
  void refreshBtVerifyChart();
});
document.getElementById('bt-verify-detail-iv')?.addEventListener('change', () => {
  void refreshBtVerifyChart();
});
document.getElementById('bt-verify-chip-start')?.addEventListener('click', () => openBtvPicker('start'));
document.getElementById('bt-verify-chip-end')?.addEventListener('click', () => openBtvPicker('end'));
document.getElementById('bt-verify-open-pop')?.addEventListener('click', () => openBtvPicker('start'));
document.getElementById('bt-verify-pop-close')?.addEventListener('click', () => closeBtvPicker());
document.getElementById('bt-verify-backdrop')?.addEventListener('click', () => closeBtvPicker());
document.querySelectorAll('#bt-verify-popover .bt-range-tab').forEach((btn) => {
  btn.addEventListener('click', () => btvSetPopTabs(btn.getAttribute('data-vwhich') || 'start'));
});
document.getElementById('bt-verify-cal-prev')?.addEventListener('click', () => btvShiftCal(-1));
document.getElementById('bt-verify-cal-next')?.addEventListener('click', () => btvShiftCal(1));
document.getElementById('bt-verify-pop-apply')?.addEventListener('click', () => {
  if (!_btvYmdStart || !_btvYmdEnd) {
    const hint = document.getElementById('bt-verify-foot-hint');
    if (hint) {
      hint.classList.add('is-warn');
      hint.textContent = '请选择起止日期后再完成';
    }
    return;
  }
  const days = btvDaysBetweenInclusive(_btvYmdStart, _btvYmdEnd);
  if (days < BTV_MIN_SPAN_DAYS || days > BTV_MAX_SPAN_DAYS) {
    const hint = document.getElementById('bt-verify-foot-hint');
    if (hint) {
      hint.classList.add('is-warn');
      hint.textContent = `跨度必须在 ${BTV_MIN_SPAN_DAYS}～${BTV_MAX_SPAN_DAYS} 日之间`;
    }
    return;
  }
  closeBtvPicker();
  void refreshBtVerifyChart();
});

document.getElementById('bt-runs-refresh')?.addEventListener('click', (e) => {
  e.preventDefault();
  void loadBacktestRunsList();
});
document.getElementById('bt-runs-only-current')?.addEventListener('change', () => {
  void loadBacktestRunsList();
});

void (async () => {
  await initFactorPanel();
  initBacktestRangeUI();
  void loadUserStrategyList();
  void loadBacktestRunsList();
  const st = document.getElementById('bt-status');
  if (st && !window._lastBacktestData) {
    st.textContent = '请设置标的与因子后点击「运行回测」；长区间拉 K 线时仪表盘非必要轮询会自动暂停。';
  }
})();

// 父窗口通知"策略 tab 被激活" / 镜像配置被外部（DevTools 探针、别处接口）变更 → 强制刷新列表同步按钮
window.addEventListener('message', (e) => {
  const t = e?.data?.type;
  if (t === 'page-activated' && e?.data?.page === 'strategy') {
    void loadBacktestRunsList();
  } else if (t === 'simulated-mirror-changed') {
    void loadBacktestRunsList();
  }
});
try {
  const bc = new BroadcastChannel('simulated-mirror');
  bc.addEventListener('message', (e) => {
    if (e?.data?.type === 'simulated-mirror-changed') void loadBacktestRunsList();
  });
} catch (_) {}
