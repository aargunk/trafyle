; Trafyle kurulum dosyası (Inno Setup 6). windows\build.bat tarafından derlenir.
#define AppName "Trafyle"
#define AppVersion "3.4.0"

[Setup]
AppId={{6F1C2B9E-4D3A-4E8B-9B7A-5E2C1D0F8A41}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Trafyle-Kurulum
SetupIconFile=..\assets\AppIcon.ico
UninstallDisplayIcon={app}\Trafyle.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne kısayol ekle"; GroupDescription: "Kısayollar:"

[Files]
Source: "..\dist\Trafyle\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Trafyle.exe"; AppUserModelID: "Trafyle.App"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Trafyle.exe"; Tasks: desktopicon; AppUserModelID: "Trafyle.App"

[Run]
Filename: "{app}\Trafyle.exe"; Description: "Trafyle'ı şimdi aç"; Flags: nowait postinstall skipifsilent
