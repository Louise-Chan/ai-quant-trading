/** 策略中心：订阅、运行状态、专属风险（含 DeepSeek 预设） */
/** 与 backend/services/strategy_definitions.py STRATEGIES id 对应（仅用于订阅里 strategy_id、非 user_strategy_id） */
const BUILTIN_STRATEGY_NAMES = { 1: '稳健增长', 2: '积极进取' };
/** 与 strategy_definitions 中 risk_caps 一致 */
const BUILTIN_STRATEGY_CAPS = {
  1: { max_position_pct: 0.3, max_single_order_pct: 0.1 },
  2: { max_position_pct: 0.55, max_single_order_pct: 0.18 },
};

let _strategyList = [];
let _subscriptions = [];
let _currentRiskSubId = null;
let _riskCaps = null;
let _riskSettings = null;

async function getBrokerMode() {
  try {
    if (window.api?.broker?.status) {
      const r = await window.api.broker.status();
      return r?.data?.current_mode || 'simulated';
    }
  } catch (_) {}
  return localStorage.getItem('trading_mode') || 'simulated';
}

function strategyName(id) {
  const s = _strategyList.find((x) => x.id === id);
  return s ? s.name : `策略#${id}`;
}

/**
 * 单条订阅的展示文案（用户策略 id 与内置策略 id 分开解析，避免混淆）
 */
function subscriptionDisplayLabel(sub) {
  const usid =
    sub.user_strategy_id != null && Number(sub.user_strategy_id) > 0 ? Number(sub.user_strategy_id) : null;
  const sid = sub.strategy_id != null ? Number(sub.strategy_id) : 0;
  let namePart;
  if (usid) {
    namePart = strategyName(usid);
  } else if (sid > 0) {
    namePart = BUILTIN_STRATEGY_NAMES[sid] || `内置策略#${sid}`;
  } else {
    namePart = '订阅';
  }
  return `${namePart} · 模式 ${sub.mode} · 订阅 #${sub.id}`;
}

function hasActiveUserStrategySubscription(usid, mode) {
  const m = String(mode || 'simulated');
  return (_subscriptions || []).some(
    (s) =>
      s.status === 'active' &&
      Number(s.user_strategy_id) === Number(usid) &&
      String(s.mode) === m
  );
}

function hasActiveBuiltinSubscription(strategyId, mode) {
  const m = String(mode || 'simulated');
  return (_subscriptions || []).some(
    (s) =>
      s.status === 'active' &&
      (s.user_strategy_id == null || Number(s.user_strategy_id) <= 0) &&
      Number(s.strategy_id) === Number(strategyId) &&
      String(s.mode) === m
  );
}

/** 仅一张内置卡：汇总展示与分模板订阅/已订阅。 */
function buildSingleBuiltinCardHtml(mode) {
  const active = (_subscriptions || []).filter((s) => s.status === 'active');
  const builtinSubs = active.filter((s) => {
    const hasUs = s.user_strategy_id != null && Number(s.user_strategy_id) > 0;
    const sid = s.strategy_id != null ? Number(s.strategy_id) : 0;
    return !hasUs && sid > 0;
  });
  const metaLines = builtinSubs
    .map((sub) => `<p class="strategy-subscription-meta">${esc(subscriptionDisplayLabel(sub))}</p>`)
    .join('');
  const capHint =
    '稳健增长约 30% / 10% 单笔；积极进取约 55% / 18% 单笔（以策略中心风控为准）';
  const actions = [1, 2]
    .map((tid) => {
      const subbed = hasActiveBuiltinSubscription(tid, mode);
      const nm = BUILTIN_STRATEGY_NAMES[tid];
      return subbed
        ? `<span class="btn-subscribe-pill is-subscribed">${esc(nm)} 已订阅</span>`
        : `<button type="button" class="btn-subscribe btn-subscribe-builtin" data-builtin-strategy-id="${tid}">订阅${esc(nm)}</button>`;
    })
    .join('');
  return `
      <div class="strategy-item strategy-item--builtin">
        <div class="strategy-item-title-row">
          <h3>内置策略模板</h3>
          <span class="strategy-builtin-badge" title="非回测页保存的自定义策略">内置</span>
        </div>
        <p>默认因子 <strong>rev_1</strong>、<strong>vol_20</strong>、<strong>vol_z</strong>（与注册时默认策略一致）；含稳健增长、积极进取等模板，可与自定义策略分别订阅。</p>
        ${metaLines}
        <p class="strategy-caps-hint">${esc(capHint)}</p>
        <div class="strategy-builtin-actions">${actions}</div>
      </div>`;
}

