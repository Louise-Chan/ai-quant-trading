const wizardTitle = document.getElementById('wizardTitle');
const stepIntro = document.getElementById('step-intro');
const stepPath = document.getElementById('step-path');
const stepInstall = document.getElementById('step-install');
const installPathInput = document.getElementById('installPath');
const pickBtn = document.getElementById('pickBtn');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const installBtn = document.getElementById('installBtn');
const cancelBtn = document.getElementById('cancelBtn');
const progressInner = document.getElementById('progressInner');
const progressText = document.getElementById('progressText');
const progressPercent = document.getElementById('progressPercent');
const message = document.getElementById('message');

let currentInstallDir = '';
let currentStep = 0;
let installing = false;

function setStep(step) {
  currentStep = step;
  stepIntro.classList.toggle('hidden', step !== 0);
  stepPath.classList.toggle('hidden', step !== 1);
  stepInstall.classList.toggle('hidden', step !== 2);

  if (step === 0) {
    wizardTitle.textContent = '欢迎使用 SilentSigma 安装程序';
    prevBtn.classList.add('hidden');
    nextBtn.classList.remove('hidden');
    installBtn.classList.add('hidden');
  } else if (step === 1) {
    wizardTitle.textContent = '选择安装路径';
    prevBtn.classList.remove('hidden');
    nextBtn.classList.add('hidden');
    installBtn.classList.remove('hidden');
  } else {
    wizardTitle.textContent = '正在安装';
    prevBtn.classList.add('hidden');
    nextBtn.classList.add('hidden');
    installBtn.classList.add('hidden');
  }
}

function setMessage(text, type = '') {
  message.textContent = text || '';
  message.className = `message ${type}`.trim();
}

function setProgress(value, stage) {
  const v = Math.max(0, Math.min(100, Number(value || 0)));
  progressInner.style.width = `${v}%`;
  progressPercent.textContent = `${v}%`;
  if (stage) progressText.textContent = stage;
}

function setInstallingState(isInstalling) {
  installing = isInstalling;
  installBtn.disabled = isInstalling;
  prevBtn.disabled = isInstalling;
  nextBtn.disabled = isInstalling;
  pickBtn.disabled = isInstalling;
  installPathInput.disabled = isInstalling;
  cancelBtn.textContent = isInstalling ? '取消安装' : '关闭';
}

async function bootstrap() {
  const defaultPath = await window.installerAPI.getDefaultPath();
  currentInstallDir = defaultPath;
  installPathInput.value = defaultPath;
}

pickBtn.addEventListener('click', async () => {
  const picked = await window.installerAPI.pickPath();
  if (picked) {
    currentInstallDir = picked;
    installPathInput.value = picked;
  }
});

installPathInput.addEventListener('change', () => {
  currentInstallDir = installPathInput.value.trim();
});

prevBtn.addEventListener('click', () => {
  if (currentStep === 1) setStep(0);
});

nextBtn.addEventListener('click', () => {
  if (currentStep === 0) setStep(1);
});

installBtn.addEventListener('click', async () => {
  currentInstallDir = installPathInput.value.trim();
  if (!currentInstallDir) {
    setMessage('请先输入安装路径。', 'warn');
    return;
  }
  setStep(2);
  setMessage('开始安装...', '');
  setInstallingState(true);
  setProgress(3, '正在初始化安装程序...');
  await window.installerAPI.startInstall(currentInstallDir);
});

cancelBtn.addEventListener('click', async () => {
  if (installing) {
    await window.installerAPI.cancelInstall();
    return;
  }
  await window.installerAPI.closeInstaller();
});

window.installerAPI.onProgress((payload) => {
  setProgress(payload?.value, payload?.stage);
});

window.installerAPI.onState((payload) => {
  const state = payload?.state;
  if (state === 'running') {
    setInstallingState(true);
    setMessage('正在安装核心组件，请稍候...', '');
  } else if (state === 'done') {
    setInstallingState(false);
    setMessage('安装成功，正在启动应用...', 'ok');
  } else if (state === 'cancelled') {
    setInstallingState(false);
    setMessage('安装已取消，正在关闭安装程序...', 'warn');
  } else if (state === 'error') {
    setInstallingState(false);
    setProgress(0, '安装失败');
    setMessage(payload?.message || '安装失败，请重试。', 'err');
    if (currentStep !== 1) setStep(1);
  }
});

bootstrap().catch((err) => {
  setMessage(String(err?.message || err), 'err');
});

setStep(0);
