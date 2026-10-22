; 모비 커넥터 리모콘 설치 파일 (tools\build.py 가 판 번호·경로를 넘겨 부른다)
; 사용자별 설치(관리자 권한 없이 설치) — 예전 2.x 설치판과 같은 %LOCALAPPDATA%\Programs 아래.
; 사용자 데이터는 %LOCALAPPDATA%\MabiDaily 라 지우거나 덮어써도 남는다.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0C5B3A-8F1D-4C2B-9E57-4A1F2D7B9C31}
AppName=모비 커넥터 리모콘
AppVersion={#AppVersion}
AppPublisher=Banteil
AppPublisherURL=https://github.com/Banteil/mobi-remote
DefaultDirName={localappdata}\Programs\mobi-remote-py
DefaultGroupName=모비 커넥터 리모콘
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=mobi-remote-{#AppVersion}-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\mobi-remote.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 실행 중인 리모콘이 있으면 닫으라고 묻는다 (덮어쓰기 실패 방지)
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로 가기 만들기"; GroupDescription: "추가 작업:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 예전 2.x(Electron) 설치판과 같은 이름·자리 → 2.x 의 새 판 알림으로 이 설치 파일을 실행하면 바로 가기가 새 판을 가리키게 된다
Name: "{userprograms}\모비 커넥터 리모콘"; Filename: "{app}\mobi-remote.exe"
Name: "{userdesktop}\모비 커넥터 리모콘"; Filename: "{app}\mobi-remote.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\mobi-remote.exe"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent shellexec
