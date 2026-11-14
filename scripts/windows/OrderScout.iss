[Setup]
AppId={{6A52E4F6-EA38-4AF9-9F73-76D9B02B89B1}
AppName=OrderScout
AppVersion={#AppVersion}
AppPublisher=OrderScout contributors
AppPublisherURL=https://github.com/hermanjons/OrderScout
AppSupportURL=https://github.com/hermanjons/OrderScout/issues
DefaultDirName={autopf}\OrderScout\os-{#AppVersion}
UsePreviousAppDir=no
DefaultGroupName=OrderScout
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=OrderScout_Setup_x64
SetupIconFile={#AppDir}\_internal\images\orderscout-logo.ico
UninstallDisplayIcon={app}\OrderScout.exe
LicenseFile={#AppDir}\licenses\OrderScout\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#VCRedist}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsVCRuntime

[Icons]
Name: "{group}\OrderScout"; Filename: "{app}\OrderScout.exe"

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ runtime..."; Flags: waituntilterminated; Check: NeedsVCRuntime
Filename: "{app}\OrderScout.exe"; Description: "{cm:LaunchProgram,OrderScout}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsVCRuntime: Boolean;
var
  Installed, Major, Minor: Cardinal;
begin
  Result :=
    not RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) or
    (Installed <> 1) or
    not RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Major', Major) or
    not RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Minor', Minor) or
    (Major < 14) or ((Major = 14) and (Minor < 42));
end;