async function deleteUserStrategyById(id) {
  if (!window.api?.userStrategies?.delete) return;
  if (!confirm('确定删除该策略？删除后不可恢复。')) return;
  try {
    await window.api.userStrategies.delete(id);
    await loadStrategies();
    await populateSubscriptionSelects();
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function loadStrategies() {
  if (!window.api) return;
  try {
    const res = await window.api.strategies.list(1, 20);
    _strategyList = res.data?.list || [];
    await loadSubscriptions();
    const mode = await getBrokerMode();
    document.getElementById('strategy-list').innerHTML =
      _strategyList
        .map((s) => {
          const activeSubs = (_subscriptions || []).filter(
            (sub) =>
              sub.status === 'active' &&
              sub.user_strategy_id != null &&
              Number(sub.user_strategy_id) > 0 &&
              Number(sub.user_strategy_id) === Number(s.id)
          );
          const subLines =
            activeSubs.length > 0
              ? activeSubs
                  .map(
                    (sub) =>
                      `<p class="strategy-subscription-meta">${esc(subscriptionDisplayLabel(sub))}</p>`
                  )
                  .join('')
              : '';
          const userSubbed = hasActiveUserStrategySubscription(s.id, mode);
          const subBtn = userSubbed
            ? '<span class="btn-subscribe-pill is-subscribed">已订阅</span>'
            : `<button type="button" class="btn-subscribe" data-usid="${s.id}">订阅</button>`;
          return `
      <div class="strategy-item">
        <div class="strategy-item-title-row">
          <h3>${esc(s.name)}${s.in_use ? '<span class="badge-strategy-in-use">使用中</span>' : ''}</h3>
          <button type="button" class="btn-strategy-rename" data-usid="${s.id}">改名</button>
        </div>
        <p>${esc(s.description || '')}</p>
        ${subLines}
        <p class="strategy-caps-hint">仓位上限约 <strong>${((s.max_position_pct_cap || 0) * 100).toFixed(0)}%</strong> · 单笔上限约 <strong>${((s.max_single_order_pct_cap || 0) * 100).toFixed(0)}%</strong></p>
        <div class="strategy-card-actions">${subBtn}<button type="button" class="btn-strategy-delete" data-usid="${s.id}">删除</button></div>
      </div>
    `;
        })
        .join('') + buildSingleBuiltinCardHtml(mode);
    document.querySelectorAll('#strategy-list .btn-subscribe:not(.btn-subscribe-builtin)').forEach((btn) => {
      btn.addEventListener('click', () => subscribe(parseInt(btn.dataset.usid, 10)));
    });
    document.querySelectorAll('.btn-subscribe-builtin').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        void subscribeBuiltin(parseInt(btn.dataset.builtinStrategyId, 10));
      });
    });
    document.querySelectorAll('.btn-strategy-rename').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.dataset.usid, 10);
        const cur = _strategyList.find((x) => x.id === id);
        const name = prompt('新策略名称', cur?.name || '');
        if (name == null || !String(name).trim()) return;
        void (async () => {
          try {
            await window.api.userStrategies.patchName(id, String(name).trim());
            await loadStrategies();
            await populateSubscriptionSelects();
          } catch (e) {
            alert(e.message);
          }
        })();
      });
    });
    document.querySelectorAll('.btn-strategy-delete').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        void deleteUserStrategyById(parseInt(btn.dataset.usid, 10));
      });
    });
  } catch (e) {
    document.getElementById('strategy-list').innerHTML = '<p>加载失败</p>';
  }
}

