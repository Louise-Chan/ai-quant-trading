' Double-click launcher for SilentSigma GUI installer
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)

Function FindLatestInstallerExe()
  distDir = scriptDir & "\dist-installer-gui"
  latestExe = ""
  latestDate = #1/1/2000#

  If FSO.FolderExists(distDir) Then
    Set folder = FSO.GetFolder(distDir)
    For Each f In folder.Files
      If LCase(FSO.GetExtensionName(f.Name)) = "exe" Then
        If InStr(1, f.Name, "SilentSigma-Installer-GUI-", vbTextCompare) = 1 Then
          If f.DateLastModified > latestDate Then
            latestDate = f.DateLastModified
            latestExe = f.Path
          End If
        End If
      End If
    Next
  End If

  FindLatestInstallerExe = latestExe
End Function

latestExe = FindLatestInstallerExe()
If latestExe <> "" Then
  answer = MsgBox("Rebuild GUI installer to apply latest UI/theme changes?" & vbCrLf & _
                  "Yes = rebuild then run, No = run existing EXE.", _
                  vbQuestion + vbYesNo, "SilentSigma Installer")
  If answer = vbYes Then
    cmd = "powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File """ & scriptDir & "\scripts\build-gui-installer.ps1"" -SkipCore -SkipPython -UseChinaMirror"
    WshShell.Run cmd, 1, True
    latestExe = FindLatestInstallerExe()
  End If
Else
  cmd = "powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File """ & scriptDir & "\scripts\build-gui-installer.ps1"" -UseChinaMirror"
  WshShell.Run cmd, 1, True
  latestExe = FindLatestInstallerExe()
End If

If latestExe = "" Then
  MsgBox "Installer EXE not found in dist-installer-gui after build.", vbExclamation, "SilentSigma Installer"
  WScript.Quit 1
End If

WshShell.Run """" & latestExe & """", 1, False
