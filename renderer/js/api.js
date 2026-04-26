/**
 * 后端 API 封装
 * baseURL 可配置，带 Token，统一响应格式
 */
const API_BASE = (typeof window !== 'undefined' && window.API_BASE) || 'http://127.0.0.1:8081/api/v1';
let _brokerStatusCache = null;
let _brokerStatusCacheAt = 0;
let _brokerStatusPending = null;
const BROKER_STATUS_TTL_MS = 4000;
const MARKET_QUOTES_TTL_MS = 3000;
const _marketQuotesCache = new Map();
const _marketQuotesPending = new Map();

function getPerfBoostUntil() {
  try {
    const v = Number(localStorage.getItem('dashboard_perf_boost_until') || '0');
    return Number.isFinite(v) ? v : 0;
  } catch (_) {
    return 0;
  }
}

async function getToken() {
  const electron = window.electronAPI || window.parent?.electronAPI;
  if (electron?.store?.get) {
    try {
      const t = await electron.store.get('token');
      if (t) return t;
    } catch (_) {}
  }
  return localStorage.getItem('token') || (window.parent && window.parent !== window ? window.parent.localStorage?.getItem?.('token') : null);
}

function setToken(token) {
  const electron = window.electronAPI || window.parent?.electronAPI;
  if (electron?.store?.set) {
    electron.store.set('token', token);
  }
  localStorage.setItem('token', token);
  try { window.parent?.localStorage?.setItem?.('token', token); } catch (_) {}
}

async function request(url, options = {}) {
  const allowSuccessFalse = Boolean(options.__allowSuccessFalse);
  const timeoutMs = Number(options.timeout_ms || 15000);
  const { __allowSuccessFalse: _a, timeout_ms: _t, ...fetchOptions } = options;
  const token = await getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...fetchOptions.headers,
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const ac = new AbortController();
  const extSig = fetchOptions.signal;
  let extAbortHandler = null;
  if (extSig) {
    if (extSig.aborted) ac.abort(extSig.reason);
    else {
      extAbortHandler = () => ac.abort(extSig.reason);
      extSig.addEventListener('abort', extAbortHandler, { once: true });
    }
  }
  const timer = setTimeout(() => ac.abort(new Error('timeout')), timeoutMs > 0 ? timeoutMs : 15000);
  let res;
  let text;
  try {
    res = await fetch(`${API_BASE}${url}`, { cache: 'no-store', ...fetchOptions, signal: ac.signal, headers });
    text = await res.text();
  } catch (e) {
    if (extSig && extSig.aborted) {
      throw e;
    }
    if (ac.signal.aborted || e?.name === 'AbortError') {
      throw new Error('请求超时，请稍后重试');
    }
    throw e;
  } finally {
    clearTimeout(timer);
    if (extSig && extAbortHandler) extSig.removeEventListener('abort', extAbortHandler);
  }
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_) {
    throw new Error((text || '').includes('Internal Server Error') || (text || '').startsWith('<')
      ? '后端服务异常，请查看后端控制台日志' : (text && text.length < 80 ? text : '响应格式错误'));
  }

  if (!res.ok) {
    throw new Error(data.message || `HTTP ${res.status}`);
  }
  if (data.success === false && !allowSuccessFalse) {
    throw new Error(data.message || '请求失败');
  }
  return data;
}

