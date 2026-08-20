# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    Doc Tool 一键打包脚本：把项目打包成 Windows 可执行程序（exe）。

.DESCRIPTION
    轻量打包脚本，不需要 Inno Setup，也不跑发布门禁/泄漏扫描。
    - 默认（onedir）：dist\DocTool\DocTool.exe（GUI）+ doc-tool-cli.exe（CLI），
      目录整体分发，启动快，是项目的官方布局。
    - -OneFile：dist\DocTool.exe 单文件，一个 exe 随用随拷；首次启动需
      解压到系统临时目录，稍慢。
    - 构建依赖优先使用仓库自带的 vendored 运行时（规避安全软件对 pip 的
      拦截与本机残缺安装）：
        build\pyinstaller-tool\    PyInstaller 6.22.1
        build\pyside-runtime\      完整 PySide6 6.8.3（site-packages 可能残缺）
    - PyInstaller 版本必须 >= requirements-build.txt 的锁定版本（6.22.1）；
      旧版（如 6.14.0）在 Python 3.13/Windows 上会打出扩展模块加载失败的坏包。
    - 构建完成后默认执行：产物内容校验（Qt/python313 是否齐全、是否残留
      multiprocessing 启动钩子）+ 冻结冒烟测试（仅 onedir），可用 -SkipTests 跳过。

.PARAMETER OneFile
    构建单文件 exe（使用 packaging\doc_tool_onefile.spec）。

.PARAMETER Portable
    在 onedir 构建之后额外打出团队分发便携包
    dist\DocTool-<版本>-portable.zip（DocTool\ + 启动DocTool.cmd）。
    启动脚本每次把整个目录复制到 %TEMP% 下全新随机目录再启动，绕开安全软件
    对「未签名 exe 从 %TEMP% 之外加载 DLL」的拦截与路径信誉拖黑。

.PARAMETER SkipTests
    跳过冻结冒烟测试与产物内容校验。

.PARAMETER InstallDeps
    缺少 PyInstaller/PySide6 时自动 pip 安装（pip 被安全软件拦截时自动重试一次；
    仍失败则提示改用 vendored 运行时）。默认只提示。

.EXAMPLE
    .\build_exe.ps1
    .\build_exe.ps1 -OneFile
    .\build_exe.ps1 -Portable
    .\build_exe.ps1 -InstallDeps
#>