function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function subscribe(userStrategyId) {
  const mode = await getBrokerMode();
  if (!window.api) return;
  try {
    await window.api.strategies.subscribe({ user_strategy_id: userStrategyId, mode, params: {} });
    alert('订阅成功');
    await loadStrategies();
    await populateSubscriptionSelects();
  } catch (e) {
    alert(e.message);
  }
}

async function subscribeBuiltin(strategyId) {
  const mode = await getBrokerMode();
  if (!window.api) return;
  try {
    await window.api.strategies.subscribe({ strategy_id: strategyId, mode, params: {} });
    alert('订阅成功');
    await loadStrategies();
    await populateSubscriptionSelects();
  } catch (e) {
    alert(e.message);
  }
}

async function loadSubscriptions() {
  if (!window.api) return;
  try {
    const res = await window.api.strategies.subscriptions();
    _subscriptions = res.data?.list || [];
    const active = _subscriptions.filter((s) => s.status === 'active');
    document.getElementById('subscriptions-list').innerHTML = active.length
      ? active.map((s) => `
        <div class="subscription-item">
          <span>${esc(subscriptionDisplayLabel(s))}</span>
          <button class="btn-cancel" data-id="${s.id}">取消订阅</button>
        </div>
      `).join('')
      : '<p class="empty">暂无有效订阅（请先在上方订阅策略）</p>';
    document.querySelectorAll('.btn-cancel').forEach((btn) => {
      btn.addEventListener('click', () => cancelSub(parseInt(btn.dataset.id, 10)));
    });
  } catch (e) {
    document.getElementById('subscriptions-list').innerHTML = '<p>加载失败</p>';
  }
}

async function cancelSub(id) {
  if (!window.api) return;
  try {
    await window.api.strategies.cancelSubscription(id);
    await loadStrategies();
    await populateSubscriptionSelects();
    await refreshRuntimeBar();
  } catch (e) {
    alert(e.message);
  }
}

async function populateSubscriptionSelects() {
  const mode = await getBrokerMode();
  const selRun = document.getElementById('select-run-subscription');
  const selRisk = document.getElementById('select-risk-subscription');
  const active = _subscriptions.filter((s) => s.status === 'active' && s.mode === mode);
  const opts = '<option value="">— 请选择 —</option>' + active.map((s) =>
    `<option value="${s.id}">${esc(strategyName(s.user_strategy_id || s.strategy_id))} (#${s.id})</option>`
  ).join('');
  if (selRun) selRun.innerHTML = opts;
  if (selRisk) selRisk.innerHTML = opts;
}

async function refreshRuntimeBar() {
  const el = document.getElementById('runtime-status-text');
  if (!el || !window.api?.dashboard?.tradingState) {
    if (el) el.textContent = '无法获取状态';
    return;
  }
  try {
    const res = await window.api.dashboard.tradingState();
    const d = res.data || {};
    const mode = await getBrokerMode();
    let t = d.trading_running ? '● 运行中' : '○ 已停止';
    t += ` · 当前交易模式：<strong>${esc(d.current_mode || mode)}</strong>`;
    if (d.active_subscription_id && d.active_strategy_name) {
      t += ` · 关联订阅 #${d.active_subscription_id}（${esc(d.active_strategy_name)}）`;
    } else if (d.active_subscription_id) {
      t += ` · 关联订阅 #${d.active_subscription_id}`;
    } else {
      t += ' · 未指定运行订阅';
    }
    if (d.mode_mismatch) t += ' <span class="warn-text">（与当前模式不一致，请重新选择）</span>';
    el.innerHTML = t;
    const sel = document.getElementById('select-run-subscription');
    if (sel && d.active_subscription_id) {
      sel.value = String(d.active_subscription_id);
    }
  } catch (_) {
    el.textContent = '未登录或无法加载运行状态';
  }
}

