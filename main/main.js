const { app, Menu } = require('electron');
const path = require('path');
const { registerIpcHandlers } = require('./ipc-handlers');
const { createMainWindow } = require('./window-manager');
const { ensureBackendReady, stopBackend } = require('./backend-launcher');

async function init() {
  Menu.setApplicationMenu(null);  // 移除 File/Edit/View/Window/Help 菜单栏
  registerIpcHandlers();

  // 打包态：自动启动内置 Python 后端并等待健康检查通过；
  // 开发态：若已检测到端口可用则复用，否则跳过（用 run.bat 手动启动）。
  await ensureBackendReady();

  createMainWindow();
}

app.whenReady().then(init);

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopBackend();
});

app.on('activate', () => {
  const { BrowserWindow } = require('electron');
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});
