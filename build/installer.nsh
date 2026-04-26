; ===========================================================================
;  SilentSigma 安装程序自定义片段（被 electron-builder 注入到生成的 NSIS 脚本）。
;  这里主要做两件事：
;    - 卸载时清理用户数据（默认保留，仅当用户在卸载向导里选择删除时才动手）；
;    - 安装结束页面允许用户勾选"立即运行 SilentSigma"。
;  electron-builder 已自动处理：自定义路径选择、桌面/开始菜单快捷方式、中英双语等。
; ===========================================================================

!macro customInstall
  ; 把 productName 写入卸载注册表的 DisplayName
  WriteRegStr HKCU "Software\SilentSigma" "InstallPath" "$INSTDIR"
!macroend

!macro customUnInstall
  ; 默认保留 %APPDATA%\SilentSigma\data 下的数据库与日志，
  ; 卸载向导里 deleteAppDataOnUninstall=false 已限制，不在这里强删。
  DeleteRegKey HKCU "Software\SilentSigma"
!macroend
