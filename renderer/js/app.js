/** 主平台路由、导航 */
(async function init() {
  const token = window.electronAPI ? await window.electronAPI.store.get('token') : localStorage.getItem('token');
  if (!token && window.api) {
    try {
      await window.api.users.me();
    } catch {
      if (window.electronAPI?.app?.openAuth) window.electronAPI.app.openAuth();
      return;
    }
  }

  if (window.api) {
    try {
      const res = await window.api.users.me();
      document.getElementById('user-name').textContent = res.data?.nickname || res.data?.username || '用户';
    } catch (e) {
      console.warn(e);
    }
  }

  document.getElementById('btn-logout').addEventListener('click', async () => {
    try { await window.api?.auth?.logout?.(); } catch (e) {}
    if (window.electronAPI?.store?.set) window.electronAPI.store.set('token', null);
    localStorage.removeItem('token');
    if (window.electronAPI?.app?.openAuth) window.electronAPI.app.openAuth();
    window.close?.();
  });

  const navItems = document.querySelectorAll('.nav-item');
  const frame = document.getElementById('page-frame');
  const pages = { dashboard: 'dashboard', account: 'account', strategy: 'strategy', profile: 'profile' };

  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const page = item.dataset.page;
      navItems.forEach(n => n.classList.remove('active'));
      item.classList.add('active');
      frame.src = `pages/${page}/index.html`;
    });
  });
})();
