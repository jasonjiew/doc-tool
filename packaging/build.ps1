# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    Doc Tool 安装包构建脚本

.DESCRIPTION
    任务 8.8：完整的安装包构建流水线。
    1. 运行 PyInstaller 构建 onedir 应用
    2. 运行冻结应用冒烟测试
    3. 运行 Inno Setup 编译安装器
    4. 生成 SHA-256 哈希
    5. 生成依赖清单（SBOM）

.PARAMETER SkipPyInstaller
    跳过 PyInstaller 构建（使用已有的 dist/ 产出）

.PARAMETER SkipTests
    跳过冒烟测试

.EXAMPLE
    .\packaging\build.ps1
    .\packaging\build.ps1 -SkipPyInstaller
#>

param(
    [switch]$SkipPyInstaller,
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
# Python test subprocesses emit UTF-8 paths and markers; avoid the Windows GBK
# fallback corrupting captured output in PowerShell-driven release builds.
$env:PYTHONUTF8 = "1"
$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$Version = "2.5.2"

# --- vendored 运行时（优先使用，规避安全软件对 pip 的拦截与本机残缺安装）---
$VendoredQt = "$RepoRoot\build\pyside-runtime"
$VendoredPyInstaller = "$RepoRoot\build\pyinstaller-tool"
$PyPathParts = @()
if (Test-Path "$VendoredPyInstaller\PyInstaller") { $PyPathParts += $VendoredPyInstaller }
if (Test-Path "$VendoredQt\PySide6") { $PyPathParts += $VendoredQt }
if ($env:PYTHONPATH) { $PyPathParts += $env:PYTHONPATH }
if ($PyPathParts.Count -gt 0) { $env:PYTHONPATH = ($PyPathParts | Select-Object -Unique) -join ';' }

# PyInstaller 版本门禁：requirements-build.txt 锁定 6.22.1
# （6.14.0 在 Python 3.13/Windows 上会打出冻结应用扩展模块加载失败的坏包）
$PyInstallerMin = $null
$PinLine = Select-String -Path "$RepoRoot\requirements-build.txt" -Pattern '^\s*pyinstaller==([0-9][0-9.]*)\s*$' -ErrorAction SilentlyContinue
if ($PinLine) { $PyInstallerMin = [version]$PinLine.Matches[0].Groups[1].Value }
$PyInstallerVerRaw = (& python -m PyInstaller --version 2>&1 | Select-Object -First 1).ToString().Trim()
$PyInstallerVer = $null
if ($PyInstallerVerRaw -match '^\d+\.\d+') { $PyInstallerVer = [version]($PyInstallerVerRaw -split '\s')[0] }
if (-not $PyInstallerVer) {
    throw "PyInstaller 不可用。请先执行 python -m pip install -r requirements-build.txt；pip 被安全软件拦截时，build\pyinstaller-tool 下已有 vendored 6.22.1 可自动使用。"
}
if ($PyInstallerMin -and $PyInstallerVer -lt $PyInstallerMin) {
    throw "PyInstaller 版本过低: $PyInstallerVer，要求 >= $PyInstallerMin（旧版在 Python 3.13 上会打出 'DLL load failed while importing _socket' 的坏包）。"
}

$AppVersion = (& python -c "from doc_tool.domain.version import APP_VERSION; print(APP_VERSION)").Trim()
$InstallerMatch = Select-String -Path "$PSScriptRoot\installer.iss" -Pattern '#define\s+MyAppVersion\s+"([^"]+)"'
$InstallerVersion = $InstallerMatch.Matches[0].Groups[1].Value
if ($Version -ne $AppVersion -or $Version -ne $InstallerVersion) {
    throw "版本不一致: build=$Version app=$AppVersion installer=$InstallerVersion"
}

Write-Host "=== Doc Tool 安装包构建 ===" -ForegroundColor Cyan
Write-Host "版本: $Version"
Write-Host "仓库根: $RepoRoot"
Write-Host ""

# --- 阶段 1：生产文档泄漏扫描 ---
Write-Host "[1/5] 生产文档泄漏扫描..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    & python packaging\scan_leaks.py
    if ($LASTEXITCODE -ne 0) {
        throw "生产文档泄漏扫描失败 (exit $LASTEXITCODE)"
    }
} finally {
    Pop-Location
}
Write-Host "  泄漏扫描通过。" -ForegroundColor Green

# 发布授权门禁状态：未决决策/未签署检查单会在此输出阻断提示。
# （正式公共发布强制阻断由 CI 以 `release_gate.py --public` 执行；本地构建只报告状态。）
Write-Host "  发布授权门禁..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    & python packaging\release_gate.py
    if ($LASTEXITCODE -ne 0) {
        throw "发布授权门禁失败 (exit $LASTEXITCODE)"
    }
} finally {
    Pop-Location
}

