; Установщик «Стыки» (Inno Setup 6). Собирается из build.py:
;   ISCC /DAppVersion=1.0.0 /DSourceDir=dist\StationJoints installer.iss
; Ставится без прав администратора – в %LOCALAPPDATA%\Programs\StationJoints,
; регистрирует файлы работ .stj, при обновлении заменяет старую версию.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\StationJoints"
#endif

[Setup]
; постоянный идентификатор – по нему установщик находит прошлую версию
AppId={{6E0B7C1A-3F52-4E8B-9C2D-5A1F0D7E4B93}
AppName=Стыки
AppVersion={#AppVersion}
AppVerName=Стыки {#AppVersion}
AppPublisher=viirtualp1
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\StationJoints
DefaultGroupName=Стыки
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=StationJoints-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\StationJoints.exe
UninstallDisplayName=Стыки – схема станции
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
; при обновлении закрыть запущенную программу
CloseApplications=force
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[InstallDelete]
; старые файлы движка и интерфейса – чтобы от прошлой версии ничего не осталось
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\data"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Стыки"; Filename: "{app}\StationJoints.exe"
Name: "{autodesktop}\Стыки"; Filename: "{app}\StationJoints.exe"; Tasks: desktopicon

[Registry]
; файлы работ .stj открываются двойным щелчком
Root: HKA; Subkey: "Software\Classes\.stj"; ValueType: string; ValueName: ""; ValueData: "StationJoints.Project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\StationJoints.Project"; ValueType: string; ValueName: ""; ValueData: "Работа «Стыки»"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\StationJoints.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\StationJoints.exe,0"
Root: HKA; Subkey: "Software\Classes\StationJoints.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\StationJoints.exe"" ""%1"""

[Run]
Filename: "{app}\StationJoints.exe"; Description: "Запустить «Стыки»"; Flags: nowait postinstall skipifsilent
; тихое обновление из программы – сразу запустить новую версию
Filename: "{app}\StationJoints.exe"; Flags: nowait; Check: WizardSilent
