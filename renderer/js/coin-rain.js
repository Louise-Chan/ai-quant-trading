/**
 * 金币雨背景动画
 * - 仅在欢迎页 / 登录页 / 注册页三个 view 激活时运行
 * - 主界面 (#view-main) 激活时自动停止以节省资源
 * - 金币：纯色圆盘，中央有货币符号形状的镂空（孔洞透出 canvas 背景）
 * - 仅下落 + 左右摆动（无旋转 / 无厚度），按 size 做远近层次 & 遮挡
 * - 低 CPU 占用：粒子复用，不创建新对象；requestAnimationFrame 节流
 */
(function () {
  const canvas = document.getElementById('coin-rain');
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext('2d');

  const coins = [];
  let width = 0;
  let height = 0;
  let dpr = Math.min(window.devicePixelRatio || 1, 2);
  let rafId = null;
  let running = false;

  function resize() {
    width = window.innerWidth;
    height = window.innerHeight;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // 金币放大 1.5× → 面积约 2.25×，同步降低目标数量避免画面过挤
    const target = Math.min(42, Math.max(16, Math.round((width * height) / 65000)));
    while (coins.length < target) coins.push(makeCoin(true));
    while (coins.length > target) coins.pop();
  }

  function makeCoin(spread) {
    return resetCoin({}, spread);
  }

  const SIZE_MIN = 24;   // 整体 ×1.5
  const SIZE_MAX = 72;

  // 金币中央镂空的货币符号（随机分配一个到每枚金币）
  const GLYPHS = ['$', '€', '¥', '£', '₿', 'Ξ', '₮', '₩', '₹', '¢'];

  // 纯色币安黄
  const COIN_COLOR = '#F0B90B';

  function resetCoin(coin, spread) {
    // 幂分布：pow > 1 偏向小值，让远景（小金币）占多数
    const r = Math.pow(Math.random(), 1.6);
    coin.size = SIZE_MIN + r * (SIZE_MAX - SIZE_MIN);
    // 归一化的深度系数（0=远/小，1=近/大）
    const depth = (coin.size - SIZE_MIN) / (SIZE_MAX - SIZE_MIN);
    coin.depth = depth;

    coin.x = Math.random() * width;
    coin.y = spread ? Math.random() * height : -coin.size * 2 - Math.random() * height * 0.3;

    // 近大远小 → 近快远慢：大金币下落快、小金币慢（视觉上更"远"）
    // 近点的金币速度上限降下来，避免"砸下来"的感觉
    coin.vy = 0.35 + depth * 1.1 + Math.random() * 0.3;
    coin._baseVy = coin.vy;   // 记录基础下落速度，方便吸收结束后平滑回归
    coin.vx = 0;              // 水平速度（用于磁石吸收阶段）

    coin.wobbleSeed = Math.random() * Math.PI * 2;
    coin.wobbleAmp = 4 + depth * 22;
    coin.wobbleFreq = 0.0004 + Math.random() * 0.0008;

    // 近实远淡：小金币更透明，模拟大气透视
    coin.alpha = 0.5 + depth * 0.5;

    // 随机一个货币符号
    coin.glyph = GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
    return coin;
  }

  // ===================================================================
  // 磁石吸收 + 卡片充能动画协调
  //   节奏：每个周期 = CHARGE_DURATION 吸收 + CHARGE_REST 休息
  //   吸收阶段：金币朝卡片中心加速飞入，距离越近/时间越晚 吸力越大
  //   同时给 active 卡片加 .card-charging 类，触发 CSS 震动+放大+金边
  // ===================================================================
  const CHARGE_DURATION = 3000;   // 每次吸收动画 3s
  const CHARGE_REST = 5000;       // 两次吸收之间间隔 5s
  let chargeAnchor = null;        // 首个周期的起点（performance.now()），null = 未初始化
  let wasCharging = false;
  let cardEl = null;
  let cardCx = 0, cardCy = 0, cardR = 0;
  let cardTick = 0;

  function getActiveCard() {
    const v = document.querySelector('.view.active');
    if (!v) return null;
    return v.querySelector('.welcome-card, .auth-card');
  }

  function refreshCardGeom() {
    cardEl = getActiveCard();
    if (!cardEl) { cardCx = cardCy = 0; cardR = 0; return; }
    const r = cardEl.getBoundingClientRect();
    cardCx = r.left + r.width / 2;
    cardCy = r.top + r.height / 2;
    // 用短边作为"被吸收判定"半径的基础，比整体外接圆更贴合视觉
    cardR = Math.min(r.width, r.height) / 2;
  }

  /** 触发一次卡片充能动画（重启 CSS animation） */
  function triggerCardCharge(el) {
    if (!el) return;
    el.classList.remove('card-charging');
    // 强制 reflow，确保下一次 add 能重新跑完整动画
    void el.offsetWidth;
    el.classList.add('card-charging');
  }

  function drawCoin(coin, t) {
    const wx = coin.x + Math.sin(t * coin.wobbleFreq + coin.wobbleSeed) * coin.wobbleAmp;

    ctx.save();
    ctx.globalAlpha = coin.alpha;
    ctx.translate(wx, coin.y);

    // 阴影让金币浮在白底上
    ctx.shadowColor = 'rgba(170, 115, 0, 0.25)';
    ctx.shadowBlur = coin.size * 0.8;
    ctx.shadowOffsetY = coin.size * 0.22;

    // === 纯色实心圆（平面金币） ===
    ctx.fillStyle = COIN_COLOR;
    ctx.beginPath();
    ctx.arc(0, 0, coin.size, 0, Math.PI * 2);
    ctx.fill();

    // 关闭阴影，避免随后抠孔操作被阴影干扰
    ctx.shadowBlur = 0;
    ctx.shadowOffsetY = 0;

    // === 镂空中央货币符号：destination-out 擦除金币对应区域，
    //     露出 canvas 透明 → 能看到 body 背景色（白底+极淡金色光晕） ===
    ctx.globalCompositeOperation = 'destination-out';
    ctx.fillStyle = '#000';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    // 符号大小约为金币直径的 65%
    const glyphSize = coin.size * 1.3;
    ctx.font = `700 ${glyphSize}px "Inter", "SF Pro Display", "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif`;
    // 轻微下移修正：基线视觉上略高于几何中心
    ctx.fillText(coin.glyph, 0, coin.size * 0.02);

    // 恢复合成模式
    ctx.globalCompositeOperation = 'source-over';

    ctx.restore();
  }

  function step(t) {
    if (!running) return;
    ctx.clearRect(0, 0, width, height);

    // 每 10 帧刷新一次卡片几何（getBoundingClientRect 不强制 reflow，但仍节流一下）
    if (cardTick++ % 10 === 0) refreshCardGeom();

    // 周期判定：先休息 CHARGE_REST，再吸收 CHARGE_DURATION，如此往复
    if (chargeAnchor === null) chargeAnchor = t + CHARGE_REST;
    let charging = false;
    let cp = 0;  // charging progress 0~1
    if (cardEl && t >= chargeAnchor) {
      const elapsed = t - chargeAnchor;
      const cycle = CHARGE_DURATION + CHARGE_REST;
      const pos = elapsed % cycle;
      if (pos < CHARGE_DURATION) {
        charging = true;
        cp = pos / CHARGE_DURATION;
      }
    }

    // 充能态跳变：开始时 → 加 class 触发 CSS 动画；结束时 → 移除 class
    if (charging !== wasCharging) {
      if (charging) {
        triggerCardCharge(cardEl);
      } else if (cardEl) {
        cardEl.classList.remove('card-charging');
      }
      wasCharging = charging;
    }

    for (let i = 0; i < coins.length; i++) {
      const c = coins[i];

      if (charging && cardEl) {
        const dx = cardCx - c.x;
        const dy = cardCy - c.y;
        const dist = Math.hypot(dx, dy) || 1;
        const nx = dx / dist;
        const ny = dy / dist;

        // 吸力 = 基础（随时间推进变强）+ 近距离加成
        //   cp=0  时基础 ≈ 0.08，几乎不动
        //   cp=1  时基础 ≈ 0.55，加近距离加成 → 越吸越快
        const diag = Math.hypot(width, height);
        const distFactor = Math.max(0, 1 - dist / diag);
        const pull = 0.08 + cp * 0.5 + distFactor * (0.4 + cp * 1.4);

        c.vx += nx * pull;
        c.vy += ny * pull;

        // 进入卡片范围内 → 被吸收，重生在屏幕顶部
        if (dist < cardR * 0.55) {
          resetCoin(c, false);
          continue;
        }
      } else {
        // 非吸收期：水平速度阻尼，垂直速度平滑回归基础下落速度
        c.vx *= 0.85;
        c.vy = c.vy * 0.88 + c._baseVy * 0.12;
      }

      c.x += c.vx;
      c.y += c.vy;

      // 出界重置（下方/左右远离视口都视为消耗）
      if (c.y - c.size > height) resetCoin(c, false);
      else if (c.x < -c.size * 3 || c.x > width + c.size * 3) resetCoin(c, false);
    }

    // 按 size 升序：小（远）先画 → 大（近）后画，大金币自然遮挡小金币
    coins.sort((a, b) => a.size - b.size);
    for (let i = 0; i < coins.length; i++) {
      drawCoin(coins[i], t);
    }
    rafId = requestAnimationFrame(step);
  }

  function start() {
    if (running) return;
    running = true;
    if (!width || !height) resize();
    rafId = requestAnimationFrame(step);
  }

  function stop() {
    running = false;
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
    ctx.clearRect(0, 0, width, height);
    // 清理充能状态，避免切回来时残留类名 / 周期错乱
    if (cardEl) cardEl.classList.remove('card-charging');
    chargeAnchor = null;
    wasCharging = false;
    cardEl = null;
  }

  /** 根据当前 active view 判断是否应该播放动画 */
  function isDecorativeViewActive() {
    const active = document.querySelector('.view.active');
    if (!active) return false;
    const id = active.id;
    return id === 'view-welcome' || id === 'view-auth-login' || id === 'view-auth-register';
  }

  function sync() {
    if (document.hidden) {
      stop();
      return;
    }
    if (isDecorativeViewActive()) start();
    else stop();
  }

  /** 监听 view 切换：.view.active 的增/减会触发 class 变化 */
  const observer = new MutationObserver(() => {
    sync();
  });
  document.querySelectorAll('.view').forEach((v) => {
    observer.observe(v, { attributes: true, attributeFilter: ['class'] });
  });

  window.addEventListener('resize', () => {
    if (!running) return;
    resize();
  });
  document.addEventListener('visibilitychange', sync);

  /* 首次初始化：等 DOM ready */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      resize();
      sync();
    });
  } else {
    resize();
    sync();
  }

  /* 暴露给外部：方便调试 */
  window.__coinRain = { start, stop, resize, sync };
})();
