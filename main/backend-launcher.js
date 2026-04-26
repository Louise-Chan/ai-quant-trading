/**
 * 打包态下负责拉起 Python 后端：
 *   - 优先使用资源目录里的 python_runtime/python.exe（便携 Python）。
 *   - 把数据库等可写产物落到 %LOCALAPPDATA%\SilentSigma\data，避免 Program Files 只读问题。
 *   - 启动后轮询 /api/v1/health，最多等 60s 再创建主窗口。
 *   - 应用退出时杀掉子进程。
 */
const { app } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const BACKEND_PORT = 8081;
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/api/v1/health`;

let backendProcess = null;

function getResourcePath(...segments) {
  // 打包后 process.resourcesPath = <安装目录>/resources
  // 开发态则相对项目根目录
  const base = app.isPackaged
    ? process.resourcesPath
    : path.join(__dirname, '..');
  return path.join(base, ...segments);
}

function getDataDir() {
  // 用户可写：%APPDATA%/SilentSigma 或 %LOCALAPPDATA%/SilentSigma/data
  const userData = app.getPath('userData'); // 自动包含 productName
  const dir = path.join(userData, 'data');
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch (e) {
    // ignore
  }
  return dir;
}

function pickPython() {
  const bundled = getResourcePath('python_runtime', 'python.exe');
  if (fs.existsSync(bundled)) return bundled;
  // 开发态回退到系统 python（仅用于 npm start 时验证）
  return process.platform === 'win32' ? 'python' : 'python3';
}

function checkHealth() {
  return new Promise((resolve) => {
    const req = http.get(HEALTH_URL, { timeout: 1500 }, (res) => {
      const ok = res.statusCode === 200;
      res.resume();
      resolve(ok);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend(maxSeconds = 60) {
  for (let i = 0; i < maxSeconds; i++) {
    if (await checkHealth()) return true;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

function startBackend() {
  if (backendProcess) return backendProcess;

  const pythonExe = pickPython();
  const backendDir = getResourcePath('backend');

  if (!fs.existsSync(path.join(backendDir, 'main.py'))) {
    console.error('[backend-launcher] backend/main.py not found at', backendDir);
    return null;
  }

  const env = {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUNBUFFERED: '1',
    SILENTSIGMA_DATA_DIR: getDataDir(),
  };

  backendProcess = spawn(pythonExe, ['main.py'], {
    cwd: backendDir,
    env,
    stdio: 'pipe',
    windowsHide: true,
  });

  backendProcess.stdout.on('data', (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });
  backendProcess.stderr.on('data', (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });
  backendProcess.on('exit', (code, signal) => {
    console.log(`[backend-launcher] backend exited code=${code} signal=${signal}`);
    backendProcess = null;
  });
  backendProcess.on('error', (err) => {
    console.error('[backend-launcher] failed to start backend:', err);
  });

  return backendProcess;
}

function stopBackend() {
  if (!backendProcess) return;
  try {
    if (process.platform === 'win32') {
      // taskkill 树状结束，避免 uvicorn reloader 残留
      const { execSync } = require('child_process');
      try {
        execSync(`taskkill /pid ${backendProcess.pid} /T /F`, { windowsHide: true, stdio: 'ignore' });
      } catch (_) {
        backendProcess.kill();
      }
    } else {
      backendProcess.kill('SIGTERM');
    }
  } catch (e) {
    console.error('[backend-launcher] stop error:', e);
  }
  backendProcess = null;
}

async function ensureBackendReady() {
  // 已经有人在跑（比如开发时手动 run.bat），直接复用
  if (await checkHealth()) {
    console.log('[backend-launcher] backend already running, reuse it.');
    return true;
  }
  // 开发态默认不自动拉起，避免和 run.bat 抢端口
  if (!app.isPackaged) {
    console.log('[backend-launcher] dev mode: backend not running, please start it manually (run.bat).');
    return false;
  }
  console.log('[backend-launcher] starting bundled backend...');
  startBackend();
  const ready = await waitForBackend(60);
  if (!ready) {
    console.error('[backend-launcher] backend health check timed out (60s).');
  }
  return ready;
}

module.exports = {
  ensureBackendReady,
  stopBackend,
  startBackend,
  checkHealth,
};
