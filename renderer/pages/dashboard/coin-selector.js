/** 智能选币 */
const searchEl = document.getElementById('coin-search');
const listEl = document.getElementById('coin-list');

async function getCurrentMode() {
  try {
    if (window.api?.broker?.status) {
      const res = await window.api.broker.status();
      return res?.data?.current_mode || 'real';
    }
  } catch (_) {}
  try {
    return window.electronAPI ? (await window.electronAPI.store.get('trading_mode')) : (localStorage.getItem('trading_mode') || 'real');
  } catch (_) {
    return 'real';
  }
}

async function loadCoins(keyword = '', page = 1) {
  if (!window.api) return;
  try {
    const res = await window.api.dashboard.coins(keyword, page, 50);
    const list = res.data?.list || [];
    listEl.innerHTML = list.map(p => `
      <div class="coin-item" data-symbol="${p.symbol || ''}">
        <span>${p.symbol || '-'}</span>
        <button class="btn-add">+ 自选</button>
      </div>
    `).join('');
    listEl.querySelectorAll('.btn-add').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = btn.closest('.coin-item');
        const symbol = item?.dataset?.symbol;
        if (symbol) addToWatchlist(symbol);
      });
    });
  } catch (e) {
    listEl.innerHTML = '<p class="empty">加载失败</p>';
  }
}

async function addToWatchlist(symbol) {
  if (!window.api) return;
  try {
    await window.api.dashboard.addWatchlist(symbol);
    if (window.loadWatchlist) window.loadWatchlist();
  } catch (e) {
    alert(e.message);
  }
}

let debounceTimer;
searchEl?.addEventListener('input', () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => loadCoins(searchEl.value), 300);
});

document.getElementById('btn-refresh-coins')?.addEventListener('click', () => loadCoins(searchEl?.value || ''));

// 一键选币：先进入调节页面，底部选币按钮才输出结果
document.getElementById('btn-smart-select')?.addEventListener('click', () => {
  showRuleSettingsModal();
});

// 接入 Agent 选币
document.getElementById('btn-agent-select')?.addEventListener('click', async () => {
  if (!window.api?.dashboard?.agentSelect) return;
  const pref = prompt('可选：输入选币偏好（如：偏稳健、高波动）', '');
  const btn = document.getElementById('btn-agent-select');
  const origText = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = '加载中...'; }
  try {
    const mode = await getCurrentMode();
    const res = await window.api.dashboard.agentSelect({ preference: pref || undefined, top_n: 8, mode });
    if (res?.success && res?.data?.symbols?.length) {
      showSmartSelectModal(res.data.symbols, res.data.source || 'ai_agent', res.data.summary);
    } else {
      alert(res?.message || 'Agent 服务暂未就绪');
    }
  } catch (e) {
    alert(e?.message || 'Agent 服务暂未就绪');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = origText || '接入Agent'; }
  }
});

// 调节页面：规则参数 + 底部选币按钮
function showRuleSettingsModal() {
  const modal = document.createElement('div');
  modal.className = 'smart-select-modal rule-settings-modal';
  modal.innerHTML = `
    <div class="smart-select-modal-content">
      <h3>选币规则调节</h3>
      <div class="rule-form">
        <div class="rule-row">
          <label>最低成交额（万 USDT）</label>
          <select id="rule-min-volume">
            <option value="1">1</option>
            <option value="5" selected>5</option>
            <option value="10">10</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </div>
        <div class="rule-row">
          <label>24h 涨跌幅上限（%）</label>
          <select id="rule-max-change">
            <option value="0.5">50</option>
            <option value="1" selected>100</option>
            <option value="2">200</option>
            <option value="5">500</option>
          </select>
        </div>
        <div class="rule-row">
          <label>推荐数量</label>
          <select id="rule-top-n">
            <option value="5">5</option>
            <option value="10" selected>10</option>
            <option value="15">15</option>
            <option value="20">20</option>
          </select>
        </div>
      </div>
      <div class="smart-select-actions">
        <button class="btn-cancel">取消</button>
        <button class="btn-do-select">选币</button>
      </div>
    </div>
  `;
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;';
  const content = modal.querySelector('.smart-select-modal-content');
  if (content) content.style.cssText = 'background:#fff;border-radius:12px;padding:1.5rem;max-width:380px;box-shadow:0 4px 20px rgba(0,0,0,0.15);';
  document.body.appendChild(modal);

  modal.querySelector('.btn-cancel')?.addEventListener('click', () => modal.remove());
  modal.querySelector('.btn-do-select')?.addEventListener('click', async () => {
    const minVol = parseInt(modal.querySelector('#rule-min-volume')?.value || '5', 10) * 10000;
    const maxChg = parseFloat(modal.querySelector('#rule-max-change')?.value || '1');
    const topN = parseInt(modal.querySelector('#rule-top-n')?.value || '10', 10);
    modal.remove();
    await doSmartSelectAndShowResults({ min_quote_volume: minVol, max_change_24h: maxChg, top_n: topN });
  });
}

// 执行选币并展示结果（结果页单选入自选）
async function doSmartSelectAndShowResults(params) {
  if (!window.api?.dashboard?.smartSelect) return;
  const btn = document.getElementById('btn-smart-select');
  const origText = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = '加载中...'; }
  try {
    const mode = await getCurrentMode();
    const res = await window.api.dashboard.smartSelect({ ...params, mode });
    if (res?.success && res?.data?.symbols?.length) {
      showSmartSelectResultModal(res.data.symbols, res.data.source || 'rule_engine');
    } else {
      alert(res?.message || '暂无推荐，请稍后重试');
    }
  } catch (e) {
    alert(e?.message || '选币服务暂未就绪');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = origText || '选币'; }
  }
}

// 结果页：每个币种可单选加入自选
function showSmartSelectResultModal(symbols, source) {
  const modal = document.createElement('div');
  modal.className = 'smart-select-modal result-modal';
  modal.innerHTML = `
    <div class="smart-select-modal-content">
      <h3>选币结果</h3>
      <p class="smart-select-source">来源：${source}</p>
      <div class="smart-select-list">
        ${symbols.map(s => `
          <div class="smart-select-result-item" data-symbol="${s.symbol}">
            <span class="symbol">${s.symbol}</span>
            ${s.reason ? `<small>${s.reason}</small>` : ''}
            <button class="btn-add-single">+ 自选</button>
          </div>
        `).join('')}
      </div>
      <div class="smart-select-actions">
        <button class="btn-close">关闭</button>
      </div>
    </div>
  `;
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;';
  const content = modal.querySelector('.smart-select-modal-content');
  if (content) content.style.cssText = 'background:#fff;border-radius:12px;padding:1.5rem;max-width:420px;max-height:85vh;overflow:auto;box-shadow:0 4px 20px rgba(0,0,0,0.15);';
  document.body.appendChild(modal);

  modal.querySelector('.btn-close')?.addEventListener('click', () => modal.remove());
  modal.querySelectorAll('.btn-add-single').forEach(btn => {
    btn.addEventListener('click', async () => {
      const item = btn.closest('.smart-select-result-item');
      const symbol = item?.dataset?.symbol;
      if (!symbol || !window.api) return;
      btn.disabled = true;
      try {
        await window.api.dashboard.addWatchlist(symbol);
        if (window.loadWatchlist) window.loadWatchlist();
        btn.textContent = '已添加';
        btn.classList.add('added');
      } catch (e) {
        btn.disabled = false;
        alert(e?.message || '添加失败');
      }
    });
  });
}

loadCoins();
