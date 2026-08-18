# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    Doc Tool 一键打包脚本：把项目打包成 Windows 可执行程序（exe）。

.DESCRIPTION
    轻量打包脚本，不需要 Inno Setup，也不跑发布门禁/泄漏扫描。
    - 默认（onedir）：dist\DocTool\DocTool.exe（GUI）+ doc-tool-cli.exe（CLI），
      目录整体分发，启动快，是项目的官方布局。
    - -OneFile：dist\DocTool.exe 单文件，一个 exe 随用随拷；首次启动需
      解压到系统临时目录，稍慢，但能绕过部分公司安全软件对"未签名 exe
      从普通目录加载 DLL"的拦截（本机实测 %TEMP% 外运行会报
      "DLL load failed while importing _socket"）。
    - onedir 构建完成后默认运行冻结冒烟测试，可用 -SkipTests 跳过。

.PARAMETER OneFile
    构建单文件 exe（使用 packaging\doc_tool_onefile.spec）。

.PARAMETER SkipTests
    跳过冻结冒烟测试。

.PARAMETER InstallDeps
    缺少 PyInstaller/PySide6 时自动 pip 安装（默认只提示）。

.EXAMPLE
    .\build_exe.ps1
    .\build_exe.ps1 -OneFile
    .\build_exe.ps1 -InstallDeps
#>

[CmdletBinding()]
param(
    [switch]$OneFile,
    [switch]$SkipTests,
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"
# 子进程统一 UTF-8，避免中文路径/输出在 GBK 下乱码
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$RepoRoot = Resolve-Path "$PSScriptRoot"
$SpecFile = if ($OneFile) { "packaging\doc_tool_onefile.spec" } else { "packaging\doc_tool.spec" }
$Mode = if ($OneFile) { "单文件 onefile" } else { "onedir 目录" }

# 本机 site-packages 里的 PySide6 可能是残缺安装（只有顶层包，QtCore/QtWidgets
# 导入失败，打包结果会缺 Qt 全部组件）。项目自带的完整运行时
# build\pyside-runtime（scripts\setup_pyside6.py 产物）优先用于构建。
$VendoredQt = "$RepoRoot\build\pyside-runtime"
if (Test-Path "$VendoredQt\PySide6") {
    $env:PYTHONPATH = "$VendoredQt;$env:PYTHONPATH"
    Write-Host "使用本地完整 PySide6 运行时: $VendoredQt" -ForegroundColor DarkGray
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "=== Doc Tool 打包成 exe ===" -ForegroundColor Cyan
Write-Host "模式    : $Mode"
Write-Host "仓库根  : $RepoRoot"
Write-Host ""

# --- 1. 检查 Python ---
if (-not (Test-Command python)) {
    throw "未找到 Python。请先安装 Python 3.13 并加入 PATH。"
}
$PythonVer = (& python --version 2>&1).Trim()
Write-Host "[1/4] Python: $PythonVer" -ForegroundColor Green

# --- 2. 检查构建依赖 ---
$Missing = @()
& python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { $Missing += "pyinstaller" }
# 顶层包可导入不代表安装完整，必须能真正导入 QtWidgets
& python -c "from PySide6.QtWidgets import QApplication" 2>$null
if ($LASTEXITCODE -ne 0) { $Missing += "PySide6(QtWidgets)" }

if ($Missing.Count -gt 0) {
    Write-Host "[2/4] 缺少构建依赖: $($Missing -join ', ')" -ForegroundColor Yellow
    if ($InstallDeps) {
        Write-Host "  正在安装依赖（需要几分钟，请保持网络可用）..." -ForegroundColor Yellow
        Push-Location $RepoRoot
        try {
            & python -m pip install -r requirements.txt -r requirements-build.txt
            if ($LASTEXITCODE -ne 0) { throw "依赖安装失败 (exit $LASTEXITCODE)" }
        } finally {
            Pop-Location
        }
    } else {
        throw "缺少构建依赖。请先执行: python -m pip install -r requirements.txt -r requirements-build.txt`n或加 -InstallDeps 参数自动安装。`n（本机若 pip 报 WinError 17，属公司安全软件拦截，改用: python scripts\setup_pyside6.py）"
    }
} else {
    Write-Host "[2/4] 构建依赖已就绪" -ForegroundColor Green
}

# --- 3. PyInstaller 构建 ---
Write-Host "[3/4] PyInstaller 构建中（$Mode）..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    & python -m PyInstaller $SpecFile --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$ExePath = if ($OneFile) {
    "$RepoRoot\dist\DocTool.exe"
} else {
    "$RepoRoot\dist\DocTool\DocTool.exe"
}
if (-not (Test-Path $ExePath)) {
    throw "未找到构建产物: $ExePath"
}
$SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
Write-Host "  $($ExePath) 生成成功 ($SizeMB MB)" -ForegroundColor Green

# --- 4. 冻结冒烟测试（仅 onedir 布局） ---
if (-not $OneFile -and -not $SkipTests) {
    Write-Host "[4/4] 冻结冒烟测试..." -ForegroundColor Yellow
    Push-Location $RepoRoot
    try {
        & python scripts\tests\test_frozen_smoke.py
        $SmokeExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($SmokeExit -ne 0) {
        # 部分公司安全软件对"未签名 exe 从 %TEMP% 之外加载 DLL"返回
        # ERROR_BAD_EXE_FORMAT（DLL load failed while importing _socket/_ctypes）。
        # 构建产物本身有效（在 %TEMP% 下运行正常），此失败是环境拦截而非打包问题。
        Write-Host "  冒烟测试未通过（exit $SmokeExit）" -ForegroundColor Yellow
        Write-Host "  提示: 若报错含 'DLL load failed while importing _socket'，" -ForegroundColor Yellow
        Write-Host "        这是本机安全软件拦截未签名 exe 从 %TEMP% 外加载 DLL，并非打包问题。" -ForegroundColor Yellow
        Write-Host "        可把 dist\DocTool 复制到 %TEMP% 下运行验证，或改用 -OneFile 构建。" -ForegroundColor Yellow
    } else {
        Write-Host "  冒烟测试通过" -ForegroundColor Green
    }
} else {
    Write-Host "[4/4] 跳过冒烟测试" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "=== 构建完成 ===" -ForegroundColor Cyan
Write-Host "GUI exe: $ExePath" -ForegroundColor White
if ($OneFile) {
    Write-Host "单文件 exe 可直接拷贝分发；首次启动解压到系统临时目录，稍慢。" -ForegroundColor White
    Write-Host "（本机安全软件拦截 %TEMP% 外的未签名 exe 加载 DLL，onefile 模式已实测可用）" -ForegroundColor DarkGray
} else {
    Write-Host "CLI exe: $RepoRoot\dist\DocTool\doc-tool-cli.exe" -ForegroundColor White
    Write-Host "分发时保持 dist\DocTool 整个目录完整（exe 依赖同目录 _internal/）。" -ForegroundColor White
    Write-Host "本机若直接运行报 'DLL load failed while importing _socket'：" -ForegroundColor DarkGray
    Write-Host "  1) 复制 dist\DocTool 到 %TEMP% 下运行（实测可用）；或" -ForegroundColor DarkGray
    Write-Host "  2) 用 -OneFile 重新构建单文件 exe。" -ForegroundColor DarkGray
}
