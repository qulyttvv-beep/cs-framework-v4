; Inno Setup script for the Spark X Windows installer.
;
;   pyinstaller sparkx.spec --noconfirm
;   iscc /DAppVersion=4.3.0 packaging\sparkx.iss
;
; Installs dist\Spark X\ for the current user (no admin prompt) into
; %LOCALAPPDATA%\Programs\Spark X, adds a Start-menu entry (and optionally a
; desktop icon and the `cs` command on PATH) and registers an uninstaller.
; Settings and chats live in %APPDATA%\Spark X, so they survive upgrades.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C1F3B2E-5A0D-4E8B-9D2A-53A7C1E0F4B9}
AppName=Spark X
AppVersion={#AppVersion}
AppVerName=Spark X {#AppVersion}
AppPublisher=Spark X
AppPublisherURL=https://github.com/qulyttvv-beep/cs-framework-v4
AppSupportURL=https://github.com/qulyttvv-beep/cs-framework-v4/issues
AppUpdatesURL=https://github.com/qulyttvv-beep/cs-framework-v4/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Spark X
DefaultGroupName=Spark X
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
OutputDir=..\out
OutputBaseFilename=SparkX-Setup-x64
SetupIconFile=..\assets\sparkx.ico
UninstallDisplayIcon={app}\Spark X.exe
UninstallDisplayName=Spark X
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "addtopath"; Description: "Add the cs command-line tool to PATH"; GroupDescription: "Command line:"; Flags: unchecked

[Files]
Source: "..\dist\Spark X\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; tells Spark X it is installed, so it keeps its data in %APPDATA%\Spark X
Source: "INSTALLED"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Spark X"; Filename: "{app}\Spark X.exe"
Name: "{autodesktop}\Spark X"; Filename: "{app}\Spark X.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
  Check: NeedsAddPath(ExpandConstant('{app}')); Tasks: addtopath

[Run]
Filename: "{app}\Spark X.exe"; Description: "{cm:LaunchProgram,Spark X}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

procedure RemoveFromPath(Dir: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
    exit;
  Paths := ';' + Paths + ';';
  P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Paths));
  if P = 0 then
    exit;
  Delete(Paths, P, Length(Dir) + 1);
  Paths := Copy(Paths, 2, Length(Paths) - 2);
  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
