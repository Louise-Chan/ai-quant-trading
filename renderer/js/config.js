/** 后端 API 地址，gate-v2 默认 8081 */
(function() {
  if (window.API_BASE) return;
  try {
    if (window.parent && window.parent !== window && window.parent.API_BASE) {
      window.API_BASE = window.parent.API_BASE;
      return;
    }
  } catch (_) { /* file:// 下跨 frame 访问可能被阻止 */ }
  window.API_BASE = 'http://127.0.0.1:8081/api/v1';
})();
