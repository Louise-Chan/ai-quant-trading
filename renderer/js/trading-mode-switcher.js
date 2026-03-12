/** 交易模式切换（实盘/模拟）- 以后端 broker.status 为准 */
window.initTradingModeSwitcher = async function initTradingModeSwitcher() {
  const el = document.getElementById('trading-mode-switcher');
  if (!el || !window.api) return;

  const setLocalMode = (m) => {
    if (window.electronAPI?.store?.set) window.electronAPI.store.set('trading_mode', m);
    localStorage.setItem('trading_mode', m);
  };

  let currentMode = 'simulated';
  try {
    const res = await window.api.broker.status();
    currentMode = res.data?.current_mode || 'simulated';
    setLocalMode(currentMode);
  } catch (_) {
    const local = window.electronAPI ? await window.electronAPI.store.get('trading_mode') : localStorage.getItem('trading_mode');
    currentMode = local || 'simulated';
  }
  el.innerHTML = `
    <span class="mode-label">交易模式：</span>
    <button class="mode-btn ${currentMode === 'real' ? 'active' : ''}" data-mode="real">实盘</button>
    <button class="mode-btn ${currentMode === 'simulated' ? 'active' : ''}" data-mode="simulated">模拟</button>
  `;

  el.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const mode = btn.dataset.mode;
      if (mode === currentMode) return;
      if (mode === 'real' && !confirm('切换至实盘将使用真实资金，是否继续？')) return;
      try {
        await window.api.broker.setMode(mode);
        currentMode = mode;
        setLocalMode(mode);
        el.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        // 通知账户页刷新（模拟/实盘切换时实时更新）
        const frame = document.getElementById('page-frame');
        if (frame?.contentWindow) {
          frame.contentWindow.postMessage({ type: 'trading-mode-changed', mode }, '*');
        }
      } catch (e) {
        alert(e.message || '切换失败');
      }
    });
  });
};
