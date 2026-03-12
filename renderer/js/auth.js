/** 登录/注册逻辑 */
const tabs = document.querySelectorAll('.tab');
const formLogin = document.getElementById('form-login');
const formRegister = document.getElementById('form-register');
const msgEl = document.getElementById('auth-message');
const statusEl = document.getElementById('backend-status');

/** 检测后端连接，仅接受 gate-v2 (8081/8080/8000/8001) */
async function detectBackend() {
  const ports = [8081, 8080, 8000, 8001];
  if (statusEl) {
    statusEl.className = 'backend-status checking';
    statusEl.textContent = '正在检测后端连接...';
  }
  for (const port of ports) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/v1/health`);
      const data = await res.json();
      const ver = data?.data?.backend_version;
      if (data && data.success && ver === 'gate-v2') {
        window.API_BASE = `http://127.0.0.1:${port}/api/v1`;
        if (statusEl) {
          statusEl.className = 'backend-status ok';
          statusEl.textContent = '✓ 后端已连接 (gate-v2 端口 ' + port + ')';
        }
        document.getElementById('btn-retry')?.classList.add('hidden');
        return true;
      }
    } catch (_) {}
  }
  if (statusEl) {
    statusEl.className = 'backend-status fail';
    statusEl.innerHTML = '✗ 无法连接 gate-v2 后端<br><small>请运行 start-backend.bat 或 backend\\start.bat</small>';
  }
  const retryBtn = document.getElementById('btn-retry');
  if (retryBtn) retryBtn.classList.remove('hidden');
  return false;
}

document.getElementById('btn-retry')?.addEventListener('click', () => {
  const retryBtn = document.getElementById('btn-retry');
  if (retryBtn) retryBtn.classList.add('hidden');
  detectBackend();
});

// 页面加载时检测后端
detectBackend();

tabs.forEach(t => {
  t.addEventListener('click', () => {
    tabs.forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    const tab = t.dataset.tab;
    formLogin.classList.toggle('hidden', tab !== 'login');
    formRegister.classList.toggle('hidden', tab !== 'register');
    msgEl.textContent = '';
  });
});

function showMsg(text, isErr) {
  msgEl.textContent = text;
  msgEl.className = 'auth-message ' + (isErr ? 'error' : '');
}

formLogin.addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(formLogin);
  const username = fd.get('username');
  const password = fd.get('password');
  try {
    const base = (window.API_BASE || 'http://127.0.0.1:8081/api/v1');
    const res = await fetch(`${base}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (data.success && data.data?.token) {
      const token = data.data.token;
      if (window.electronAPI?.store?.set) await window.electronAPI.store.set('token', token);
      localStorage.setItem('token', token);
      if (window.electronAPI?.app?.openMain) {
        window.electronAPI.app.openMain(token);
      } else {
        window.location.href = 'app.html';
      }
    } else {
      showMsg(data.message || '登录失败', true);
    }
  } catch (err) {
    const msg = err.message === 'Failed to fetch' 
      ? '连接失败，请查看上方状态栏并确保后端已启动' 
      : (err.message || '网络错误');
    showMsg(msg, true);
  }
});

formRegister.addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(formRegister);
  const username = fd.get('username');
  const password = fd.get('password');
  const email = fd.get('email') || undefined;
  try {
    const base = (window.API_BASE || 'http://127.0.0.1:8081/api/v1');
    const res = await fetch(`${base}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, email }),
    });
    const data = await res.json();
    if (data.success && data.data?.token) {
      const token = data.data.token;
      if (window.electronAPI?.store?.set) await window.electronAPI.store.set('token', token);
      localStorage.setItem('token', token);
      if (window.electronAPI?.app?.openMain) {
        window.electronAPI.app.openMain(token);
      } else {
        window.location.href = 'app.html';
      }
    } else {
      showMsg(data.message || '注册失败', true);
    }
  } catch (err) {
    const msg = err.message === 'Failed to fetch' 
      ? '连接失败，请查看上方状态栏并确保后端已启动' 
      : (err.message || '网络错误');
    showMsg(msg, true);
  }
});
