/** Unified single-window app - view switching */
(function() {
  const views = { welcome: 'view-welcome', 'auth-login': 'view-auth-login', 'auth-register': 'view-auth-register', main: 'view-main' };

  function showView(name) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const el = document.getElementById(views[name]);
    if (el) {
      el.classList.add('active');
      if (name === 'main') initMain();
      if (name === 'auth-login' || name === 'auth-register') detectBackend(name);
    }
  }

  function initMain() {
    const token = window.electronAPI ? (async () => {
      try { return await window.electronAPI.store.get('token'); } catch { return null; }
    })() : Promise.resolve(localStorage.getItem('token'));
    
    Promise.resolve(token).then(async t => {
      if (!t && window.api) {
        try { await window.api.users.me(); } catch {
          showView('auth-login');
          return;
        }
      }
      if (window.api) {
        try {
          const res = await window.api.users.me();
          const un = document.getElementById('user-name');
          if (un) un.textContent = res.data?.nickname || res.data?.username || '用户';
        } catch (e) { console.warn(e); }
      }
      if (typeof window.initTradingModeSwitcher === 'function') window.initTradingModeSwitcher();
      updateTime();
      setInterval(updateTime, 60000);
    });

    document.getElementById('btn-logout')?.addEventListener('click', async () => {
      try { await window.api?.auth?.logout?.(); } catch (e) {}
      if (window.electronAPI?.store?.set) window.electronAPI.store.set('token', null);
      localStorage.removeItem('token');
      showView('welcome');
    });

    const navItems = document.querySelectorAll('.nav-item');
    const frames = document.querySelectorAll('.page-frame');
    navItems.forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const page = item.dataset.page;
        navItems.forEach(n => n.classList.remove('active'));
        item.classList.add('active');
        frames.forEach(f => {
          f.classList.toggle('active', f.dataset.page === page);
        });
      });
    });
  }

  function updateTime() {
    const el = document.getElementById('header-time');
    if (el) {
      const d = new Date();
      el.textContent = d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' });
    }
  }

  // Welcome buttons
  document.getElementById('btn-login')?.addEventListener('click', () => showView('auth-login'));
  document.getElementById('btn-register')?.addEventListener('click', () => showView('auth-register'));

  // Auth switch links
  document.getElementById('link-to-register')?.addEventListener('click', (e) => { e.preventDefault(); showView('auth-register'); });
  document.getElementById('link-to-login')?.addEventListener('click', (e) => { e.preventDefault(); showView('auth-login'); });

  // Auth back buttons
  document.getElementById('btn-back-login')?.addEventListener('click', () => showView('welcome'));
  document.getElementById('btn-back-register')?.addEventListener('click', () => showView('welcome'));

  // Auth logic
  const formLogin = document.getElementById('form-login');
  const formRegister = document.getElementById('form-register');

  async function detectBackend(viewName) {
    const statusEl = document.getElementById('backend-status-' + (viewName === 'auth-login' ? 'login' : 'register'));
    const retryBtn = document.getElementById('btn-retry-' + (viewName === 'auth-login' ? 'login' : 'register'));
    const ports = [8081, 8080, 8000, 8001];
    if (statusEl) { statusEl.className = 'backend-status checking'; statusEl.textContent = '正在检测后端连接...'; }
    if (retryBtn) retryBtn.classList.add('hidden');
    for (const port of ports) {
      try {
        const res = await fetch(`http://127.0.0.1:${port}/api/v1/health`);
        const data = await res.json();
        const ver = data?.data?.backend_version;
        if (data && data.success && ver === 'gate-v2') {
          window.API_BASE = `http://127.0.0.1:${port}/api/v1`;
          if (statusEl) { statusEl.className = 'backend-status ok'; statusEl.textContent = '✓ 后端已连接 (gate-v2 端口 ' + port + ')'; }
          return true;
        }
      } catch (_) {}
    }
    if (statusEl) {
      statusEl.className = 'backend-status fail';
      statusEl.innerHTML = '✗ 无法连接 gate-v2 后端<br><small>请运行 start-backend.bat 或 backend\\start.bat</small>';
    }
    if (retryBtn) retryBtn.classList.remove('hidden');
    return false;
  }

  document.getElementById('btn-retry-login')?.addEventListener('click', () => detectBackend('auth-login'));
  document.getElementById('btn-retry-register')?.addEventListener('click', () => detectBackend('auth-register'));

  function showMsg(viewName, text, isErr) {
    const msgEl = document.getElementById('auth-message-' + (viewName === 'auth-login' ? 'login' : 'register'));
    if (msgEl) { msgEl.textContent = text; msgEl.className = 'auth-message ' + (isErr ? 'error' : ''); }
  }

  async function doLogin(username, password) {
    const base = window.API_BASE || 'http://127.0.0.1:8081/api/v1';
    const res = await fetch(`${base}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
    return res.json();
  }

  async function doRegister(username, password, email) {
    const base = window.API_BASE || 'http://127.0.0.1:8081/api/v1';
    const res = await fetch(`${base}/auth/register`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, email }) });
    return res.json();
  }

  function onAuthSuccess(data) {
    const token = data.data?.token;
    if (!token) return;
    if (window.electronAPI?.store?.set) window.electronAPI.store.set('token', token);
    localStorage.setItem('token', token);
    showView('main');
  }

  formLogin?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(formLogin);
    try {
      const data = await doLogin(fd.get('username'), fd.get('password'));
      if (data.success && data.data?.token) onAuthSuccess(data);
      else showMsg('auth-login', data.message || '登录失败', true);
    } catch (err) {
      showMsg('auth-login', err.message === 'Failed to fetch' ? '连接失败，请确保后端已启动' : (err.message || '网络错误'), true);
    }
  });

  formRegister?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(formRegister);
    try {
      const data = await doRegister(fd.get('username'), fd.get('password'), fd.get('email') || undefined);
      if (data.success && data.data?.token) onAuthSuccess(data);
      else showMsg('auth-register', data.message || '注册失败', true);
    } catch (err) {
      showMsg('auth-register', err.message === 'Failed to fetch' ? '连接失败，请确保后端已启动' : (err.message || '网络错误'), true);
    }
  });

  // 注册页：输入时实时校验用户名/邮箱是否已存在
  (function initRegisterCheck() {
    const usernameEl = document.getElementById('register-username');
    const emailEl = document.getElementById('register-email');
    let checkTimer = null;

    function debounceCheck() {
      if (checkTimer) clearTimeout(checkTimer);
      checkTimer = setTimeout(doCheck, 400);
    }

    async function doCheck() {
      const base = window.API_BASE || 'http://127.0.0.1:8081/api/v1';
      const username = usernameEl?.value?.trim();
      const email = emailEl?.value?.trim();
      if (!username && !email) {
        showMsg('auth-register', '', false);
        return;
      }
      try {
        const params = new URLSearchParams();
        if (username) params.set('username', username);
        if (email) params.set('email', email);
        const res = await fetch(`${base}/auth/check?${params}`);
        const data = await res.json();
        if (data?.success && data?.data) {
          const { username_exists, email_exists } = data.data;
          const msgs = [];
          if (username_exists) msgs.push('用户名已存在');
          if (email_exists) msgs.push('该邮箱已被注册过');
          showMsg('auth-register', msgs.join('，'), true);
        } else {
          showMsg('auth-register', '', false);
        }
      } catch (_) {
        showMsg('auth-register', '', false);
      }
    }

    usernameEl?.addEventListener('blur', debounceCheck);
    emailEl?.addEventListener('blur', debounceCheck);
    usernameEl?.addEventListener('input', () => { showMsg('auth-register', '', false); });
    emailEl?.addEventListener('input', () => { showMsg('auth-register', '', false); });
  })();

  window.showView = showView;

  (async function() {
    const t = window.electronAPI ? await window.electronAPI.store.get('token') : localStorage.getItem('token');
    if (t && window.api) {
      try {
        await window.api.users.me();
        showView('main');
        return;
      } catch (_) {}
    }
    showView('welcome');
  })();
})();
