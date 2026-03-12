const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  app: {
    minimize: () => ipcRenderer.invoke('app:minimize'),
    maximize: () => ipcRenderer.invoke('app:maximize'),
    close: () => ipcRenderer.invoke('app:close'),
    openMain: (token) => ipcRenderer.invoke('app:openMain', token),
    openAuth: () => ipcRenderer.invoke('app:openAuth'),
  },
  store: {
    get: (key) => ipcRenderer.invoke('store:get', key),
    set: (key, val) => ipcRenderer.invoke('store:set', key, val),
  },
});
