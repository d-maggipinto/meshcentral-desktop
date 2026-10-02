; SPDX-License-Identifier: Apache-2.0
; Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
; Inno Setup script: dist\MeshCentralDesktop (PyInstaller folder) -> dist\MeshCentralDesktop-<ver>-setup.exe
; Build: ISCC /DAppVersion=X.Y.Z packaging\windows\installer.iss
#ifndef AppVersion
  #error Pass /DAppVersion=X.Y.Z
#endif

[Setup]
; never change AppId: Windows uses it to find the installed copy for upgrades and uninstall
AppId={{47DEDF0F-F69B-49E1-92F1-1F6D12B5A067}
AppName=MeshCentral Desktop
AppVersion={#AppVersion}
AppVerName=MeshCentral Desktop {#AppVersion}
AppPublisher=CYVELION LTD
AppPublisherURL=https://github.com/d-maggipinto/meshcentral-desktop
AppSupportURL=https://github.com/d-maggipinto/meshcentral-desktop/issues
VersionInfoVersion={#AppVersion}
VersionInfoCompany=CYVELION LTD
DefaultDirName={autopf}\MeshCentral Desktop
DefaultGroupName=MeshCentral Desktop
DisableProgramGroupPage=yes
; per-user install by default (no administrator needed); the user can choose "all users"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\..\dist
OutputBaseFilename=MeshCentralDesktop-{#AppVersion}-setup
SetupIconFile=..\..\build\meshcentral-desktop.ico
UninstallDisplayIcon={app}\MeshCentralDesktop.exe
UninstallDisplayName=MeshCentral Desktop
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; the running app holds this mutex (osdep.acquire_single_instance): setup asks to close it first
AppMutex=uk.co.cyvelion.MeshCentralDesktop
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\MeshCentralDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MeshCentral Desktop"; Filename: "{app}\MeshCentralDesktop.exe"; AppUserModelID: "CYVELION.MeshCentralDesktop"
Name: "{autodesktop}\MeshCentral Desktop"; Filename: "{app}\MeshCentralDesktop.exe"; Tasks: desktopicon; AppUserModelID: "CYVELION.MeshCentralDesktop"

[Run]
Filename: "{app}\MeshCentralDesktop.exe"; Description: "{cm:LaunchProgram,MeshCentral Desktop}"; Flags: nowait postinstall skipifsilent

[Code]
// Edge WebView2 Runtime (remote desktop, terminal, chat): part of Windows 11 and current Windows 10.
function WebView2Installed(): Boolean;
var v: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0')
    or RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WizardSilent() and not WebView2Installed() then
    MsgBox('The Microsoft Edge WebView2 Runtime was not found. The remote desktop, terminal and chat need it.' + #13#10 +
           'Download it from https://developer.microsoft.com/microsoft-edge/webview2/ (Evergreen Runtime).',
           mbInformation, MB_OK);
end;
