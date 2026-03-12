/** 策略中心 */
async function loadStrategies() {
  if (!window.api) return;
  try {
    const res = await window.api.strategies.list(1, 20);
    const list = res.data?.list || [];
    document.getElementById('strategy-list').innerHTML = list.map(s => `
      <div class="strategy-item">
        <h3>${s.name}</h3>
        <p>${s.description || ''}</p>
        <button class="btn-subscribe" data-id="${s.id}">订阅</button>
      </div>
    `).join('');
    document.querySelectorAll('.btn-subscribe').forEach(btn => {
      btn.addEventListener('click', () => subscribe(parseInt(btn.dataset.id)));
    });
  } catch (e) {
    document.getElementById('strategy-list').innerHTML = '<p>加载失败</p>';
  }
}

async function subscribe(strategyId) {
  const mode = window.electronAPI ? await window.electronAPI.store.get('trading_mode') : localStorage.getItem('trading_mode') || 'simulated';
  if (!window.api) return;
  try {
    await window.api.strategies.subscribe(strategyId, mode, {});
    alert('订阅成功');
    loadSubscriptions();
  } catch (e) {
    alert(e.message);
  }
}

async function loadSubscriptions() {
  if (!window.api) return;
  try {
    const res = await window.api.strategies.subscriptions();
    const list = res.data?.list || [];
    document.getElementById('subscriptions-list').innerHTML = list.map(s => `
      <div class="subscription-item">
        <span>策略ID: ${s.strategy_id}</span>
        <span>模式: ${s.mode}</span>
        <span>状态: ${s.status}</span>
        <button class="btn-cancel" data-id="${s.id}">取消</button>
      </div>
    `).join('') || '<p class="empty">暂无订阅</p>';
    document.querySelectorAll('.btn-cancel').forEach(btn => {
      btn.addEventListener('click', () => cancelSub(parseInt(btn.dataset.id)));
    });
  } catch (e) {
    document.getElementById('subscriptions-list').innerHTML = '<p>加载失败</p>';
  }
}

async function cancelSub(id) {
  if (!window.api) return;
  try {
    await window.api.strategies.cancelSubscription(id);
    loadSubscriptions();
  } catch (e) {
    alert(e.message);
  }
}

loadStrategies();
loadSubscriptions();
