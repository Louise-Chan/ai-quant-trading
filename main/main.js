const { app, Menu } = require('electron');
const path = require('path');
const { registerIpcHandlers } = require('./ipc-handlers');
const { createMainWindow } = require('./window-manager');

function init() {
  Menu.setApplicationMenu(null);  // 移除 File/Edit/View/Window/Help 菜单栏
  registerIpcHandlers();
  createMainWindow();
}

app.whenReady().then(init);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  const { BrowserWindow } = require('electron');
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});
