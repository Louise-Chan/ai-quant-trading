const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('installerAPI', {
  getDefaultPath: () => ipcRenderer.invoke('install:getDefaultPath'),
  pickPath: () => ipcRenderer.invoke('install:pickPath'),
  startInstall: (installDir) => ipcRenderer.invoke('install:start', installDir),
  cancelInstall: () => ipcRenderer.invoke('install:cancel'),
  closeInstaller: () => ipcRenderer.invoke('install:close'),
  onState: (handler) => ipcRenderer.on('install:state', (_evt, payload) => handler(payload)),
  onProgress: (handler) => ipcRenderer.on('install:progress', (_evt, payload) => handler(payload)),
});
