; ============================================================
; PLN Billing Analyzer v2.1 - Inno Setup script
; ============================================================
; Compile: iscc installer.iss
; Output : Output\PLN-Billing-Setup-v2.1.exe
; ============================================================

#define AppName     "PLN Billing Analyzer"
#define AppVersion  "2.1"
#define AppPublisher "PLN"
#define AppExeName  "PLN-Billing.exe"

[Setup]
AppId={{B7E5F3C2-9D4A-4E1F-A8B6-C0D9E2F8A3B1}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\PLN-Billing
DefaultGroupName=PLN Billing Analyzer
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=PLN-Billing-Setup-v{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Buat shortcut di Desktop"; GroupDescription: "Shortcut tambahan:"

[Files]
; Semua isi dist\PLN-Billing\
Source: "dist\PLN-Billing\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PLN Billing Analyzer"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall PLN Billing Analyzer"; Filename: "{uninstallexe}"
Name: "{userdesktop}\PLN Billing Analyzer"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Jalankan {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Hapus folder kerja kosong saat uninstall (file user data tetap aman di %LOCALAPPDATA%\PLN-Billing)
Type: filesandordirs; Name: "{app}"
