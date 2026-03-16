/**
 * 后端 API 封装
 * baseURL 可配置，带 Token，统一响应格式
 */
const API_BASE = (typeof window !== 'undefined' && window.API_BASE) || 'http://127.0.0.1:8081/api/v1';

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
  const token = await getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${url}`, { cache: 'no-store', ...options, headers });
  const text = await res.text();
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
  if (data.success === false) {
    throw new Error(data.message || '请求失败');
  }
  return data;
}

const api = {
  get: (url, opts) => request(url, { method: 'GET', ...opts }),
  post: (url, body) => request(url, { method: 'POST', body: JSON.stringify(body) }),
  put: (url, body) => request(url, { method: 'PUT', body: JSON.stringify(body) }),
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
  },
  broker: {
    bind: (mode, api_key, api_secret) => api.post('/broker/bind', { mode, api_key, api_secret }),
    status: () => api.get('/broker/status'),
    setMode: (mode) => api.put('/broker/mode', { mode }),
    unbind: (mode) => api.delete(`/broker/unbind${mode ? '?mode=' + mode : ''}`),
  },
  dashboard: {
    coins: (keyword, page, size) => api.get(`/dashboard/coins?keyword=${keyword || ''}&page=${page || 1}&size=${size || 50}`),
    watchlist: () => api.get('/dashboard/watchlist'),
    watchlistWithPositions: () => api.get('/dashboard/watchlist-with-positions'),
    addWatchlist: (symbol) => api.post(`/dashboard/watchlist?symbol=${encodeURIComponent(symbol)}`),
    addWatchlistBatch: (symbols) => api.post('/dashboard/watchlist/batch', { symbols }),
    removeWatchlist: (symbol) => api.delete(`/dashboard/watchlist/${encodeURIComponent(symbol)}`),
    tickers: (symbols, mode, opts) => api.get(`/dashboard/tickers?symbols=${symbols || ''}${mode ? '&mode=' + mode : ''}`, opts),
    smartSelectRules: () => api.get('/dashboard/smart-select-rules'),
    smartSelect: (body) => api.post('/dashboard/smart-select', body || {}),
    agentSelect: (body) => api.post('/dashboard/agent-select', body || {}),
  },
  market: {
    candlesticks: (symbol, interval, from_ts, to_ts, limit, opts) => {
      let u = `/market/candlesticks?symbol=${encodeURIComponent(symbol)}&interval=${interval || '1h'}`;
      if (from_ts) u += `&from_ts=${from_ts}`;
      if (to_ts) u += `&to_ts=${to_ts}`;
      u += `&limit=${limit || 300}`;
      return api.get(u, opts);
    },
  },
  portfolio: {
    summary: (mode) => api.get(`/portfolio/summary${mode ? '?mode=' + mode : ''}`),
    navHistory: (mode) => api.get(`/portfolio/nav-history${mode ? '?mode=' + mode : ''}`),
  },
  assets: {
    balance: (mode) => api.get(`/assets/balance${mode ? '?mode=' + mode : ''}`),
  },
  trading: {
    orders: (mode, status, symbol, page, size) => api.get(`/trading/orders?mode=${mode || ''}&status=${status || ''}&symbol=${symbol || ''}&page=${page || 1}&size=${size || 20}`),
    positions: (mode) => api.get(`/trading/positions${mode ? '?mode=' + mode : ''}`),
    trades: (mode, symbol, page, size) => api.get(`/trading/trades?mode=${mode || ''}&symbol=${symbol || ''}&page=${page || 1}&size=${size || 20}`),
    cancelOrder: (id, symbol) => api.post(`/trading/orders/cancel/${id}?symbol=${encodeURIComponent(symbol || '')}`),
  },
  strategies: {
    list: (page, size, category) => api.get(`/strategies?page=${page || 1}&size=${size || 20}${category ? '&category=' + category : ''}`),
    detail: (id) => api.get(`/strategies/${id}`),
    subscriptions: () => api.get('/strategies/subscriptions'),
    subscribe: (strategy_id, mode, params) => api.post('/strategies/subscribe', { strategy_id, mode, params }),
    updateSubscription: (id, params) => api.patch(`/strategies/subscriptions/${id}`, { params }),
    cancelSubscription: (id) => api.delete(`/strategies/subscriptions/${id}`),
  },
  risk: {
    settings: (mode) => api.get(`/risk/settings${mode ? '?mode=' + mode : ''}`),
    updateSettings: (data, mode) => api.put(`/risk/settings${mode ? '?mode=' + mode : ''}`, data),
  },
};

window.api = api;
window.getToken = getToken;
window.setToken = setToken;
