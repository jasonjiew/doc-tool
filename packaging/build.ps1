# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    康尚文档工具安装包构建脚本

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
$Version = "1.0.0"

$AppVersion = (& python -c "from doc_tool.domain.version import APP_VERSION; print(APP_VERSION)").Trim()
$InstallerMatch = Select-String -Path "$PSScriptRoot\installer.iss" -Pattern '#define\s+MyAppVersion\s+"([^"]+)"'
$InstallerVersion = $InstallerMatch.Matches[0].Groups[1].Value
if ($Version -ne $AppVersion -or $Version -ne $InstallerVersion) {
    throw "版本不一致: build=$Version app=$AppVersion installer=$InstallerVersion"
}

Write-Host "=== 康尚文档工具安装包构建 ===" -ForegroundColor Cyan
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

# 构建后必须扫描本次产物；只在构建前扫描旧 dist 无法阻断本次意外打包。
Push-Location $RepoRoot
try {
    & python packaging\scan_leaks.py --strict --dist-dir "dist\KonsungDocTool"
    if ($LASTEXITCODE -ne 0) {
        throw "构建产物允许清单/泄漏扫描失败 (exit $LASTEXITCODE)"
    }
} finally {
    Pop-Location
}

# --- 阶段 3：冒烟测试 ---
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
    $SetupExe = "$RepoRoot\packaging\Output\KonsungDocTool-Setup-$Version.exe"
    if (Test-Path $SetupExe) {
        $Size = [math]::Round((Get-Item $SetupExe).Length / 1MB, 1)
        Write-Host "  安装器构建完成: $SetupExe ($Size MB)" -ForegroundColor Green
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

$DistDir = "$RepoRoot\dist\KonsungDocTool"
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
$SbomFile = "$ReleaseDir\KonsungDocTool-$Version-sbom.txt"
$SbomContent = @"
康尚文档工具 $Version 依赖清单（SBOM）
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
PyInstaller 6.14.0  GPL-2.0-or-later / BSD License
Inno Setup 6        Inno Setup License

应用文件清单
------------
入口: KonsungDocTool.exe (GUI)
内核: _internal/scripts/*.py
模板: _internal/templates/*.docx
配置: _internal/config/*.yml
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

$CycloneFile = "$ReleaseDir\KonsungDocTool-$Version.cdx.json"
$SpdxFile = "$ReleaseDir\KonsungDocTool-$Version.spdx.json"
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

Write-Host ""
Write-Host "=== 构建完成 ===" -ForegroundColor Cyan
if ($SetupExe) {
    Write-Host "安装器: $SetupExe" -ForegroundColor White
}
Write-Host "依赖清单: $SbomFile" -ForegroundColor White
Write-Host "CycloneDX: $CycloneFile" -ForegroundColor White
Write-Host "SPDX: $SpdxFile" -ForegroundColor White
