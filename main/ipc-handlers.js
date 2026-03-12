const { ipcMain } = require('electron');
const { getMainWindow } = require('./window-manager');

function registerIpcHandlers() {
  ipcMain.handle('app:minimize', () => {
    const win = getMainWindow();
    if (win && !win.isDestroyed()) win.minimize();
  });

  ipcMain.handle('app:maximize', () => {
    const win = getMainWindow();
    if (win && !win.isDestroyed()) win.isMaximized() ? win.unmaximize() : win.maximize();
  });

  ipcMain.handle('app:close', () => {
    const win = getMainWindow();
    if (win && !win.isDestroyed()) win.close();
  });

  ipcMain.handle('app:openMain', () => {});
  ipcMain.handle('app:openAuth', () => {});

  const store = {};
  ipcMain.handle('store:get', (e, key) => store[key] ?? null);
  ipcMain.handle('store:set', (e, key, val) => { store[key] = val; });
}

module.exports = { registerIpcHandlers };
