; ============================================================
;  SectorLoom Telemetry Agent — Windows installer
;
;  Built by .github/workflows/build-agent.yml on a Windows
;  runner, after PyInstaller has produced SectorLoomAgent.exe.
;  It can also be compiled on Linux with makensis, which is how
;  it is checked before it ever reaches a Windows machine.
;
;    makensis -DVERSION=1.0.0 -DAGENT_EXE=../dist/SectorLoomAgent.exe \
;             installer/sectorloom.nsi
;
;  Deliberately a PER-USER install: it writes only to the
;  person's own AppData and HKEY_CURRENT_USER, so Windows never
;  shows a "Do you want to allow this app to make changes"
;  prompt. One fewer scary dialog on a program that is already
;  going to trip SmartScreen.
; ============================================================

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef AGENT_EXE
  !define AGENT_EXE "..\dist\SectorLoomAgent.exe"
!endif
!ifndef OUTFILE
  !define OUTFILE "SectorLoomSetup.exe"
!endif

!define APPNAME     "SectorLoom Telemetry Agent"
!define SHORTNAME   "SectorLoom Agent"
!define PUBLISHER   "SectorLoom"
!define EXENAME     "SectorLoomAgent.exe"
!define UNINSTKEY   "Software\Microsoft\Windows\CurrentVersion\Uninstall\SectorLoomAgent"
!define RUNKEY      "Software\Microsoft\Windows\CurrentVersion\Run"
; the agent's own "Start with Windows" switch reads and writes this
; exact value name (sectorloom_agent/startup.py), so the installer must
; use it too or the two will disagree about whether it is on
!define RUNVALUE    "SectorLoomTelemetryAgent"
!define OLDRUNVALUE "LapwiseTelemetryAgent"

Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\SectorLoom"
InstallDirRegKey HKCU "${UNINSTKEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails hide
ShowUninstDetails hide

; Version information. An executable with none of this looks far more
; suspect to both Windows and the person reading the SmartScreen box.
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName"     "${APPNAME}"
VIAddVersionKey "CompanyName"     "${PUBLISHER}"
VIAddVersionKey "FileDescription" "Installer for the SectorLoom telemetry agent"
VIAddVersionKey "FileVersion"     "${VERSION}"
VIAddVersionKey "ProductVersion"  "${VERSION}"
VIAddVersionKey "LegalCopyright"  "SectorLoom"

!define MUI_ICON   "sectorloom.ico"
!define MUI_UNICON "sectorloom.ico"
!define MUI_ABORTWARNING

; No welcome page and no component chooser: there is one thing to
; install and nothing to decide. Clicking the download should start the
; install, not open a wizard.
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXENAME}"
!define MUI_FINISHPAGE_RUN_TEXT "Start the SectorLoom agent now"
!define MUI_FINISHPAGE_TEXT "The agent is installed and will start with Windows from now on.$\r$\n$\r$\nSign in with your SectorLoom email and password in the window that opens, tick the sims you race, and you are done. You can turn off starting with Windows in that same window."
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"


; ---------------------------------------------------------------
;  Shut the agent down before touching its files. Upgrading over a
;  running copy fails on a locked file, and the failure arrives as
;  an unhelpful "cannot write" box.
; ---------------------------------------------------------------
!macro StopAgent
  DetailPrint "Closing the agent if it is running..."
  nsExec::Exec 'taskkill /F /IM "${EXENAME}"'
  Pop $0
  Sleep 700
!macroend


Section "Install"
  SetShellVarContext current

  ; An older install somewhere else leaves a second copy behind and two
  ; entries in Add/Remove Programs, so clear it out first.
  ReadRegStr $0 HKCU "${UNINSTKEY}" "InstallLocation"
  ${If} $0 != ""
  ${AndIf} $0 != "$INSTDIR"
  ${AndIf} ${FileExists} "$0\Uninstall.exe"
    DetailPrint "Removing the previous installation in $0..."
    ExecWait '"$0\Uninstall.exe" /S _?=$0'
    Delete "$0\Uninstall.exe"
    RMDir /r "$0"
  ${EndIf}

  !insertmacro StopAgent

  SetOutPath "$INSTDIR"
  File "/oname=${EXENAME}" "${AGENT_EXE}"
  File "/oname=sectorloom.ico" "sectorloom.ico"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateShortCut "$SMPROGRAMS\${SHORTNAME}.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\sectorloom.ico"

  ; Start with Windows, on by default — the whole point is that it is
  ; watching while you race without being asked to. The agent's own
  ; settings window turns it back off.
  DeleteRegValue HKCU "${RUNKEY}" "${OLDRUNVALUE}"
  WriteRegStr HKCU "${RUNKEY}" "${RUNVALUE}" '"$INSTDIR\${EXENAME}"'

  ; Add/Remove Programs
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayName"     "${APPNAME}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKCU "${UNINSTKEY}" "Publisher"       "${PUBLISHER}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayIcon"     "$INSTDIR\sectorloom.ico"
  WriteRegStr   HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr   HKCU "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" "$0"
SectionEnd


Section "Uninstall"
  SetShellVarContext current

  !insertmacro StopAgent

  DeleteRegValue HKCU "${RUNKEY}" "${RUNVALUE}"
  DeleteRegValue HKCU "${RUNKEY}" "${OLDRUNVALUE}"
  DeleteRegKey   HKCU "${UNINSTKEY}"

  Delete "$SMPROGRAMS\${SHORTNAME}.lnk"
  Delete "$INSTDIR\${EXENAME}"
  Delete "$INSTDIR\sectorloom.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  ; %APPDATA%\SectorLoom\agent.json is deliberately left alone. It holds
  ; the sign-in token and the folder settings, so reinstalling does not
  ; mean setting it all up again. Nothing in it is telemetry.
SectionEnd
