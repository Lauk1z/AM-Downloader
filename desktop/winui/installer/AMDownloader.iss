#ifndef PackageDir
  #error PackageDir must point to a verified WinUI package.
#endif
#ifndef ReleaseVersion
  #error ReleaseVersion is required.
#endif

[Setup]
AppId=AMDownloader.WinUI
AppName=AM Downloader (WinUI 3 Preview)
AppVersion={#ReleaseVersion}
AppPublisher=Lauk1z
AppPublisherURL=https://github.com/Lauk1z/AM-Downloader
AppSupportURL=https://github.com/Lauk1z/AM-Downloader/issues
AppUpdatesURL=https://github.com/Lauk1z/AM-Downloader/releases
DefaultDirName={localappdata}\Programs\AM Downloader
DefaultGroupName=AM Downloader
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.19041
DisableProgramGroupPage=yes
WizardStyle=modern dark
SetupIconFile={#PackageDir}\Assets\app.ico
UninstallDisplayIcon={app}\AM Downloader WinUI.exe
LicenseFile={#PackageDir}\LICENSE.txt
OutputDir={#InstallerOutput}
OutputBaseFilename=AM-Downloader-{#ReleaseVersion}-WinUI3-Windows-x64-Setup
VersionInfoVersion={#NumericVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#ReleaseVersion}
Compression=lzma2/normal
SolidCompression=yes
CloseApplications=no
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AM Downloader"; Filename: "{app}\AM Downloader WinUI.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\AM Downloader (WinUI)"; Filename: "{app}\AM Downloader WinUI.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AM Downloader WinUI.exe"; Description: "{cm:LaunchProgram,AM Downloader}"; Flags: nowait postinstall skipifsilent