document.getElementById('btn-set-active-subscription')?.addEventListener('click', async () => {
  const sel = document.getElementById('select-run-subscription');
  const id = sel?.value ? parseInt(sel.value, 10) : 0;
  if (!id) {
    alert('请先选择订阅');
    return;
  }
  try {
    await window.api.dashboard.setTradingState({ active_subscription_id: id });
    alert('已设为当前运行策略。可在仪表盘点击「开始交易」。');
    await refreshRuntimeBar();
  } catch (e) {
    alert(e.message);
  }
});

function settingsToSliderValues(settings, caps) {
  const mpc = caps.max_position_pct || 0.3;
  const mso = caps.max_single_order_pct || 0.15;
  const msl = caps.max_stop_loss_magnitude || 0.15;
  const mp = Math.round(((settings.max_position_pct || 0.1) / mpc) * 100);
  const ms = Math.round(((settings.max_single_order_pct || 0.05) / mso) * 100);
  const mag = Math.abs(settings.stop_loss || -0.05);
  const sl = Math.round((mag / msl) * 100);
  return {
    maxPos: Math.min(100, Math.max(1, mp)),
    maxSingle: Math.min(100, Math.max(1, ms)),
    stop: Math.min(100, Math.max(1, sl)),
  };
}

function sliderValuesToSettings(slMaxPos, slStop, slSingle, caps) {
  const mpc = caps.max_position_pct || 0.3;
  const mso = caps.max_single_order_pct || 0.15;
  const msl = caps.max_stop_loss_magnitude || 0.15;
  return {
    max_position_pct: (slMaxPos / 100) * mpc,
    stop_loss: -((slStop / 100) * msl),
    max_single_order_pct: (slSingle / 100) * mso,
  };
}

function updateRiskLabels() {
  const caps = _riskCaps;
  if (!caps) return;
  const rp = document.getElementById('range-max-position');
  const rs = document.getElementById('range-stop-loss');
  const rg = document.getElementById('range-max-single');
  const s = sliderValuesToSettings(
    parseInt(rp?.value || '50', 10),
    parseInt(rs?.value || '30', 10),
    parseInt(rg?.value || '40', 10),
    caps
  );
  const lp = document.getElementById('lbl-max-pos');
  const ls = document.getElementById('lbl-stop-loss');
  const lg = document.getElementById('lbl-max-single');
  if (lp) lp.textContent = `(${((s.max_position_pct) * 100).toFixed(1)}%)`;
  if (ls) ls.textContent = `(${(s.stop_loss * 100).toFixed(1)}%)`;
  if (lg) lg.textContent = `(${((s.max_single_order_pct) * 100).toFixed(1)}%)`;
}

async function loadRiskForSubscription(subId) {
  const ph = document.getElementById('risk-placeholder');
  const ed = document.getElementById('risk-editor');
  if (!subId || !window.api) {
    _currentRiskSubId = null;
    if (ph) ph.style.display = 'block';
    if (ed) ed.style.display = 'none';
    return;
  }
  try {
    const res = await window.api.strategies.subscriptionRisk(subId);
    const d = res.data;
    _currentRiskSubId = subId;
    _riskCaps = d.risk_caps;
    _riskSettings = d.settings;
    if (ph) ph.style.display = 'none';
    if (ed) ed.style.display = 'block';
    const capsEl = document.getElementById('risk-caps-display');
    if (capsEl && _riskCaps) {
      capsEl.innerHTML = `<strong>${esc(d.strategy_name)}</strong> 上限：总仓位 ≤ ${((_riskCaps.max_position_pct || 0) * 100).toFixed(0)}%，单笔 ≤ ${((_riskCaps.max_single_order_pct || 0) * 100).toFixed(0)}%，止损幅度 ≤ ${((_riskCaps.max_stop_loss_magnitude || 0) * 100).toFixed(0)}%`;
    }
    const sl = settingsToSliderValues(_riskSettings, _riskCaps);
    const rp = document.getElementById('range-max-position');
    const rs = document.getElementById('range-stop-loss');
    const rg = document.getElementById('range-max-single');
    if (rp) rp.value = String(sl.maxPos);
    if (rs) rs.value = String(sl.stop);
    if (rg) rg.value = String(sl.maxSingle);
    updateRiskLabels();
  } catch (e) {
    alert(e.message);
  }
}