const api = {
  get: (url, opts) => request(url, { method: 'GET', ...opts }),
  post: (url, body, extra) => request(url, { method: 'POST', body: JSON.stringify(body), ...extra }),
  put: (url, body, extra) => request(url, { method: 'PUT', body: JSON.stringify(body), ...extra }),
  patch: (url, body) => request(url, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: (url) => request(url, { method: 'DELETE' }),

  auth: {
    login: (username, password) => api.post('/auth/login', { username, password }),
    register: (username, password, email) => api.post('/auth/register', { username, password, email }),
    logout: () => api.post('/auth/logout'),
  },
  users: {
    me: () => api.get('/users/me'),
    updateMe: (data) => api.patch('/users/me', data),
    preferences: () => api.get('/users/preferences'),
    updatePreferences: (data) => api.put('/users/preferences', data),
  },
  broker: {
    bind: (mode, api_key, api_secret) => api.post('/broker/bind', { mode, api_key, api_secret }),
    status: async (opts) => {
      const force = !!(opts && opts.force);
      const now = Date.now();
      if (!force && _brokerStatusCache && now - _brokerStatusCacheAt < BROKER_STATUS_TTL_MS) {
        return _brokerStatusCache;
      }
      if (!force && _brokerStatusPending) return _brokerStatusPending;
      _brokerStatusPending = api
        .get('/broker/status')
        .then((res) => {
          _brokerStatusCache = res;
          _brokerStatusCacheAt = Date.now();
          return res;
        })
        .finally(() => {
          _brokerStatusPending = null;
        });
      return _brokerStatusPending;
    },
    setMode: (mode) => api.put('/broker/mode', { mode }),
    unbind: (mode) => api.delete(`/broker/unbind${mode ? '?mode=' + mode : ''}`),
  },
  dashboard: {
    coins: (keyword, page, size) => api.get(`/dashboard/coins?keyword=${keyword || ''}&page=${page || 1}&size=${size || 50}`),
    watchlist: () => api.get('/dashboard/watchlist'),
    watchlistWithPositions: () => api.get('/dashboard/watchlist-with-positions'),
    addWatchlist: (symbol, quoteMarket) => {
      let u = `/dashboard/watchlist?symbol=${encodeURIComponent(symbol)}`;
      if (quoteMarket) u += `&quote_market=${encodeURIComponent(quoteMarket)}`;
      return api.post(u);
    },
    addWatchlistBatch: (symbols, items) =>
      api.post('/dashboard/watchlist/batch', items?.length ? { items } : { symbols: symbols || [] }),
    removeWatchlist: (symbol, quoteMarket) => {
      let u = `/dashboard/watchlist/${encodeURIComponent(symbol)}`;
      if (quoteMarket) u += `?quote_market=${encodeURIComponent(quoteMarket)}`;
      return api.delete(u);
    },
    tickers: (symbols, mode, opts) => {
      const o = opts && typeof opts === 'object' ? opts : {};
      const market = o.market || 'spot';
      const { market: _m, ...rest } = o;
      let u = `/dashboard/tickers?symbols=${encodeURIComponent(symbols || '')}&market=${encodeURIComponent(market)}`;
      if (mode) u += `&mode=${encodeURIComponent(mode)}`;
      return api.get(u, rest);
    },
    marketQuotes: (market, keyword, mode, limit) => {
      const m = market || 'spot';
      const kw = keyword || '';
      const md = mode || '';
      const lim = limit != null && limit > 0 ? limit : 800;
      const key = `${m}|${kw}|${md}|${lim}`;
      const now = Date.now();
      if (getPerfBoostUntil() <= now) {
        const c = _marketQuotesCache.get(key);
        if (c && now - c.at < MARKET_QUOTES_TTL_MS) {
          return Promise.resolve(c.res);
        }
        if (_marketQuotesPending.has(key)) return _marketQuotesPending.get(key);
      }
      let u = `/dashboard/market-quotes?market=${encodeURIComponent(market || 'spot')}&keyword=${encodeURIComponent(keyword || '')}`;
      if (mode) u += `&mode=${encodeURIComponent(mode)}`;
      u += `&limit=${encodeURIComponent(String(lim))}`;
      const req = api.get(u).then((res) => {
        _marketQuotesCache.set(key, { at: Date.now(), res });
        return res;
      }).finally(() => {
        _marketQuotesPending.delete(key);
      });
      _marketQuotesPending.set(key, req);
      return req;
    },
    smartSelectRules: () => api.get('/dashboard/smart-select-rules'),
    smartSelect: (body) => api.post('/dashboard/smart-select', body || {}),
    agentSelect: (body) => api.post('/dashboard/agent-select', body || {}, { __allowSuccessFalse: true }),
    tradingState: () => api.get('/dashboard/trading-state'),
    setTradingState: (body) => api.put('/dashboard/trading-state', body || {}),
  },
  market: {
    candlesticks: (symbol, interval, from_ts, to_ts, limit, opts) => {
      const o = opts && typeof opts === 'object' ? opts : {};
      const market = o.market || 'spot';
      const mode = o.mode;
      const { market: _m, mode: _mode, ...rest } = o;
      let u = `/market/candlesticks?symbol=${encodeURIComponent(symbol)}&interval=${interval || '1h'}&market=${encodeURIComponent(market)}`;
      if (from_ts) u += `&from_ts=${from_ts}`;
      if (to_ts) u += `&to_ts=${to_ts}`;
      u += `&limit=${limit || 300}`;
      if (mode) u += `&mode=${encodeURIComponent(mode)}`;
      return api.get(u, rest);
    },
  },
  portfolio: {
    summary: (mode, accountScope) => {
      const q = [];
      if (mode) q.push(`mode=${encodeURIComponent(mode)}`);
      if (accountScope) q.push(`account_scope=${encodeURIComponent(accountScope)}`);
      return api.get(`/portfolio/summary${q.length ? '?' + q.join('&') : ''}`, { timeout_ms: 60000 });
    },
    navHistory: (mode, accountScope) => {
      const q = [];
      if (mode) q.push(`mode=${encodeURIComponent(mode)}`);
      if (accountScope) q.push(`account_scope=${encodeURIComponent(accountScope)}`);
      return api.get(`/portfolio/nav-history${q.length ? '?' + q.join('&') : ''}`);
    },
  },
  assets: {
    balance: (mode, accountScope) => {
      const q = [];
      if (mode) q.push(`mode=${encodeURIComponent(mode)}`);
      if (accountScope) q.push(`account_scope=${encodeURIComponent(accountScope)}`);
      return api.get(`/assets/balance${q.length ? '?' + q.join('&') : ''}`, { timeout_ms: 60000 });
    },
  },
  trading: {
    orders: (mode, status, symbol, page, size) => api.get(`/trading/orders?mode=${mode || ''}&status=${status || ''}&symbol=${symbol || ''}&page=${page || 1}&size=${size || 20}`),
    positions: (mode) => api.get(`/trading/positions${mode ? '?mode=' + mode : ''}`),
    trades: (mode, symbol, page, size) => api.get(`/trading/trades?mode=${mode || ''}&symbol=${symbol || ''}&page=${page || 1}&size=${size || 20}`),
    cancelOrder: (id, symbol) => api.post(`/trading/orders/cancel/${id}?symbol=${encodeURIComponent(symbol || '')}`),
    /** 现货快捷下单；填写止盈/止损时后端登记跟踪任务，成交后轮询并市价平仓 */
    placeSpotBracket: (body) => api.post('/trading/spot-bracket-order', body || {}),
    /** 撤销当前标的全部现货挂单 + 市价卖出基础币 + 取消本地 bracket 跟踪 */
    closeAllSymbol: (symbol) => api.post('/trading/close-all-symbol', { symbol: symbol || '' }),
    bracketTracks: (limit) => api.get(`/trading/bracket-tracks?limit=${encodeURIComponent(String(limit || 30))}`),
    /** 更新止盈/止损价（K 线拖动或表单修改后同步到跟踪任务） */
    updateBracketTrack: (trackId, body) =>
      api.patch(`/trading/bracket-tracks/${encodeURIComponent(String(trackId))}`, body || {}),
  },
  strategies: {
    list: (page, size, category) => api.get(`/strategies?page=${page || 1}&size=${size || 20}${category ? '&category=' + category : ''}`),
    detail: (id) => api.get(`/strategies/${id}`),
    subscriptions: () => api.get('/strategies/subscriptions'),
    /** body: { user_strategy_id?, strategy_id?, mode, params } */
    subscribe: (body) => api.post('/strategies/subscribe', body || {}),
    updateSubscription: (id, params) => api.patch(`/strategies/subscriptions/${id}`, { params }),
    cancelSubscription: (id) => api.delete(`/strategies/subscriptions/${id}`),
    subscriptionRisk: (subId) => api.get(`/strategies/subscriptions/${subId}/risk`),
    updateSubscriptionRisk: (subId, data) => api.put(`/strategies/subscriptions/${subId}/risk`, data || {}),
    subscriptionRiskPresetsDeepseek: (subId) =>
      api.post(`/strategies/subscriptions/${subId}/risk/presets/deepseek`, {}, { __allowSuccessFalse: true }),
  },
  strategyEngine: {
    analyze: (symbol, interval, mode) => {
      let u = `/strategy-engine/analyze?symbol=${encodeURIComponent(symbol || '')}&interval=${encodeURIComponent(interval || '1h')}`;
      if (mode) u += `&mode=${encodeURIComponent(mode)}`;
      return api.get(u);
    },
    /** 预测/风险/归因 模型表格 + 评分（symbols 逗号分隔，可空=自选） */
    analyticsReport: (symbols, interval, mode) => {
      let u = `/strategy-engine/analytics-report?interval=${encodeURIComponent(interval || '1h')}`;
      if (symbols) u += `&symbols=${encodeURIComponent(symbols)}`;
      if (mode) u += `&mode=${encodeURIComponent(mode)}`;
      return api.get(u);
    },
    /**
     * 组合可视化回测；factorIds 为参与因子；range 可选 { startDate, endDate } 为 YYYY-MM-DD（同时传后端按区间拉 K 线）
     */
    backtestVisual: (symbols, interval, mode, factorIds, range, maxOpensPerDay, avgDailyMode) => {
      let u = `/strategy-engine/backtest-visual?interval=${encodeURIComponent(interval || '1h')}`;
      if (symbols) u += `&symbols=${encodeURIComponent(symbols)}`;
      if (mode) u += `&mode=${encodeURIComponent(mode)}`;
      if (factorIds && factorIds.length) u += `&factors=${encodeURIComponent(factorIds.join(','))}`;
      if (range?.startDate && range?.endDate) {
        u += `&start_date=${encodeURIComponent(range.startDate)}&end_date=${encodeURIComponent(range.endDate)}`;
      }
      if (Number.isFinite(Number(maxOpensPerDay)) && Number(maxOpensPerDay) > 0) {
        u += `&max_opens_per_day=${encodeURIComponent(String(Math.trunc(Number(maxOpensPerDay))))}`;
      }
      if (avgDailyMode === 'natural' || avgDailyMode === 'trading') {
        u += `&avg_daily_mode=${encodeURIComponent(avgDailyMode)}`;
      }
      return api.get(u, { timeout_ms: 900000 });
    },
    factorLibrary: () => api.get('/strategy-engine/factor-library'),
    factorLibraryRefreshAsync: (body) =>
      api.post('/strategy-engine/factor-library/refresh-async', body || {}, {
        __allowSuccessFalse: true,
        timeout_ms: 20000,
      }),
    factorLibraryRefreshStatus: (jobId) => api.get(`/strategy-engine/factor-library/refresh-status?job_id=${encodeURIComponent(String(jobId || ''))}`),
    /** mode: generate | screen | optimize */
    deepseekFactorScreen: (body) =>
      api.post('/strategy-engine/deepseek-factor-screen', body || {}, {
        __allowSuccessFalse: true,
        timeout_ms: 300000,
      }),
    /** 根据回测结构化摘要生成 DeepSeek 中文解读（纯文本/Markdown） */
    deepseekBacktestReport: (body) =>
      api.post('/strategy-engine/deepseek-backtest-report', body || {}, {
        __allowSuccessFalse: true,
        timeout_ms: 300000,
      }),
  },
  risk: {
    settings: (mode) => api.get(`/risk/settings${mode ? '?mode=' + mode : ''}`),
    updateSettings: (data, mode) => api.put(`/risk/settings${mode ? '?mode=' + mode : ''}`, data),
  },
  userStrategies: {
    list: () => api.get('/user-strategies'),
    get: (id) => api.get(`/user-strategies/${id}`),
    create: (body) => api.post('/user-strategies', body || {}),
    update: (id, body) => api.put(`/user-strategies/${id}`, body || {}),
    patchName: (id, name) => api.patch(`/user-strategies/${id}/name`, { name }),
    delete: (id) => api.delete(`/user-strategies/${id}`),
  },
  backtestRuns: {
    list: (limit, userStrategyId) => {
      const q = [];
      if (limit) q.push(`limit=${encodeURIComponent(String(limit))}`);
      if (userStrategyId != null && Number(userStrategyId) > 0) {
        q.push(`user_strategy_id=${encodeURIComponent(String(userStrategyId))}`);
      }
      return api.get(`/backtest-runs${q.length ? '?' + q.join('&') : ''}`);
    },
    get: (id) => api.get(`/backtest-runs/${encodeURIComponent(String(id || ''))}`),
    save: (body) => api.post('/backtest-runs', body || {}),
    delete: (id) => api.delete(`/backtest-runs/${encodeURIComponent(String(id || ''))}`),
  },
  simulatedMirror: {
    status: () => api.get('/simulated-mirror/status'),
    enable: (backtestRunId, currentNav, accountScope) =>
      api.post('/simulated-mirror/enable', {
        backtest_run_id: Number(backtestRunId || 0),
        current_nav: Number(currentNav || 0),
        account_scope: accountScope || 'spot',
      }),
    disable: () => api.post('/simulated-mirror/disable', {}),
    snapshot: (accountScope) =>
      api.get(`/simulated-mirror/snapshot${accountScope ? `?account_scope=${encodeURIComponent(accountScope)}` : ''}`),
  },
  orderAudit: {
    custodyStart: () => api.post('/order-audit/custody/start', {}),
    custodyStop: () => api.post('/order-audit/custody/stop', {}),
    custodyStatus: () => api.get('/order-audit/custody/status'),
    custodySettings: (body) => api.put('/order-audit/custody/settings', body || {}),
    generate: (body) => api.post('/order-audit/generate', body || {}),
    /** 多因子+ML+回测引擎写入 signal.strategy_engine 后送 DeepSeek 审核 */
    generateWithStrategyEngine: (body) => {
      const b = { use_strategy_engine: true, ...(body || {}) };
      try {
        const sigQm = b.signal && (b.signal.quote_market || b.signal.instrument_type);
        if (b.quote_market == null && !sigQm) {
          const qm = typeof window !== 'undefined' && window.getDashboardQuoteMarket?.();
          if (qm) b.quote_market = qm === 'futures' ? 'futures' : 'spot';
        }
      } catch (_) {}
      return api.post('/order-audit/generate', b);
    },
    list: (status, limit) => {
      let q = `limit=${limit || 80}`;
      if (status) q += `&status=${encodeURIComponent(status)}`;
      return api.get(`/order-audit/list?${q}`);
    },
    approve: (id, body) => api.post(`/order-audit/${id}/approve`, body ?? {}),
    reject: (id) => api.post(`/order-audit/${id}/reject`),
  },
};

window.api = api;
window.getToken = getToken;
window.setToken = setToken;
