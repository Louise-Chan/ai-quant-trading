const { app, BrowserWindow, ipcMain, dialog, shell, nativeImage } = require('electron');
const path = require('path');
const { spawn, exec } = require('child_process');
const fs = require('fs');

let win = null;
let installerProcess = null;
let fakeProgressTimer = null;
let cancelRequested = false;

function resolveInstallerIcon() {
  const candidates = [
    // 开发态
    path.join(__dirname, 'icon.ico'),
    path.join(__dirname, 'SilentSigmaLogo.png'),
    // 打包态（asar 外资源路径）
    app.isPackaged ? path.join(process.resourcesPath, 'installer_gui/icon.ico') : '',
    app.isPackaged ? path.join(process.resourcesPath, 'installer_gui/SilentSigmaLogo.png') : '',
    app.isPackaged ? path.join(process.resourcesPath, 'icon.ico') : '',
  ].filter(Boolean);

  for (const p of candidates) {
    if (fs.existsSync(p)) {
      const img = nativeImage.createFromPath(p);
      if (!img.isEmpty()) return img;
    }
  }
  return undefined;
}

function getPayloadInstallerPath() {
  return path.join(process.resourcesPath, 'payload', 'SilentSigma-Core-Setup.exe');
}

function getDefaultInstallDir() {
  return path.join(process.env.LOCALAPPDATA || app.getPath('home'), 'Programs', 'SilentSigma');
}

function createWindow() {
  win = new BrowserWindow({
    width: 980,
    height: 640,
    minWidth: 900,
    minHeight: 580,
    title: 'SilentSigma 安装程序',
    autoHideMenuBar: true,
    backgroundColor: '#0f172a',
    icon: resolveInstallerIcon(),
    webPreferences: {
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  win.loadFile(path.join(__dirname, 'index.html'));
}

function sendToRenderer(channel, payload) {
  if (win && !win.isDestroyed()) {
    win.webContents.send(channel, payload);
  }
}

function startFakeProgress() {
  let value = 8;
  sendToRenderer('install:progress', { value, stage: '准备安装环境...' });
  clearInterval(fakeProgressTimer);
  fakeProgressTimer = setInterval(() => {
    value += value < 65 ? 5 : (value < 85 ? 2 : 1);
    if (value > 95) value = 95;
    sendToRenderer('install:progress', { value, stage: '正在安装，请稍候...' });
  }, 500);
}

function stopFakeProgress() {
  clearInterval(fakeProgressTimer);
  fakeProgressTimer = null;
}

function getInstalledAppExe(installDir) {
  if (!installDir) return '';
  return path.join(path.resolve(installDir), 'SilentSigma.exe');
}

function killInstallerProcessTree() {
  return new Promise((resolve) => {
    if (!installerProcess || !installerProcess.pid) {
      resolve();
      return;
    }
    const pid = installerProcess.pid;
    exec(`taskkill /pid ${pid} /T /F`, { windowsHide: true }, () => resolve());
  });
}

async function runCoreInstaller(installDir) {
  const setupExe = getPayloadInstallerPath();
  if (!fs.existsSync(setupExe)) {
    throw new Error(`未找到核心安装包: ${setupExe}`);
  }

  if (installerProcess) {
    throw new Error('已有安装任务正在运行');
  }
  cancelRequested = false;

  const normalizedInstallDir = path.resolve(installDir).replace(/[\\/]+$/, '');
  const args = ['/S', `/D=${normalizedInstallDir}`];

  return await new Promise((resolve, reject) => {
    try {
      installerProcess = spawn(setupExe, args, {
        windowsHide: true,
        detached: false,
        stdio: 'ignore',
      });
    } catch (err) {
      installerProcess = null;
      reject(err);
      return;
    }

    installerProcess.once('error', (err) => {
      installerProcess = null;
      reject(err);
    });

    installerProcess.once('exit', (code) => {
      installerProcess = null;
      if (code === 0) resolve();
      else reject(new Error(`安装失败，退出码 ${code}`));
    });
  });
}

ipcMain.handle('install:getDefaultPath', () => getDefaultInstallDir());

ipcMain.handle('install:pickPath', async () => {
  const result = await dialog.showOpenDialog(win, {
    title: '选择安装目录',
    properties: ['openDirectory', 'createDirectory'],
    defaultPath: getDefaultInstallDir(),
  });
  if (result.canceled || !result.filePaths?.length) return null;
  return result.filePaths[0];
});

ipcMain.handle('install:start', async (_evt, installDir) => {
  try {
    if (!installDir || typeof installDir !== 'string') {
      throw new Error('安装路径无效');
    }
    sendToRenderer('install:state', { state: 'running' });
    startFakeProgress();
    await runCoreInstaller(installDir);
    stopFakeProgress();
    const appExe = getInstalledAppExe(installDir);
    sendToRenderer('install:progress', { value: 100, stage: '安装完成' });
    sendToRenderer('install:state', { state: 'done', installDir });
    if (appExe && fs.existsSync(appExe)) {
      shell.openPath(appExe);
    }
    // 安装完成后自动关闭安装器页面
    setTimeout(() => app.quit(), 800);
    return { ok: true };
  } catch (err) {
    stopFakeProgress();
    if (cancelRequested) {
      sendToRenderer('install:state', { state: 'cancelled' });
      setTimeout(() => app.quit(), 200);
      return { ok: false, cancelled: true };
    }
    sendToRenderer('install:state', { state: 'error', message: String(err?.message || err) });
    return { ok: false, message: String(err?.message || err) };
  }
});

ipcMain.handle('install:cancel', async () => {
  cancelRequested = true;
  stopFakeProgress();
  await killInstallerProcessTree();
  sendToRenderer('install:state', { state: 'cancelled' });
  setTimeout(() => app.quit(), 100);
  return { ok: true };
});

ipcMain.handle('install:close', async () => {
  cancelRequested = true;
  await killInstallerProcessTree();
  app.quit();
});

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
