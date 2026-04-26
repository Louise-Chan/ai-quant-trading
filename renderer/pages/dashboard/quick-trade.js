/**
 * 快捷现货下单：买/卖 Tab、市场价格行；可选「触发止盈止损」勾选后显示盈亏比与止盈止损并随单登记跟踪。
 * 限价委托价：换标的时用打开图表当刻 K 线区价格快照一次。
 */
(function () {
  if (window.__quickTradeInit) {
    try {
      console.warn('[quick-trade] 脚本重复加载，已跳过重复绑定（避免重复下单）');
    } catch (_) {}
    return;
  }
  window.__quickTradeInit = true;

  const $ = (id) => document.getElementById(id);
  const selType = $('qt-order-type');
  const priceBlock = $('qt-price-block');
  const inpPrice = $('qt-price');
  const inpAmt = $('qt-amount');
  const inpUsdt = $('qt-usdt');
  const inpTp = $('qt-tp');
  const inpSl = $('qt-sl');
  const inpRR = $('qt-rr');
  const slider = $('qt-slider-pct');
  const sliderVis = $('qt-slider-visual');
  const pctNum = $('qt-pct-num');
  const btnSubmit = $('btn-qt-submit');
  const btnCloseAll = $('btn-qt-close-all');
  const baseUnitEl = $('qt-base-unit');
  const qtAvail = $('qt-avail');
  const qtAvailUnit = $('qt-avail-unit');
  const qtMaxBase = $('qt-max-base');
  const qtMaxUnit = $('qt-max-base-unit');
  const qtMaxSell = $('qt-max-sell');
  const qtMaxSellUnit = $('qt-max-sell-unit');
  const qtTabBuy = $('qt-tab-buy');
  const qtTabSell = $('qt-tab-sell');
  const qtRowMaxBuy = $('qt-row-max-buy');
  const qtRowMaxSell = $('qt-row-max-sell');
  const qtMarketPrice = $('qt-market-price');
  const chkBracket = $('qt-enable-bracket');
  const qtBracketFields = $('qt-bracket-fields');
  const qtInstrumentLabel = $('qt-instrument-label');
  const PERF_BOOST_KEY = 'dashboard_perf_boost_until';

  let activeSide = 'buy';
  let _lastSpotPrice = null;
  let _availUsdt = null;
  /** 当前标的可卖基础币数量（卖方 Tab 可用/滑条 100% 基准） */
  let _maxSellQty = null;
  let _priceFocused = false;
  /** 委托价已按「打开图表时」快照过的标的；同标的内不再用行情覆盖输入框 */
  let _qtSnapSymbol = null;
  let _rrApplyTimer = null;
  let _syncingTpSl = false;
  let _debTpToSl = null;
  let _debSlToTp = null;
  let _balanceTimer = null;
  /** 下单请求进行中，防止连点或 syncQuickTradeSymbol 中途把按钮重新启用 */
  let _submitInFlight = false;
  const DEFAULT_RISK_PCT = 0.01;

  function shouldPausePolling() {
    if (document.hidden) return true;
    try {
      const until = Number(localStorage.getItem(PERF_BOOST_KEY) || '0');
      return Number.isFinite(until) && until > Date.now();
    } catch (_) {
      return false;
    }
  }

  function markPerfBoost(ms) {
    const ttl = Number.isFinite(ms) ? ms : 5000;
    try {
      localStorage.setItem(PERF_BOOST_KEY, String(Date.now() + ttl));
    } catch (_) {}
  }

  function parseNum(s) {
    const v = parseFloat(String(s || '').replace(/,/g, '').trim());
    return Number.isFinite(v) ? v : NaN;
  }

  function priceDecimals(ref) {
    const r = Number(ref);
    if (!Number.isFinite(r) || r <= 0) return 4;
    return r >= 1000 ? 2 : r >= 1 ? 4 : 6;
  }

  function formatPriceVal(ref, x) {
    if (!Number.isFinite(x)) return '';
    const d = priceDecimals(ref);
    let t = x.toFixed(d);
    if (d > 2) t = t.replace(/\.?0+$/, '');
    return t;
  }

  function formatQty(n) {
    if (!Number.isFinite(n) || n <= 0) return '';
    let t = n.toFixed(8).replace(/\.?0+$/, '');
    const parts = t.split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return parts.join('.');
  }

  /** 交易额两位小数 + 千分位 */
  function formatUsdt2(n) {
    if (!Number.isFinite(n) || n < 0) return '';
    if (n === 0) return '0.00';
    const r = Math.round(n * 100) / 100;
    const s = r.toFixed(2);
    const [a, b] = s.split('.');
    const a2 = a.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return `${a2}.${b}`;
  }

  function baseFromPair(sym) {
    const s = String(sym || '').trim().toUpperCase();
    if (!s) return '—';
    const i = s.indexOf('_');
    return i > 0 ? s.slice(0, i) : s;
  }

  function getRefPrice() {
    const ot = selType?.value || 'limit';
    if (ot === 'market') return _lastSpotPrice;
    const p = parseNum(inpPrice?.value);
    if (Number.isFinite(p) && p > 0) return p;
    return _lastSpotPrice;
  }

  function parseRRStr(s) {
    const t = String(s || '').trim();
    if (!t) return 2;
    const m = t.match(/^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/);
    if (m) {
      const a = parseFloat(m[1]);
      const b = parseFloat(m[2]);
      if (Number.isFinite(a) && Number.isFinite(b) && b > 0) return a / b;
    }
    const m2 = /^(\d+(?:\.\d+)?)/.exec(t);
    return m2 ? parseFloat(m2[1]) : 2;
  }

  function bracketEnabled() {
    return Boolean(chkBracket?.checked);
  }

  function syncBracketFieldsVisibility() {
    const on = bracketEnabled();
    if (qtBracketFields) {
      if (on) qtBracketFields.removeAttribute('hidden');
      else qtBracketFields.setAttribute('hidden', '');
    }
  }

  /** 按参考价 E 与固定 1% 风险带写入止盈、止损（无有效手工价时） */
  function applyTpSlFromRR() {
    if (!bracketEnabled()) return;
    const E = getRefPrice();
    if (!Number.isFinite(E) || E <= 0) {
      return;
    }
    const rr = parseRRStr(inpRR?.value);
    if (!Number.isFinite(rr) || rr <= 0) {
      return;
    }
    const risk = E * DEFAULT_RISK_PCT;
    _syncingTpSl = true;
    try {
      if (activeSide === 'buy') {
        const sl = E - risk;
        const tp = E + rr * risk;
        if (inpSl) inpSl.value = formatPriceVal(E, sl);
        if (inpTp) inpTp.value = formatPriceVal(E, tp);
      } else {
        const sl = E + risk;
        const tp = E - rr * risk;
        if (inpSl) inpSl.value = formatPriceVal(E, sl);
        if (inpTp) inpTp.value = formatPriceVal(E, tp);
      }
    } finally {
      _syncingTpSl = false;
    }
  }

  /** 已填止盈（相对委托价方向正确）时，按盈亏比反推止损 */
  function syncSlFromTpInput() {
    if (!bracketEnabled()) return;
    if (_syncingTpSl) return;
    const E = getRefPrice();
    const rr = parseRRStr(inpRR?.value);
    const tp = parseNum(inpTp?.value);
    if (!Number.isFinite(E) || E <= 0 || !Number.isFinite(rr) || rr <= 0) return;
    if (!Number.isFinite(tp) || tp <= 0) return;
    if (activeSide === 'buy') {
      if (tp <= E) return;
      const risk = (tp - E) / rr;
      const sl = E - risk;
      if (!Number.isFinite(sl) || sl <= 0) return;
      _syncingTpSl = true;
      try {
        if (inpSl) inpSl.value = formatPriceVal(E, sl);
      } finally {
        _syncingTpSl = false;
      }
    } else {
      if (tp >= E) return;
      const risk = (E - tp) / rr;
      const sl = E + risk;
      if (!Number.isFinite(sl) || sl <= 0) return;
      _syncingTpSl = true;
      try {
        if (inpSl) inpSl.value = formatPriceVal(E, sl);
      } finally {
        _syncingTpSl = false;
      }
    }
  }

  /** 已填止损（相对委托价方向正确）时，按盈亏比反推止盈 */
  function syncTpFromSlInput() {
    if (!bracketEnabled()) return;
    if (_syncingTpSl) return;
    const E = getRefPrice();
    const rr = parseRRStr(inpRR?.value);
    const sl = parseNum(inpSl?.value);
    if (!Number.isFinite(E) || E <= 0 || !Number.isFinite(rr) || rr <= 0) return;
    if (!Number.isFinite(sl) || sl <= 0) return;
    if (activeSide === 'buy') {
      if (sl >= E) return;
      const risk = E - sl;
      const tp = E + rr * risk;
      if (!Number.isFinite(tp) || tp <= 0) return;
      _syncingTpSl = true;
      try {
        if (inpTp) inpTp.value = formatPriceVal(E, tp);
      } finally {
        _syncingTpSl = false;
      }
    } else {
      if (sl <= E) return;
      const risk = sl - E;
      const tp = E - rr * risk;
      if (!Number.isFinite(tp) || tp <= 0) return;
      _syncingTpSl = true;
      try {
        if (inpTp) inpTp.value = formatPriceVal(E, tp);
      } finally {
        _syncingTpSl = false;
      }
    }
  }

  /**
   * 价格/方向/盈亏比变化时：若止盈或止损已有合法手工值，则只联动另一方；否则用默认 1% 风险带填两者。
   */
  function reconcileTpSlWithDefault() {
    if (!bracketEnabled()) return;
    if (_syncingTpSl) return;
    const E = getRefPrice();
    const rr = parseRRStr(inpRR?.value);
    if (!Number.isFinite(E) || E <= 0 || !Number.isFinite(rr) || rr <= 0) return;
    const tp = parseNum(inpTp?.value);
    const sl = parseNum(inpSl?.value);
    const tpOk =
      Number.isFinite(tp) &&
      tp > 0 &&
      (activeSide === 'buy' ? tp > E : tp < E);
    const slOk =
      Number.isFinite(sl) &&
      sl > 0 &&
      (activeSide === 'buy' ? sl < E : sl > E);
    if (tpOk) {
      syncSlFromTpInput();
    } else if (slOk) {
      syncTpFromSlInput();
    } else {
      applyTpSlFromRR();
    }
  }

  function scheduleRR() {
    if (_rrApplyTimer) clearTimeout(_rrApplyTimer);
    _rrApplyTimer = setTimeout(() => {
      _rrApplyTimer = null;
      reconcileTpSlWithDefault();
    }, 80);
  }

  function setSliderPct(pct, updateQty) {
    const p = Math.max(0, Math.min(100, Math.round(pct)));
    if (slider) slider.value = String(p);
    /* WebKit 滑块轨道伪元素从 input 继承 CSS 变量，必须写在 range 上进度条才可见 */
    if (slider) slider.style.setProperty('--qt-pct', `${p}%`);
    if (sliderVis) sliderVis.style.setProperty('--qt-pct', `${p}%`);
    if (pctNum) pctNum.textContent = String(p);
    if (!updateQty) return;
    if (activeSide === 'sell') {
      const av = _maxSellQty;
      if (!Number.isFinite(av) || av <= 0) {
        if (inpUsdt) inpUsdt.value = '';
        if (inpAmt) inpAmt.value = '';
        return;
      }
      const q = (av * p) / 100;
      if (inpAmt) inpAmt.value = p === 0 ? '' : formatQty(q);
      syncUsdtFromQty();
      return;
    }
    const av = _availUsdt;
    if (!Number.isFinite(av) || av <= 0) {
      if (inpUsdt) inpUsdt.value = '';
      if (inpAmt) inpAmt.value = '';
      return;
    }
    const usdt = (av * p) / 100;
    if (inpUsdt) inpUsdt.value = p === 0 ? '' : formatUsdt2(usdt);
    syncQtyFromUsdt();
  }

  function pctFromUsdtInput() {
    if (activeSide === 'sell') {
      const av = _maxSellQty;
      if (!Number.isFinite(av) || av <= 0) return 0;
      const q = parseNum(inpAmt?.value);
      if (!Number.isFinite(q) || q <= 0) return 0;
      return Math.max(0, Math.min(100, Math.round((q / av) * 100)));
    }
    const av = _availUsdt;
    if (!Number.isFinite(av) || av <= 0) return 0;
    const u = parseNum(inpUsdt?.value);
    if (!Number.isFinite(u) || u <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((u / av) * 100)));
  }

  function syncQtyFromUsdt() {
    const pr = getRefPrice();
    const u = parseNum(inpUsdt?.value);
    if (!Number.isFinite(pr) || pr <= 0 || !Number.isFinite(u) || u <= 0) {
      if (inpAmt) inpAmt.value = '';
      return;
    }
    const q = u / pr;
    if (inpAmt) inpAmt.value = formatQty(q);
  }

  function syncUsdtFromQty() {
    const pr = getRefPrice();
    const q = parseNum(inpAmt?.value);
    if (!Number.isFinite(pr) || pr <= 0 || !Number.isFinite(q) || q <= 0) {
      if (inpUsdt) inpUsdt.value = '';
      setSliderPct(0, false);
      return;
    }
    const u = q * pr;
    if (inpUsdt) inpUsdt.value = formatUsdt2(u);
    if (activeSide === 'sell') {
      const av = _maxSellQty;
      if (Number.isFinite(av) && av > 0) {
        setSliderPct(Math.round((q / av) * 100), false);
      }
      return;
    }
    const av = _availUsdt;
    if (Number.isFinite(av) && av > 0) {
      setSliderPct(Math.round((u / av) * 100), false);
    }
  }

  function bumpPrice(dir) {
    if (!inpPrice) return;
    let v = parseNum(inpPrice.value);
    if (!Number.isFinite(v)) v = _lastSpotPrice || 0;
    let inc;
    if (v >= 10000) inc = 1;
    else if (v >= 1000) inc = 0.1;
    else if (v >= 100) inc = 0.01;
    else if (v >= 1) inc = 0.001;
    else if (v > 0) inc = Math.max(1e-8, v * 0.001);
    else inc = 0.0001;
    v = Math.max(0, v + dir * inc);
    const ref = _lastSpotPrice || v;
    inpPrice.value = formatPriceVal(ref, v);
    scheduleRR();
    syncQtyFromUsdt();
  }

  /**
   * 限价委托价：仅在标的切换时用「打开图表当刻」K 线区显示价写入一次；同标的下不随行情刷新覆盖。
   */
  function snapLimitPriceForSymbolIfNeeded(sym) {
    if (!inpPrice) return;
    if (selType?.value !== 'limit') return;
    if (!sym) {
      _qtSnapSymbol = null;
      inpPrice.value = '';
      return;
    }
    if (sym === _qtSnapSymbol) return;

    const tryWrite = () => {
      readPriceFromDom();
      const p = _lastSpotPrice;
      if (Number.isFinite(p) && p > 0) {
        inpPrice.value = formatPriceVal(p, p);
        scheduleRR();
        syncQtyFromUsdt();
        return true;
      }
      return false;
    };

    if (tryWrite()) {
      _qtSnapSymbol = sym;
      return;
    }
    requestAnimationFrame(() => {
      if (window.getDashboardCurrentSymbol?.() !== sym) return;
      tryWrite();
      _qtSnapSymbol = sym;
    });
  }

  function togglePriceBlock() {
    const isM = selType?.value === 'market';
    if (priceBlock) priceBlock.style.display = isM ? 'none' : '';
    scheduleRR();
    syncQtyFromUsdt();
  }

  function syncTabUI() {
    [qtTabBuy, qtTabSell].forEach((b) => {
      if (!b) return;
      const tab = b.getAttribute('data-qt-tab');
      const on = tab === activeSide;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    if (qtRowMaxBuy) qtRowMaxBuy.hidden = activeSide !== 'buy';
    if (qtRowMaxSell) qtRowMaxSell.hidden = activeSide !== 'sell';
    const sym = window.getDashboardCurrentSymbol?.() || '';
    const base = baseFromPair(sym);
    if (btnSubmit) {
      btnSubmit.classList.toggle('btn-qt-submit--buy', activeSide === 'buy');
      btnSubmit.classList.toggle('btn-qt-submit--sell', activeSide === 'sell');
      if (!sym) btnSubmit.textContent = activeSide === 'sell' ? '卖出 —' : '买入 —';
      else btnSubmit.textContent = activeSide === 'sell' ? `卖出 ${base}` : `买入 ${base}`;
    }
    if (qtAvailUnit) qtAvailUnit.textContent = activeSide === 'sell' ? base : 'USDT';
    const dis = !sym || _submitInFlight;
    if (slider) {
      if (activeSide === 'sell') {
        slider.disabled = !Number.isFinite(_maxSellQty) || _maxSellQty <= 0;
      } else {
        slider.disabled = !Number.isFinite(_availUsdt) || _availUsdt <= 0;
      }
    }
    if (btnSubmit) btnSubmit.disabled = dis;
  }

  async function setActiveSide(side) {
    const s = side === 'sell' ? 'sell' : 'buy';
    activeSide = s;
    syncTabUI();
    await refreshBalances();
    syncUsdtFromQty();
    scheduleRR();
  }

  function updateMarketPriceDisplay() {
    if (!qtMarketPrice) return;
    const p = _lastSpotPrice;
    if (Number.isFinite(p) && p > 0) qtMarketPrice.textContent = `$${formatPriceVal(p, p)}`;
    else qtMarketPrice.textContent = '--';
  }

  async function fetchMaxSellQty(sym, mode) {
    if (!sym || !window.api?.trading?.positions) return null;
    try {
      const res = await window.api.trading.positions(mode);
      const list = res?.data?.list || [];
      const b = baseFromPair(sym);
      let amt = null;
      list.forEach((pos) => {
        const s = String(pos.symbol || '').toUpperCase();
        const c = String(pos.currency || '').toUpperCase();
        if (s === sym.toUpperCase() || c === b) {
          const a = parseFloat(pos.available ?? pos.amount ?? 0);
          if (Number.isFinite(a)) amt = (amt || 0) + a;
        }
      });
      return amt != null && amt > 0 ? amt : null;
    } catch (_) {
      return null;
    }
  }

  function readPriceFromDom() {
    const el = document.getElementById('kline-realtime-price');
    if (!el) return;
    const t = (el.textContent || '').trim();
    if (!t) return;
    const v = parseFloat(t.replace(/,/g, ''));
    if (Number.isFinite(v) && v > 0) _lastSpotPrice = v;
  }

  function quoteMarketTitle() {
    const qm = window.getDashboardQuoteMarket?.() || 'spot';
    if (qm === 'futures') return '合约';
    if (qm === 'option') return '期权';
    return '现货';
  }

  function syncQuickTradeSymbol() {
    const sym = window.getDashboardCurrentSymbol?.() || '';
    if (qtInstrumentLabel) qtInstrumentLabel.textContent = quoteMarketTitle();
    const base = baseFromPair(sym);
    if (baseUnitEl) baseUnitEl.textContent = base;
    if (qtMaxUnit) qtMaxUnit.textContent = base;
    if (qtMaxSellUnit) qtMaxSellUnit.textContent = base;
    syncTabUI();
    if (btnCloseAll) btnCloseAll.disabled = !sym || _submitInFlight;
    readPriceFromDom();
    updateMarketPriceDisplay();
    snapLimitPriceForSymbolIfNeeded(sym);
    scheduleRR();
    refreshBalances();
  }

  async function refreshBalances() {
    if (!window.api?.assets?.balance) return;
    let mode = 'real';
    try {
      if (window.api.broker?.status) {
        const r = await window.api.broker.status();
        mode = r?.data?.current_mode || 'real';
      }
    } catch (_) {}
    const balScope = window.getDashboardQuoteMarket?.() === 'futures' ? 'futures' : 'spot';
    try {
      const res = await window.api.assets.balance(mode, balScope);
      const av = res?.data?.available;
      _availUsdt = typeof av === 'number' && Number.isFinite(av) ? av : null;
      if (slider && activeSide === 'buy') {
        slider.disabled = !Number.isFinite(_availUsdt) || _availUsdt <= 0;
      }
    } catch (_) {
      _availUsdt = null;
      if (slider && activeSide === 'buy') slider.disabled = true;
    }

    const sym = window.getDashboardCurrentSymbol?.() || '';
    const pr = getRefPrice();
    let maxBuyQty = null;
    if (Number.isFinite(_availUsdt) && _availUsdt > 0 && Number.isFinite(pr) && pr > 0) {
      maxBuyQty = _availUsdt / pr;
    }
    if (qtMaxBase) qtMaxBase.textContent = maxBuyQty != null ? formatQty(maxBuyQty) || '--' : '--';

    const maxSellQty = sym ? await fetchMaxSellQty(sym, mode) : null;
    _maxSellQty = maxSellQty != null && maxSellQty > 0 ? maxSellQty : null;
    if (qtMaxSell) qtMaxSell.textContent = maxSellQty != null ? formatQty(maxSellQty) || '--' : '--';

    if (qtAvail) {
      if (activeSide === 'sell') {
        if (_maxSellQty != null && _maxSellQty > 0) qtAvail.textContent = formatQty(_maxSellQty) || '--';
        else qtAvail.textContent = '--';
      } else if (_availUsdt != null && _availUsdt >= 0) qtAvail.textContent = formatUsdt2(_availUsdt) || '0.00';
      else qtAvail.textContent = '--';
    }
    if (slider && activeSide === 'sell') {
      slider.disabled = !Number.isFinite(_maxSellQty) || _maxSellQty <= 0;
    }
    syncTabUI();
  }

  async function submit(side) {
    if (_submitInFlight) return;
    if (!window.api?.trading?.placeSpotBracket) {
      alert('API 未就绪');
      return;
    }
    const sym = window.getDashboardCurrentSymbol?.() || '';
    if (!sym) {
      alert('请先在行情或自选中选择标的以加载 K 线');
      return;
    }
    const orderType = selType?.value || 'limit';
    const amountRaw = (inpAmt?.value || '').replace(/,/g, '').trim();
    const priceRaw = (inpPrice?.value || '').replace(/,/g, '').trim();
    const useBracket = bracketEnabled();
    const tp = useBracket ? (inpTp?.value || '').replace(/,/g, '').trim() : '';
    const sl = useBracket ? (inpSl?.value || '').replace(/,/g, '').trim() : '';
    if (!amountRaw || parseFloat(amountRaw) <= 0) {
      alert('请填写数量');
      return;
    }
    if (orderType === 'limit' && (!priceRaw || parseFloat(priceRaw) <= 0)) {
      alert('限价单请填写委托价格');
      return;
    }
    if (useBracket && !tp && !sl) {
      alert('已勾选「触发止盈止损」时，请至少填写止盈或止损价格');
      return;
    }
    const body = {
      symbol: sym,
      side,
      order_type: orderType,
      amount: amountRaw,
      price: orderType === 'limit' ? priceRaw : priceRaw || undefined,
      take_profit_price: useBracket ? tp || undefined : undefined,
      stop_loss_price: useBracket ? sl || undefined : undefined,
    };
    const oldTxt = btnSubmit?.textContent;
    _submitInFlight = true;
    markPerfBoost(7000);
    if (btnSubmit) btnSubmit.disabled = true;
    try {
      const res = await window.api.trading.placeSpotBracket(body);
      const msg = res.message || '已提交';
      const tk = res.data?.tracking;
      alert(msg + (tk ? '\n（已登记止盈/止损跟踪，成交后由服务器按现价相对开仓价在止损/止盈限价间自动改单）' : ''));
      try {
        window.dispatchEvent(new CustomEvent('dashboard-bracket-refresh'));
      } catch (_) {}
    } catch (e) {
      alert(e.message || '下单失败');
    } finally {
      _submitInFlight = false;
      if (btnSubmit && oldTxt) btnSubmit.textContent = oldTxt;
      syncQuickTradeSymbol();
    }
  }

  qtTabBuy?.addEventListener('click', () => {
    void setActiveSide('buy');
  });
  qtTabSell?.addEventListener('click', () => {
    void setActiveSide('sell');
  });

  chkBracket?.addEventListener('change', () => {
    syncBracketFieldsVisibility();
    if (bracketEnabled()) reconcileTpSlWithDefault();
  });

  selType?.addEventListener('change', () => {
    togglePriceBlock();
    syncQtyFromUsdt();
    scheduleRR();
  });

  inpPrice?.addEventListener('focus', () => {
    _priceFocused = true;
  });
  inpPrice?.addEventListener('blur', () => {
    _priceFocused = false;
    scheduleRR();
    syncQtyFromUsdt();
  });
  inpPrice?.addEventListener('input', () => {
    scheduleRR();
    syncQtyFromUsdt();
  });

  inpAmt?.addEventListener('input', () => {
    const raw = (inpAmt.value || '').replace(/,/g, '').trim();
    const v = parseFloat(raw);
    if (!raw || !Number.isFinite(v) || v === 0) {
      inpAmt.value = '';
      if (inpUsdt) inpUsdt.value = '';
      setSliderPct(0, false);
      return;
    }
    syncUsdtFromQty();
  });

  inpUsdt?.addEventListener('input', () => {
    const raw = (inpUsdt.value || '').replace(/,/g, '').trim();
    const v = parseFloat(raw);
    if (!raw || !Number.isFinite(v) || v <= 0) {
      inpUsdt.value = '';
      if (inpAmt) inpAmt.value = '';
      setSliderPct(0, false);
      return;
    }
    if (activeSide === 'sell') {
      syncQtyFromUsdt();
      setSliderPct(pctFromUsdtInput(), false);
      return;
    }
    setSliderPct(pctFromUsdtInput(), false);
    syncQtyFromUsdt();
  });

  slider?.addEventListener('input', () => {
    const p = parseInt(slider.value, 10) || 0;
    if (slider) slider.style.setProperty('--qt-pct', `${p}%`);
    if (sliderVis) sliderVis.style.setProperty('--qt-pct', `${p}%`);
    if (pctNum) pctNum.textContent = String(p);
    if (activeSide === 'sell') {
      const av = _maxSellQty;
      if (!Number.isFinite(av) || av <= 0) return;
      if (p === 0) {
        if (inpUsdt) inpUsdt.value = '';
        if (inpAmt) inpAmt.value = '';
        return;
      }
      const q = (av * p) / 100;
      if (inpAmt) inpAmt.value = formatQty(q);
      syncUsdtFromQty();
      return;
    }
    const av = _availUsdt;
    if (!Number.isFinite(av) || av <= 0) return;
    if (p === 0) {
      if (inpUsdt) inpUsdt.value = '';
      if (inpAmt) inpAmt.value = '';
      return;
    }
    const usdt = (av * p) / 100;
    if (inpUsdt) inpUsdt.value = formatUsdt2(usdt);
    syncQtyFromUsdt();
  });

  inpRR?.addEventListener('input', scheduleRR);
  inpRR?.addEventListener('change', () => reconcileTpSlWithDefault());

  inpTp?.addEventListener('input', () => {
    if (_syncingTpSl) return;
    if (_debTpToSl) clearTimeout(_debTpToSl);
    _debTpToSl = setTimeout(() => {
      _debTpToSl = null;
      syncSlFromTpInput();
    }, 100);
  });
  inpTp?.addEventListener('blur', () => {
    if (_debTpToSl) {
      clearTimeout(_debTpToSl);
      _debTpToSl = null;
    }
    syncSlFromTpInput();
  });

  inpSl?.addEventListener('input', () => {
    if (_syncingTpSl) return;
    if (_debSlToTp) clearTimeout(_debSlToTp);
    _debSlToTp = setTimeout(() => {
      _debSlToTp = null;
      syncTpFromSlInput();
    }, 100);
  });
  inpSl?.addEventListener('blur', () => {
    if (_debSlToTp) {
      clearTimeout(_debSlToTp);
      _debSlToTp = null;
    }
    syncTpFromSlInput();
  });

  document.querySelectorAll('[data-qt-step]').forEach((b) => {
    b.addEventListener('click', () => {
      const id = b.getAttribute('data-qt-step');
      const step = parseInt(b.getAttribute('data-step') || '0', 10);
      if (id === 'qt-price') bumpPrice(step);
    });
  });

  btnSubmit?.addEventListener('click', () => submit(activeSide));

  btnCloseAll?.addEventListener('click', async () => {
    if (!window.api?.trading?.closeAllSymbol) {
      alert('API 未就绪');
      return;
    }
    const sym = window.getDashboardCurrentSymbol?.() || '';
    if (!sym) {
      alert('请先在行情或自选中选择标的');
      return;
    }
    const base = baseFromPair(sym);
    if (
      !confirm(
        `确定对 ${sym} 一键平仓？\n将撤销该标的全部现货挂单，并市价卖出当前持有的 ${base}（如有），并停止止盈止损跟踪。`
      )
    ) {
      return;
    }
    const old = btnCloseAll?.textContent;
    if (btnCloseAll) btnCloseAll.disabled = true;
    markPerfBoost(7000);
    try {
      const res = await window.api.trading.closeAllSymbol(sym);
      alert(res?.message || (res?.success ? '已完成' : '操作失败'));
      try {
        window.dispatchEvent(new CustomEvent('dashboard-bracket-refresh'));
      } catch (_) {}
      await refreshBalances();
    } catch (e) {
      alert(e?.message || '一键平仓失败');
    } finally {
      if (btnCloseAll) {
        btnCloseAll.disabled = !window.getDashboardCurrentSymbol?.();
        if (old) btnCloseAll.textContent = old;
      }
    }
  });

  window.addEventListener('dashboard-kline-symbol', () => {
    syncQuickTradeSymbol();
    reconcileTpSlWithDefault();
  });

  window.addEventListener('dashboard-spot-price', (ev) => {
    const p = ev?.detail?.price;
    if (typeof p === 'number' && Number.isFinite(p) && p > 0) {
      _lastSpotPrice = p;
      /* 不更新限价委托价输入框，仅用于市价参考、最大可买等 */
      updateMarketPriceDisplay();
      syncQtyFromUsdt();
      refreshBalances();
    }
  });

  togglePriceBlock();
  if (slider) slider.style.setProperty('--qt-pct', '0%');
  if (sliderVis) sliderVis.style.setProperty('--qt-pct', '0%');
  if (pctNum) pctNum.textContent = '0';
  activeSide = 'buy';
  syncBracketFieldsVisibility();
  syncTabUI();
  syncQuickTradeSymbol();
  reconcileTpSlWithDefault();

  if (_balanceTimer) clearInterval(_balanceTimer);
  _balanceTimer = setInterval(() => {
    if (shouldPausePolling()) return;
    refreshBalances();
  }, 15000);

  inpAmt?.addEventListener('blur', () => {
    const q = parseNum(inpAmt?.value);
    if (Number.isFinite(q) && q > 0 && inpAmt) inpAmt.value = formatQty(q);
  });
})();
