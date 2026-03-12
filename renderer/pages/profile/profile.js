/** 个人中心 */
async function loadBrokerStatus() {
  if (!window.api) return;
  try {
    const res = await window.api.broker.status();
    const d = res.data || {};
    document.getElementById('broker-status').innerHTML = `
      <p>实盘: ${d.real_bound ? '已绑定' : '未绑定'}</p>
      <p>模拟: ${d.simulated_bound ? '已绑定' : '未绑定'}</p>
      <p>当前模式: ${d.current_mode || '-'}</p>
    `;
  } catch (e) {
    document.getElementById('broker-status').innerHTML = '<p>加载失败</p>';
  }
}

async function loadUserInfo() {
  if (!window.api) return;
  try {
    const res = await window.api.users.me();
    const d = res.data || {};
    document.getElementById('user-info').innerHTML = `
      <p>用户名: ${d.username || '-'}</p>
      <p>邮箱: ${d.email || '-'}</p>
      <p>昵称: ${d.nickname || '-'}</p>
    `;
  } catch (e) {
    document.getElementById('user-info').innerHTML = '<p>加载失败</p>';
  }
}

document.getElementById('form-bind')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const mode = fd.get('mode');
  const api_key = fd.get('api_key');
  const api_secret = fd.get('api_secret');
  if (!window.api) return;
  try {
    await window.api.broker.bind(mode, api_key, api_secret);
    alert('绑定成功');
    loadBrokerStatus();
  } catch (err) {
    alert(err.message);
  }
});

loadBrokerStatus();
loadUserInfo();
