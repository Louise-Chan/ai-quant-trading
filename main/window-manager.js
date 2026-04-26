const { app, BrowserWindow, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const config = require('./config');

let mainWindow = null;

function resolveWindowIcon() {
  const candidates = [
    // 开发态优先直接用根目录 Logo
    path.join(__dirname, '../SilentSigmaLogo.png'),
    // 构建时生成的 ico
    path.join(__dirname, '../build/icon.ico'),
    // 打包态资源目录（若存在）
    app.isPackaged ? path.join(process.resourcesPath, 'build/icon.ico') : '',
    app.isPackaged ? path.join(process.resourcesPath, 'SilentSigmaLogo.png') : '',
  ].filter(Boolean);

  for (const p of candidates) {
    if (fs.existsSync(p)) {
      const img = nativeImage.createFromPath(p);
      if (!img.isEmpty()) return img;
    }
  }
  return undefined;
}

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
    icon: resolveWindowIcon(),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      webSecurity: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, '../renderer/index-unified.html'));

  // 菜单栏已被移除（main.js 里 Menu.setApplicationMenu(null)），
  // 快捷键要在这里手动绑：F12 / Ctrl+Shift+I 打开开发者工具，Ctrl+R / Ctrl+Shift+R 刷新渲染器。
  // before-input-event 在顶层 webContents 上会捕获整个窗口（含所有子 iframe）的按键。
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown') return;
    const ctrl = input.control || input.meta;
    const shift = input.shift;
    const key = (input.key || '').toLowerCase();
    if (key === 'f12' || (ctrl && shift && key === 'i')) {
      mainWindow.webContents.toggleDevTools();
      event.preventDefault();
    } else if (ctrl && key === 'r') {
      if (shift) mainWindow.webContents.reloadIgnoringCache();
      else mainWindow.webContents.reload();
      event.preventDefault();
    }
  });

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
