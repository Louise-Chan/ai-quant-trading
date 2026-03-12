/** 欢迎页逻辑 */
document.getElementById('btn-login').addEventListener('click', () => {
  if (window.electronAPI?.app?.openAuth) {
    window.electronAPI.app.openAuth();
  } else {
    window.location.href = 'auth.html';
  }
});

document.getElementById('btn-register').addEventListener('click', () => {
  if (window.electronAPI?.app?.openAuth) {
    window.electronAPI.app.openAuth();
  } else {
    window.location.href = 'auth.html';
  }
});
