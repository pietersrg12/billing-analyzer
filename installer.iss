; ============================================================
; SIMBA (Sistem Monitoring Baca Meter) v2.5 - Inno Setup script
; ============================================================
; Compile: iscc installer.iss
; Output : Output\SIMBA-Setup-v2.5.exe
;
; Hanya nama TAMPILAN yang SIMBA. AppId, nama .exe, dan DefaultDirName sengaja
; tetap: mengubahnya membuat installer baru tidak mengenali instalasi lama
; (terpasang ganda) dan folder data user pindah tempat.
; ============================================================

#define AppName     "SIMBA"
#define AppVersion  "2.7"
#define AppPublisher "PLN"
#define AppExeName  "PLN-Billing.exe"

[Setup]
AppId={{B7E5F3C2-9D4A-4E1F-A8B6-C0D9E2F8A3B1}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\PLN-Billing
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=SIMBA-Setup-v{#AppVersion}
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

[InstallDelete]
; Shortcut bernama lama (sebelum rebranding SIMBA). Tanpa ini, user yang upgrade
; punya dua shortcut ke .exe yang sama.
Type: filesandordirs; Name: "{autoprograms}\PLN Billing Analyzer"
Type: files; Name: "{userdesktop}\PLN Billing Analyzer.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Jalankan {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Hapus folder kerja kosong saat uninstall (file user data tetap aman di %LOCALAPPDATA%\PLN-Billing)
Type: filesandordirs; Name: "{app}"
