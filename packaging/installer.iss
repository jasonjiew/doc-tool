; -*- coding: utf-8 -*-
; Inno Setup 脚本：康尚文档工具 Windows 安装器
;
; 任务 8.5：稳定 AppId、按用户安装、开始菜单和可选桌面快捷方式。
; 任务 8.6：静默安装、覆盖升级、修复和卸载只管理应用文件。
; 任务 8.7：升级/卸载不删除外部项目。
;
; 构建命令：
;   iscc.exe packaging/installer.iss
;
; 产出：
;   packaging/Output/KonsungDocTool-Setup-<version>.exe
;
; 安装目录：%LOCALAPPDATA%\Konsung\DocTool（无需管理员权限）
; 用户项目目录：由用户选择，不在安装目录下，卸载不删除。

#define MyAppName "康尚文档工具"
#define MyAppNameEn "KonsungDocTool"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "康尚医疗"
#define MyAppURL "http://www.konsung.com"
#define MyAppExeName "KonsungDocTool.exe"

; 稳定 AppId：基于 DNS 命名空间生成的 UUID5，跨版本保持一致
; 升级和卸载依赖此 ID 识别同一应用
#define MyAppId "F6D0000F-13F0-50D9-8743-5B42D68FF071"

[Setup]
AppId={{{#MyAppId}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Konsung\DocTool
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
OutputBaseFilename=KonsungDocTool-Setup-{#MyAppVersion}
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
; PyInstaller onedir 产出（dist/KonsungDocTool/* -> 安装目录/*）
Source: "..\dist\KonsungDocTool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 开始菜单快捷方式
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
; 桌面快捷方式（可选）
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后可选启动应用
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载前确保应用已关闭
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#MyAppExeName} /F /T 2>nul"; Flags: runhidden; RunOnceId: "KillApp"

; 不声明 [UninstallDelete] 的 filesandordirs {app}。Inno Setup 会删除自己安装
; 的文件；安装目录中非安装器拥有的文件会被保留，符合非破坏性卸载要求。

[Code]
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
  // 升级时跳过目录选择页（使用之前的目录）
  if PageID = wpSelectDir then
    Result := FileExists(ExpandConstant('{app}\{#MyAppExeName}'))
  else
    Result := False;
end;