['range-max-position', 'range-stop-loss', 'range-max-single'].forEach((id) => {
  document.getElementById(id)?.addEventListener('input', () => updateRiskLabels());
});

document.getElementById('select-risk-subscription')?.addEventListener('change', (e) => {
  const v = e.target.value ? parseInt(e.target.value, 10) : 0;
  document.getElementById('risk-presets-row').style.display = 'none';
  document.getElementById('deepseek-analysis').style.display = 'none';
  loadRiskForSubscription(v || null);
});

document.getElementById('btn-save-risk')?.addEventListener('click', async () => {
  if (!_currentRiskSubId || !_riskCaps) return;
  const rp = document.getElementById('range-max-position');
  const rs = document.getElementById('range-stop-loss');
  const rg = document.getElementById('range-max-single');
  const body = sliderValuesToSettings(
    parseInt(rp?.value || '50', 10),
    parseInt(rs?.value || '30', 10),
    parseInt(rg?.value || '40', 10),
    _riskCaps
  );
  try {
    await window.api.strategies.updateSubscriptionRisk(_currentRiskSubId, body);
    alert('已保存');
    await loadRiskForSubscription(_currentRiskSubId);
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById('btn-deepseek-risk-presets')?.addEventListener('click', async () => {
  const subId = _currentRiskSubId || (document.getElementById('select-risk-subscription')?.value
    ? parseInt(document.getElementById('select-risk-subscription').value, 10)
    : 0);
  if (!subId) {
    alert('请先选择要编辑风控的订阅');
    return;
  }
  if (!_currentRiskSubId) await loadRiskForSubscription(subId);
  try {
    const res = await window.api.strategies.subscriptionRiskPresetsDeepseek(subId);
    if (!res.success) {
      if (res.data?.needs_deepseek) {
        alert('请先在仪表盘「订单审核」栏或 DeepSeek 绑定弹窗中保存 API Key。');
        return;
      }
      alert(res.message || '生成失败');
      return;
    }
    const data = res.data || {};
    const analysisEl = document.getElementById('deepseek-analysis');
    const row = document.getElementById('risk-presets-row');
    if (analysisEl) {
      analysisEl.style.display = 'block';
      analysisEl.innerHTML = `<strong>DeepSeek 简析</strong>（参见 <a href="https://api-docs.deepseek.com/zh-cn/" target="_blank" rel="noopener">官方文档</a>）<p>${esc(data.analysis || '')}</p>`;
    }
    const presets = data.presets || {};
    const tiers = ['low', 'medium', 'high'];
    const labels = { low: '低风险预设', medium: '中风险预设', high: '高风险预设' };
    if (row) {
      row.style.display = 'flex';
      row.innerHTML = tiers.map((t) => {
        const p = presets[t];
        if (!p) return '';
        return `<div class="preset-card" data-tier="${t}">
          <h4>${esc(p.label || labels[t])}</h4>
          <p>总仓位 ${((p.max_position_pct || 0) * 100).toFixed(1)}%</p>
          <p>止损 ${((p.stop_loss || 0) * 100).toFixed(1)}%</p>
          <p>单笔 ${((p.max_single_order_pct || 0) * 100).toFixed(1)}%</p>
          <button type="button" class="btn-apply-preset">应用到滑块</button>
        </div>`;
      }).filter(Boolean).join('');
      row.querySelectorAll('.preset-card').forEach((card) => {
        const tier = card.dataset.tier;
        const p = presets[tier];
        card.querySelector('.btn-apply-preset')?.addEventListener('click', () => {
          if (!p || !_riskCaps) return;
          _riskSettings = {
            max_position_pct: p.max_position_pct,
            stop_loss: p.stop_loss,
            max_single_order_pct: p.max_single_order_pct,
          };
          const sl = settingsToSliderValues(_riskSettings, _riskCaps);
          document.getElementById('range-max-position').value = String(sl.maxPos);
          document.getElementById('range-stop-loss').value = String(sl.stop);
          document.getElementById('range-max-single').value = String(sl.maxSingle);
          updateRiskLabels();
        });
      });
    }
  } catch (e) {
    alert(e.message);
  }
});

const ANALYTICS_REFRESH_MS = 90000;

function renderAnalyticsTables(d) {
  const pred = d.prediction_model || {};
  const risk = d.risk_model || {};
  const attr = d.attribution_model || {};
  document.getElementById('score-pred').textContent =
    pred.aggregate_score != null ? String(pred.aggregate_score) : '—';
  document.getElementById('score-risk').textContent =
    risk.aggregate_score != null ? String(risk.aggregate_score) : '—';
  document.getElementById('score-attr').textContent =
    attr.aggregate_score != null ? String(attr.aggregate_score) : '—';

  const tbPred = document.querySelector('#tbl-pred tbody');
  const tbRisk = document.querySelector('#tbl-risk tbody');
  const tbAttr = document.querySelector('#tbl-attr tbody');
  if (tbPred) {
    tbPred.innerHTML = (pred.rows || []).map((r) => `
      <tr>
        <td>${esc(r.symbol)}</td>
        <td>${esc(r.model)}</td>
        <td>${r.p_up != null ? r.p_up : '—'}</td>
        <td>${r.holdout_accuracy != null ? r.holdout_accuracy : '—'}</td>
        <td>${r.train_rows != null ? r.train_rows : '—'}</td>
        <td>${r.score != null ? r.score : '—'}</td>
        <td>${esc(r.comment || '')}</td>
      </tr>`).join('') || '<tr><td colspan="7">无数据</td></tr>';
  }
  if (tbRisk) {
    tbRisk.innerHTML = (risk.rows || []).map((r) => `
      <tr>
        <td>${esc(r.symbol)}</td>
        <td>${r.sharpe_approx != null ? r.sharpe_approx : '—'}</td>
        <td>${r.max_drawdown != null ? r.max_drawdown : '—'}</td>
        <td>${r.realized_vol_20 != null ? r.realized_vol_20 : '—'}</td>
        <td>${r.kelly_suggested != null ? r.kelly_suggested : '—'}</td>
        <td>${r.score != null ? r.score : '—'}</td>
        <td>${esc(r.comment || '')}</td>
      </tr>`).join('') || '<tr><td colspan="7">无数据</td></tr>';
  }
  if (tbAttr) {
    tbAttr.innerHTML = (attr.rows || []).map((r) => `
      <tr>
        <td>${esc(r.symbol)}</td>
        <td>${esc((r.top_factors_by_weight || []).join(' · '))}</td>
        <td>${r.weighted_icir_proxy != null ? r.weighted_icir_proxy : '—'}</td>
        <td>${r.score != null ? r.score : '—'}</td>
        <td>${esc(r.comment || '')}</td>
      </tr>`).join('') || '<tr><td colspan="5">无数据</td></tr>';
  }

  const formalWrap = document.getElementById('analytics-formal-wrap');
  const brBench = document.getElementById('analytics-brinson-bench');
  const tbBr = document.querySelector('#tbl-brinson tbody tr');
  const tbFr = document.querySelector('#tbl-formal-risk tbody tr');
  const br = d.brinson_attribution;
  const fr = d.formal_risk_model;
  if (formalWrap && br?.ok && tbBr) {
    formalWrap.hidden = false;
    if (brBench) brBench.textContent = br.benchmark_description || '';
    const c = br.cumulative || {};
    tbBr.innerHTML = `
      <td>${c.allocation_effect != null ? c.allocation_effect : '—'}</td>
      <td>${c.selection_effect != null ? c.selection_effect : '—'}</td>
      <td>${c.interaction_effect != null ? c.interaction_effect : '—'}</td>
      <td>${c.active_return != null ? c.active_return : '—'}</td>
      <td>${c.check_sum != null ? c.check_sum : '—'}</td>`;
    if (fr?.ok && tbFr) {
      const top = (fr.top_risk_contributors || []).map((x) => `${esc(x.asset)} ${x.contrib_pct}`).join('；') || '—';
      tbFr.innerHTML = `
        <td>${fr.portfolio_vol_1bar != null ? fr.portfolio_vol_1bar : '—'}</td>
        <td>${fr.tracking_error_1bar != null ? fr.tracking_error_1bar : '—'}</td>
        <td>${fr.var_95_normal_1bar != null ? fr.var_95_normal_1bar : '—'}</td>
        <td>${fr.n_obs != null ? fr.n_obs : '—'}</td>
        <td>${top}</td>`;
    } else if (tbFr) {
      tbFr.innerHTML = '<td colspan="5">正式风险模型未算出（样本过短或数据不足）</td>';
    }
  } else if (formalWrap) {
    formalWrap.hidden = true;
  }
}

async function loadAnalyticsReport() {
  const errEl = document.getElementById('analytics-err');
  const stEl = document.getElementById('analytics-status');
  if (!window.api?.strategyEngine?.analyticsReport) {
    if (stEl) stEl.textContent = 'API 未就绪';
    return;
  }
  const symbols = (document.getElementById('analytics-symbols')?.value || '').trim();
  const interval = document.getElementById('analytics-interval')?.value || '1h';
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = '';
  }
  if (stEl) stEl.textContent = '加载中…';
  try {
    const mode = await getBrokerMode();
    const res = await window.api.strategyEngine.analyticsReport(symbols, interval, mode);
    if (!res.success || !res.data) {
      throw new Error(res.message || '加载失败');
    }
    renderAnalyticsTables(res.data);
    const gen = res.data.generated_at || '';
    const used = (res.data.symbols_used || []).join(', ');
    if (stEl) stEl.textContent = `已更新 ${gen ? new Date(gen).toLocaleString() : ''}${used ? ` · 标的: ${used}` : ''}`;
  } catch (e) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = e.message || String(e);
    }
    if (stEl) stEl.textContent = '刷新失败';
  }
}

document.getElementById('btn-analytics-refresh')?.addEventListener('click', () => {
  void loadAnalyticsReport();
});

document.getElementById('btn-strategy-create')?.addEventListener('click', () => {
  const name = prompt('新策略名称', '');
  if (name == null || !String(name).trim()) return;
  void (async () => {
    try {
      await window.api.userStrategies.create({
        name: String(name).trim(),
        description: '',
        config_json: {},
        weights_json: {},
      });
      await loadStrategies();
      await populateSubscriptionSelects();
    } catch (e) {
      alert(e.message || String(e));
    }
  })();
});

(async function init() {
  await loadStrategies();
  await populateSubscriptionSelects();
  await refreshRuntimeBar();
  setInterval(refreshRuntimeBar, 10000);
  await loadAnalyticsReport();
  setInterval(() => {
    void loadAnalyticsReport();
  }, ANALYTICS_REFRESH_MS);
})();
