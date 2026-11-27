; Inno Setup script -> GeoLens-Setup.exe (installs the whole folder + shortcuts)
#define AppVer GetEnv("GEOLENS_VERSION")
#if AppVer == ""
  #define AppVer "1.0.0"
#endif
[Setup]
AppId={{6B1E2C3A-9F4D-4C7B-A1E2-0E5F3D9C7A11}
AppName=GeoLens
AppVersion={#AppVer}
AppPublisher=unseen
DefaultDirName={localappdata}\Programs\GeoLens
DefaultGroupName=GeoLens
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=GeoLens-Setup
SetupIconFile=assets\geolens.ico
UninstallDisplayIcon={app}\GeoLens.exe
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
DisableProgramGroupPage=yes

[Files]
Source: "dist\GeoLens\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\GeoLens"; Filename: "{app}\GeoLens.exe"
Name: "{autodesktop}\GeoLens"; Filename: "{app}\GeoLens.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Run]
Filename: "{app}\GeoLens.exe"; Description: "Launch GeoLens"; Flags: nowait postinstall skipifsilent
