SilentSigma  -  build/  目录
============================

此目录是 electron-builder 的 `buildResources`，存放打包阶段才会用到的资产。

可放置（可选）：
  - icon.ico          应用 / 安装包图标（建议 256x256 多尺寸 ICO；缺失时使用 Electron 默认图标）
  - background.bmp    NSIS 安装向导左侧 164x314 BMP 背景图
  - installerHeader.bmp  顶部 150x57 BMP 横幅

已存在：
  - installer.nsh     注入到生成 NSIS 脚本里的自定义片段
                      （写入卸载注册项、可选钩子等）

打包后这些文件本身不会进入安装包；仅在制作安装包时被 electron-builder 引用。