# --- 阶段 2：PyInstaller 构建 ---
if (-not $SkipPyInstaller) {
    Write-Host "[2/5] PyInstaller 构建 onedir..." -ForegroundColor Yellow
    Push-Location $RepoRoot
    try {
        & python -m PyInstaller packaging\doc_tool.spec --noconfirm --clean
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller 构建失败 (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }
    Write-Host "  PyInstaller 构建完成。" -ForegroundColor Green
} else {
    Write-Host "[2/5] 跳过 PyInstaller 构建。" -ForegroundColor DarkGray
}

# 产物内容校验：确认 Qt/python313 已打包（site-packages 的 PySide6 可能残缺，
# 未挂载 vendored 运行时会打出缺 Qt 的坏包，这里确定性拦截）
if (-not $SkipPyInstaller) {
    Write-Host "  产物内容校验..." -ForegroundColor Yellow
    $InternalDir = "$RepoRoot\dist\DocTool\_internal"
    foreach ($Need in @('python313.dll', 'Qt6Core.dll', 'shiboken6.abi3.dll')) {
        if (-not (Test-Path "$InternalDir\$Need")) {
            throw "构建产物缺少 $InternalDir\$Need——请确认 PYTHONPATH 挂载了 build\pyside-runtime（直接运行 python -m PyInstaller 会用到残缺的 site-packages PySide6）。"
        }
    }
    Write-Host "  产物内容校验通过。" -ForegroundColor Green
}

# --- 透明加密加固：.pyd -> .dll、scripts/*.py -> .pyc ---
# 亿赛通 DocGuard 类客户端会把 .pyd/.py 密文落盘且不给 DocTool.exe 透明解密，
# 原地启动报 "%1 不是有效的 Win32 应用程序"；改写为策略不加密的扩展名后规避。
if (-not $SkipPyInstaller) {
    & "$PSScriptRoot\harden_dist.ps1" -RepoRoot $RepoRoot
}

# 构建后必须扫描本次产物；只在构建前扫描旧 dist 无法阻断本次意外打包。
Push-Location $RepoRoot
try {
    & python packaging\scan_leaks.py --strict --dist-dir "dist\DocTool"
    if ($LASTEXITCODE -ne 0) {
        throw "构建产物允许清单/泄漏扫描失败 (exit $LASTEXITCODE)"
    }
} finally {
    Pop-Location
}

# --- 阶段 3：冒烟测试 ---
# 1.4.3 起：先对全部未签名 PE 做代码签名（scripts\cert-out 或 CODE_SIGNING_*
# 环境变量提供签名材料，二者都缺时自动跳过），让冻结冒烟测试签后产物。
& "$PSScriptRoot\sign_artifacts.ps1" -Target "$RepoRoot\dist\DocTool"

if (-not $SkipTests) {
    Write-Host "[3/5] 冻结应用冒烟测试..." -ForegroundColor Yellow
    Push-Location $RepoRoot
    try {
        & python scripts\tests\test_frozen_smoke.py
        if ($LASTEXITCODE -ne 0) {
            throw "冒烟测试失败 (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }
    Write-Host "  冒烟测试通过。" -ForegroundColor Green
} else {
    Write-Host "[3/5] 跳过冒烟测试。" -ForegroundColor DarkGray
}

# --- 阶段 4：Inno Setup 编译 ---
Write-Host "[4/5] Inno Setup 编译安装器..." -ForegroundColor Yellow

# 安装器随带诊断脚本（installer.iss 从 dist\ 引用 diagnose.cmd）：
# 把启动脚本与基线已刷新的诊断脚本暂存进 dist\。
& "$PSScriptRoot\stage_dist.ps1" -RepoRoot $RepoRoot
if ($LASTEXITCODE -gt 0) { throw "dist 暂存失败" }

# 查找 ISCC.exe
$IsccPaths = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
)
$Iscc = $null
foreach ($path in $IsccPaths) {
    if ($path -and (Test-Path $path)) {
        $Iscc = $path
        break
    }
}

if ($SkipInstaller) {
    Write-Host "  已显式跳过安装器编译。" -ForegroundColor DarkGray
    $SetupExe = $null
} elseif ($Iscc) {
    Push-Location "$RepoRoot\packaging"
    try {
        & $Iscc "installer.iss"
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup 编译失败 (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }
    $SetupExe = "$RepoRoot\packaging\Output\DocTool-Setup-$Version.exe"
    if (Test-Path $SetupExe) {
        $Size = [math]::Round((Get-Item $SetupExe).Length / 1MB, 1)
        Write-Host "  安装器构建完成: $SetupExe ($Size MB)" -ForegroundColor Green
        # 安装器自签名：必须在安装级冒烟与最终 SHA-256 之前完成。
        & "$PSScriptRoot\sign_artifacts.ps1" -Target $SetupExe
        if (-not $SkipTests) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File `
                "$RepoRoot\scripts\tests\test_installer_smoke.ps1" -InstallerPath $SetupExe
            if ($LASTEXITCODE -ne 0) {
                throw "安装级冒烟测试失败 (exit $LASTEXITCODE)"
            }
        }
    } else {
        throw "安装器未生成: $SetupExe"
    }
} else {
    throw "Inno Setup (ISCC.exe) 未安装；如只需 onedir，请显式使用 -SkipInstaller。"
}

# --- 阶段 5：生成 SHA-256 和依赖清单 ---
Write-Host "[5/5] 生成 SHA-256 和依赖清单..." -ForegroundColor Yellow

$DistDir = "$RepoRoot\dist\DocTool"
$ReleaseDir = "$RepoRoot\packaging\Output"
if (-not (Test-Path $ReleaseDir)) {
    New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
}

# SHA-256（安装器）
if ($SetupExe -and (Test-Path $SetupExe)) {
    $Hash = (Get-FileHash $SetupExe -Algorithm SHA256).Hash
    $HashFile = "$SetupExe.sha256"
    "$Hash  $(Split-Path $SetupExe -Leaf)" | Out-File -FilePath $HashFile -Encoding ascii -NoNewline
    Write-Host "  SHA-256: $Hash" -ForegroundColor Green
    Write-Host "  哈希文件: $HashFile" -ForegroundColor Green
}

# 依赖清单（SBOM）
$SbomFile = "$ReleaseDir\DocTool-$Version-sbom.txt"
$SbomContent = @"
Doc Tool $Version 依赖清单（SBOM）
=====================================
生成时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

运行依赖（打包进应用）
----------------------
PyYAML 6.0.3        MIT License
lxml 6.1.1          BSD License
Pillow 12.3.0       MIT-CMU License
pywin32 312         PSF-2.0 License
PySide6 6.8.3       LGPL-3.0 / GPL-3.0 License
Python 3.13         PSF-2.0 License

构建依赖（不打包）
------------------
PyInstaller $PyInstallerVer  GPL-2.0-or-later / BSD License
Inno Setup 6        Inno Setup License

应用文件清单
------------
入口: DocTool.exe (GUI)
入口: doc-tool-cli.exe (CLI)
内核: _internal/scripts/*.py
资源: _internal/doc_tool/resources/default_project.yml
许可: _internal/THIRD_PARTY_LICENSES.txt

第三方库
--------
_internal/lxml/     libxml2/libxslt XML 解析
_internal/PIL/      Pillow 图片处理
_internal/yaml/     PyYAML YAML 解析
_internal/win32/    pywin32 COM 自动化
_internal/PySide6/  Qt Widgets 桌面 UI（仅 QtCore/QtGui/QtWidgets）
"@
$SbomContent | Out-File -FilePath $SbomFile -Encoding utf8
Write-Host "  依赖清单: $SbomFile" -ForegroundColor Green

$CycloneFile = "$ReleaseDir\DocTool-$Version.cdx.json"
$SpdxFile = "$ReleaseDir\DocTool-$Version.spdx.json"
Push-Location $RepoRoot
try {
    & python packaging\generate_sbom.py `
        --requirements requirements.txt `
        --requirements requirements-build.txt `
        --cyclonedx $CycloneFile `
        --spdx $SpdxFile
    if ($LASTEXITCODE -ne 0) { throw "结构化 SBOM 生成失败 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}
Write-Host "  CycloneDX: $CycloneFile" -ForegroundColor Green
Write-Host "  SPDX: $SpdxFile" -ForegroundColor Green

# 可审计发布说明（版本/提交/校验和/SBOM 摘要）
$ReleaseNotesFile = "$ReleaseDir\release-notes.md"
$ReleaseNotesArgs = @("--output", $ReleaseNotesFile)
if ($SetupExe -and (Test-Path $SetupExe)) {
    $ReleaseNotesArgs += @("--setup-exe", $SetupExe)
}
$ReleaseNotesArgs += @("--sbom", $SbomFile)
Push-Location $RepoRoot
try {
    & python packaging\generate_release_notes.py @ReleaseNotesArgs
    if ($LASTEXITCODE -ne 0) { throw "发布说明生成失败 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}
Write-Host "  发布说明: $ReleaseNotesFile" -ForegroundColor Green

Write-Host ""
Write-Host "=== 构建完成 ===" -ForegroundColor Cyan
if ($SetupExe) {
    Write-Host "安装器: $SetupExe" -ForegroundColor White
}
Write-Host "依赖清单: $SbomFile" -ForegroundColor White
Write-Host "CycloneDX: $CycloneFile" -ForegroundColor White
Write-Host "SPDX: $SpdxFile" -ForegroundColor White
Write-Host "发布说明: $ReleaseNotesFile" -ForegroundColor White
