const { app, BrowserWindow } = require('electron');
const path = require('path');
const config = require('./config');

let mainWindow = null;

function getMainWindow() {
  return mainWindow;
}

function createMainWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
    mainWindow.focus();
    return mainWindow;
  }
  const { width, height, minWidth, minHeight } = config.windows.main;
  const isWinOrLinux = process.platform === 'win32' || process.platform === 'linux';
  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth: minWidth || 1280,
    minHeight: minHeight || 800,
    title: '',  // 不显示窗口标题
    titleBarStyle: 'hidden',  // 隐藏默认标题栏（含图标和文字）
    ...(isWinOrLinux ? {
      titleBarOverlay: {
        color: '#ffffff',      // 白色背景
        symbolColor: '#333333', // 控制按钮图标颜色
      },
    } : {}),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      webSecurity: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, '../renderer/index-unified.html'));
  mainWindow.on('closed', () => {
    mainWindow = null;
    if (process.platform !== 'darwin') app.quit();
  });
  return mainWindow;
}

module.exports = {
  createMainWindow,
  getMainWindow,
};
