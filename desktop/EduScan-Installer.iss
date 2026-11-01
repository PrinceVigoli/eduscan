#define MyAppName "EduScan Teacher"
#define MyAppVersion "0.4.0"
#define MyAppPublisher "Luna National High School"
#define MyAppExeName "EduScan-Teacher.exe"

[Setup]
AppId={{D95820C1-5BB5-4B85-AEF4-DB4C72326334}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\EduScan
DefaultGroupName=EduScan
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=EduScan-Teacher-Setup-0.4.0
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "..\release\EduScan-Windows-0.4.0\EduScan-Teacher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "STANDALONE GUIDE.txt"; DestDir: "{app}"; DestName: "PILOT GUIDE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\EduScan Teacher"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Create EduScan Backup"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--backup"
Name: "{group}\EduScan Pilot Guide"; Filename: "{app}\PILOT GUIDE.txt"
Name: "{autodesktop}\EduScan Teacher"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch EduScan Teacher"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; School data intentionally remains under %LOCALAPPDATA%\EduScan after uninstall.
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    MsgBox('EduScan will be removed. School data and backups under your Local AppData\EduScan folder will be preserved.', mbInformation, MB_OK);
end;