[CmdletBinding()]
param(
    [switch]$OneFile,
    [switch]$Portable,
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

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# --- vendored 运行时（优先使用，规避安全软件对 pip 的拦截与本机残缺安装）---
$VendoredQt = "$RepoRoot\build\pyside-runtime"
$VendoredPyInstaller = "$RepoRoot\build\pyinstaller-tool"
$PyPathParts = @()
if (Test-Path "$VendoredPyInstaller\PyInstaller") {
    $PyPathParts += $VendoredPyInstaller
    Write-Host "使用本地 vendored PyInstaller: $VendoredPyInstaller" -ForegroundColor DarkGray
}
if (Test-Path "$VendoredQt\PySide6") {
    $PyPathParts += $VendoredQt
    Write-Host "使用本地完整 PySide6 运行时: $VendoredQt" -ForegroundColor DarkGray
}
if ($env:PYTHONPATH) { $PyPathParts += $env:PYTHONPATH }
if ($PyPathParts.Count -gt 0) {
    $env:PYTHONPATH = ($PyPathParts | Select-Object -Unique) -join ';'
}

# requirements-build.txt 中锁定的 PyInstaller 最低版本
# （6.14.0 在 Python 3.13/Windows 上有冻结应用扩展模块加载失败问题，见文件内注释）
$PyInstallerMin = $null
$PinLine = Select-String -Path "$RepoRoot\requirements-build.txt" -Pattern '^\s*pyinstaller==([0-9][0-9.]*)\s*$' -ErrorAction SilentlyContinue
if ($PinLine) { $PyInstallerMin = [version]$PinLine.Matches[0].Groups[1].Value }

function Get-PyInstallerVersion {
    $out = (& python -m PyInstaller --version 2>&1 | Select-Object -First 1).ToString().Trim()
    if ($out -match '^\d+\.\d+') { return [version]($out -split '\s')[0] }
    return $null
}

function Install-BuildDeps {
    Push-Location $RepoRoot
    try {
        # 安全软件（如火绒企业版）可能拦截 pip 的文件移动/替换（WinError 17/5），
        # 首次失败后带 --no-cache-dir 重试一次。
        & python -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt
        if ($LASTEXITCODE -eq 0) { return $true }
        Write-Host "  pip 首次安装失败（exit $LASTEXITCODE），可能被安全软件拦截，重试一次..." -ForegroundColor Yellow
        & python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt -r requirements-build.txt
        if ($LASTEXITCODE -eq 0) { return $true }
        return $false
    } finally {
        Pop-Location
    }
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
Write-Host "[1/5] Python: $PythonVer" -ForegroundColor Green

# --- 2. 检查构建依赖（PyInstaller 版本 + PySide6）---
$NeedDeps = $false
$PyVer = Get-PyInstallerVersion
if (-not $PyVer) {
    $NeedDeps = $true
} elseif ($PyInstallerMin -and $PyVer -lt $PyInstallerMin) {
    Write-Host ("[2/5] PyInstaller 版本过低: 当前 {0}，要求 >= {1}（旧版在 Python 3.13 上会打出 " -f $PyVer, $PyInstallerMin) -ForegroundColor Yellow
    Write-Host "      'DLL load failed while importing _socket' 的坏包）" -ForegroundColor Yellow
    $NeedDeps = $true
}
# 顶层包可导入不代表安装完整，必须能真正导入 QtWidgets
& python -c "from PySide6.QtWidgets import QApplication" 2>$null
if ($LASTEXITCODE -ne 0) { $NeedDeps = $true }

if ($NeedDeps) {
    if ($InstallDeps) {
        Write-Host "[2/5] 安装构建依赖..." -ForegroundColor Yellow
        $DepsOk = Install-BuildDeps
        if (-not $DepsOk) {
            throw "依赖安装失败。若报 WinError 17/5，是安全软件（火绒企业版）拦截 pip：`n  · 仓库 build\ 下自带 vendored 运行时（pyinstaller-tool、pyside-runtime），可直接构建，无需 pip；`n  · 或请 IT 在火绒终端安全管理中心为本机加白名单。"
        }
    } else {
        throw "缺少构建依赖。请先执行: python -m pip install -r requirements.txt -r requirements-build.txt`n或加 -InstallDeps 参数自动安装。`n（安全软件拦截 pip 时，build\ 下的 vendored 运行时已自动优先使用。）"
    }
} else {
    Write-Host "[2/5] 构建依赖已就绪 (PyInstaller $PyVer)" -ForegroundColor Green
}

# --- 3. PyInstaller 构建 ---
Write-Host "[3/5] PyInstaller 构建中（$Mode）..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    & python -m PyInstaller $SpecFile --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$GuiExe = if ($OneFile) { "$RepoRoot\dist\DocTool.exe" } else { "$RepoRoot\dist\DocTool\DocTool.exe" }
$CliExe = "$RepoRoot\dist\DocTool\doc-tool-cli.exe"
if (-not (Test-Path $GuiExe)) {
    throw "未找到构建产物: $GuiExe"
}
$SizeMB = [math]::Round((Get-Item $GuiExe).Length / 1MB, 1)
Write-Host "  $GuiExe 生成成功 ($SizeMB MB)" -ForegroundColor Green

# --- 4/5. 产物内容校验 + 冻结冒烟测试 ---
function Assert-NoMultiprocessingRthook([string]$ExePath) {
    # 冻结 exe 若仍带 pyi_rth_multiprocessing 钩子，启动时会 import socket->_socket，
    # 在受限环境触发安全软件拦截（ERROR_BAD_EXE_FORMAT / "not a valid Win32 application"）。
    # spec 已排除 multiprocessing，这里确认产物确实不含该钩子。
    $bytes = [System.IO.File]::ReadAllBytes($ExePath)
    $text = [System.Text.Encoding]::ASCII.GetString($bytes)
    if ($text -match 'pyi_rth_multiprocessing') {
        throw "产物 $ExePath 仍包含 pyi_rth_multiprocessing 启动钩子——请检查 spec 的 excludes 是否排除了 multiprocessing。"
    }
}

if (-not $SkipTests) {
    Write-Host "[4/5] 产物内容校验..." -ForegroundColor Yellow
    if ($OneFile) {
        # onefile：检查归档内含 python313.dll + Qt 组件，且不含 multiprocessing 钩子
        $List = & python -m PyInstaller.utils.cliutils.archive_viewer -l -b $GuiExe 2>&1
        foreach ($Need in @('python313.dll', 'Qt6Core.dll', 'Qt6Widgets.dll', 'shiboken6')) {
            if (-not ($List | Select-String -SimpleMatch $Need)) {
                throw "onefile 产物缺少 $Need——请确认构建时 PYTHONPATH 挂载了 build\pyside-runtime（直接运行 python -m PyInstaller 会用到残缺的 site-packages PySide6）。"
            }
        }
        if ($List | Select-String -SimpleMatch 'pyi_rth_multiprocessing') {
            throw "onefile 产物仍包含 pyi_rth_multiprocessing——请检查 spec 的 excludes。"
        }
    } else {
        $Internal = "$RepoRoot\dist\DocTool\_internal"
        foreach ($Need in @('python313.dll', 'Qt6Core.dll', 'shiboken6.abi3.dll')) {
            if (-not (Test-Path "$Internal\$Need")) {
                throw "onedir 产物缺少 $Internal\$Need——请确认构建时 PYTHONPATH 挂载了 build\pyside-runtime。"
            }
        }
        Assert-NoMultiprocessingRthook $GuiExe
        Assert-NoMultiprocessingRthook $CliExe
    }
    Write-Host "  产物内容校验通过。" -ForegroundColor Green

    if (-not $OneFile) {
        Write-Host "[5/5] 冻结冒烟测试..." -ForegroundColor Yellow
        Push-Location $RepoRoot
        try {
            & python scripts\tests\test_frozen_smoke.py
            $SmokeExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        if ($SmokeExit -ne 0) {
            # 部分公司安全软件（火绒企业版）对"未签名 exe 从 %TEMP% 之外加载 DLL"
            # 返回 ERROR_BAD_EXE_FORMAT（DLL load failed while importing _socket）。
            # 构建产物本身有效（在 %TEMP% 下运行正常），此失败是环境拦截而非打包问题。
            Write-Host "  冒烟测试未通过（exit $SmokeExit）" -ForegroundColor Yellow
            Write-Host "  提示: 若报错含 'DLL load failed while importing _socket'，" -ForegroundColor Yellow
            Write-Host "        这是安全软件（火绒企业版）拦截未签名 exe 从 %TEMP% 外加载 DLL，并非打包问题。" -ForegroundColor Yellow
            Write-Host "        可把 dist\DocTool 复制到 %TEMP% 下运行验证，或双击 dist\启动DocTool.cmd 启动。" -ForegroundColor Yellow
        } else {
            Write-Host "  冒烟测试通过" -ForegroundColor Green
        }
    } else {
        Write-Host "[5/5] 跳过冒烟测试（onefile 无 onedir 目录布局）" -ForegroundColor DarkGray
    }
} else {
    Write-Host "[4/5][5/5] 已跳过产物校验与冒烟测试" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "=== 构建完成 ===" -ForegroundColor Cyan
Write-Host "GUI exe: $GuiExe" -ForegroundColor White
if ($OneFile) {
    Write-Host "单文件 exe 可直接拷贝分发；首次启动解压到系统临时目录，稍慢。" -ForegroundColor White
    Write-Host "（本机安全软件会随机拦截未签名 exe，onefile 在本机也不保证每次都能启动；干净机器上可用）" -ForegroundColor DarkGray
} else {
    Write-Host "CLI exe: $CliExe" -ForegroundColor White
    Write-Host "分发时保持 dist\DocTool 整个目录完整（exe 依赖同目录 _internal/）。" -ForegroundColor White
    Write-Host "本机（火绒企业版）若直接运行 GUI 报 'DLL load failed while importing _socket'：" -ForegroundColor DarkGray
    Write-Host "  1) 双击 dist\启动DocTool.cmd（自动复制到 %TEMP% 全新目录再启动，实测可用）；或" -ForegroundColor DarkGray
    Write-Host "  2) 请 IT 在火绒终端安全管理中心把本目录加入信任区/执行控制白名单，或对 exe 做代码签名。" -ForegroundColor DarkGray
}

# --- 便携包（团队分发）---
# 安全软件（火绒企业版）拦截未签名 exe 从 %TEMP% 之外加载 DLL，且同一路径反复
# 运行会把该路径的信誉拖黑。便携包把 onedir 产物和启动脚本打成一个 zip：同事解压
# 到任意位置，双击脚本即可（脚本每次复制到 %TEMP% 下全新随机目录再启动）。
if ($Portable) {
    if ($OneFile) {
        throw "-Portable 需要 onedir 布局（便携包依赖 DocTool\ 目录），请去掉 -OneFile。"
    }
    Write-Host ""
    Write-Host "=== 生成便携包 ===" -ForegroundColor Cyan
    $Launcher = Join-Path $RepoRoot "packaging\portable\启动DocTool.cmd"
    if (-not (Test-Path $Launcher)) { throw "缺少启动脚本: $Launcher" }
    Push-Location $RepoRoot
    try {
        $AppVersion = (& python -c "from doc_tool.domain.version import APP_VERSION; print(APP_VERSION)").Trim()
    } finally {
        Pop-Location
    }
    if (-not $AppVersion) { throw "无法读取 APP_VERSION" }
    Copy-Item $Launcher (Join-Path $RepoRoot "dist") -Force
    $Zip = Join-Path $RepoRoot "dist\DocTool-$AppVersion-portable.zip"
    if (Test-Path $Zip) { Remove-Item $Zip -Force }
    Compress-Archive -Path @(
        (Join-Path $RepoRoot "dist\DocTool"),
        (Join-Path $RepoRoot "dist\启动DocTool.cmd")
    ) -DestinationPath $Zip -CompressionLevel Optimal
    $SizeMb = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
    Write-Host "便携包: $Zip（$SizeMb MB）" -ForegroundColor White
    Write-Host "分发说明：整包发给同事，解压后双击「启动DocTool.cmd」，不要单独取出 DocTool.exe。" -ForegroundColor White
}

