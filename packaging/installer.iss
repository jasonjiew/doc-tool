; -*- coding: utf-8 -*-
; Inno Setup 脚本：Doc Tool Windows 安装器
;
; 任务 8.5：稳定 AppId、按用户安装、开始菜单和可选桌面快捷方式。
; 任务 8.6：静默安装、覆盖升级、修复和卸载只管理应用文件。
; 任务 8.7：升级/卸载不删除外部项目。
; 任务 2.4：公共身份（AppName/Publisher/URL/AppId/安装目录），与内部版可并存。
;
; 构建命令：
;   iscc.exe packaging/installer.iss
;
; 产出：
;   packaging/Output/DocTool-Setup-<version>.exe
;
; 安装目录：%LOCALAPPDATA%\DocTool（无需管理员权限），与内部版旧安装目录隔离
; 用户项目目录：由用户选择，不在安装目录下，卸载不删除。
;
; 发布决策（见 docs/release/02-release-decisions.md）：
;   Publisher 采用中性「Doc Tool Project」，URL 本期为空（公共域名未定）；
;   决策已登记为 DECIDED，正式公开前如需更名按决策登记表一次性调整。
;
; 加固（2026-08，针对成员报 "Failed to start embedded python interpreter!"）：
;   1) 中文 Windows 用户名会把默认安装目录变成 C:\Users\张三\AppData\Local\...，
;      PyInstaller 引导程序在非 ASCII 路径下初始化内嵌 Python 失败，报上述错误。
;      安装器检测到非 ASCII 安装目录时自动改用 {commonappdata}\DocTool 并提示；
;      用户若仍选择非 ASCII 目录，Next 会被阻止并给出说明。
;   2) 开始菜单/桌面快捷方式经 installed\启动DocTool.cmd 把程序复制到 %TEMP% 下
;      全新随机目录再启动，绕开安全软件对未签名 exe 从安装目录加载 DLL 的拦截
;      （与便携包同策略）。

#define MyAppName "Doc Tool"
#define MyAppNameEn "DocTool"
#define MyAppVersion "1.4.1"
#define MyAppPublisher "Doc Tool Project"
#define MyAppURL "https://github.com/wangjie0721666-web/doc-tool"
#define MyAppExeName "DocTool.exe"

; 稳定 AppId：公共产品专用 UUID5（不复用内部版旧 AppId，见 docs/release 基线）。
; 升级和卸载依赖此 ID 识别同一应用；值在正式发布前须经发布负责人复核。
#define MyAppId "8C61369A-D7C7-51D4-BD14-5B555EF93E52"

[Setup]
AppId={{{#MyAppId}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 按用户安装，不需要管理员权限
PrivilegesRequired=lowest
; 单实例安装，升级时自动关闭旧版本
CloseApplications=force
RestartApplications=yes
; 不允许自定义安装目录到 Program Files（避免权限问题）
UsePreviousAppDir=yes
; 卸载时不删除用户数据（项目、输出、日志在安装目录外）
UninstallFilesDir={app}\uninst
; 输出文件名包含版本号
OutputDir=Output
OutputBaseFilename={#MyAppNameEn}-Setup-{#MyAppVersion}
; 安装器与卸载器图标
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; 压缩
Compression=lzma2/ultra64
SolidCompression=yes
; 磁盘跨越
DiskSpanning=no
; 版本信息（显示在文件属性中）
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
; 安装器界面语言
ShowLanguageDialog=no

[Languages]
; 中文语言文件需从 https://jrsoftware.org/files/istrans/ 下载 ChineseSimplified.isl
; 放入 Inno Setup Languages 目录后改用：compiler:Languages\ChineseSimplified.isl
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
; PyInstaller onedir 产出（dist/DocTool/* -> 安装目录/*）
Source: "..\dist\{#MyAppNameEn}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 安装版启动器：复制到 %TEMP% 全新目录再启动（绕开安全软件对未签名 exe 的拦截）
Source: "installed\启动DocTool.cmd"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 开始菜单快捷方式：经启动器运行（%TEMP% 复制启动，规避安全软件拦截）
Name: "{group}\{#MyAppName}"; Filename: "{app}\启动DocTool.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
; 桌面快捷方式（可选）
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\启动DocTool.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后可选启动应用（经启动器）
Filename: "{app}\启动DocTool.cmd"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载前确保应用已关闭
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#MyAppExeName} /F /T 2>nul"; Flags: runhidden; RunOnceId: "KillApp"

; 不声明 [UninstallDelete] 的 filesandordirs {app}。Inno Setup 会删除自己安装
; 的文件；安装目录中非安装器拥有的文件会被保留，符合非破坏性卸载要求。

[Code]
var
  NonAsciiDirHintShown: Boolean;

// 判断安装是否处于静默模式（/SILENT 或 /VERYSILENT）。Inno Setup 6.7.3
// 没有内置 IsSilent 函数，用 ParamStr 检测命令行参数。
function IsSilent: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    if (CompareText(ParamStr(I), '/SILENT') = 0) or
       (CompareText(ParamStr(I), '/VERYSILENT') = 0) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

// 判断目录路径是否只含 ASCII 字符。PyInstaller 引导程序在非 ASCII 路径
// （如中文 Windows 用户名导致的 C:\Users\张三\...）下初始化内嵌 Python 会
// 失败并报 "Failed to start embedded python interpreter!"。
function IsAsciiPath(const S: String): Boolean;
var
  I: Integer;
begin
  Result := True;
  for I := 1 to Length(S) do
  begin
    if Ord(S[I]) > 127 then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

// 进入目录选择页时：默认目录含非 ASCII 字符则自动改用 {commonappdata}（纯 ASCII）。
// 仅交互式安装生效；静默安装（/SILENT /VERYSILENT）由调用方显式传入目录，
// 且经启动器复制到 %TEMP% 纯 ASCII 目录运行，不在此处拦截。
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectDir) and (not IsSilent()) then
  begin
    if (not NonAsciiDirHintShown) and (not IsAsciiPath(WizardDirValue())) then
    begin
      WizardForm.DirEdit.Text := ExpandConstant('{commonappdata}\{#MyAppNameEn}');
      MsgBox('默认安装目录包含中文等非 ASCII 字符，会导致程序无法启动。' + #13#10 +
             '已自动改用纯英文目录：' + ExpandConstant('{commonappdata}\{#MyAppNameEn}') + #13#10 +
             '如不希望安装到该目录，请手动选择一个纯英文路径（例如 D:\DocTool）。',
             mbInformation, MB_OK);
      NonAsciiDirHintShown := True;
    end;
  end;
end;

// 目录选择页点「下一步」时：目录仍含非 ASCII 字符则阻止继续，并给出说明。
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and (not IsSilent()) then
  begin
    if not IsAsciiPath(WizardDirValue()) then
    begin
      MsgBox('安装目录不能包含中文等非 ASCII 字符，否则程序将无法启动。' + #13#10 +
             '请选择纯英文目录，例如 D:\DocTool 或 C:\ProgramData\DocTool。',
             mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // 升级前关闭正在运行的应用
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM {#MyAppExeName} /F /T 2>nul',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // 升级时跳过目录选择页（使用之前的目录）。注意不能用 {app} 常量——
  // ShouldSkipPage 在 {app} 初始化之前就可能被调用，会触发
  // "attempt was made to expand the 'app' constant before it was initialized"；
  // WizardDirValue() 直接读目录输入框的当前值，任何阶段都安全。
  if PageID = wpSelectDir then
    Result := FileExists(WizardDirValue() + '\{#MyAppExeName}')
  else
    Result := False;
end;
