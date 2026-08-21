# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    暂存发布目录：把启动脚本与诊断脚本放进 dist\ ，并把诊断基线刷新为本次构建的真实值。

.DESCRIPTION
    - dist\启动DocTool.cmd      ← packaging\portable\启动DocTool.cmd
    - dist\diagnose.cmd        ← packaging\portable\diagnose.cmd（EXP_* 基线按
                                  dist\DocTool 的实际大小/哈希/文件数重写，
                                  避免人工同步漂移）
    便携包（make_portable.ps1 / build_exe.ps1 -Portable）与安装器
    （installer.iss / build.ps1）统一依赖本脚本的产物。
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path }

$DistDir = Join-Path $RepoRoot "dist\DocTool"
$DistRoot = Join-Path $RepoRoot "dist"
$Internal = Join-Path $DistDir "_internal"

foreach ($Need in @(
    (Join-Path $DistDir "DocTool.exe"),
    (Join-Path $DistDir "doc-tool-cli.exe"),
    (Join-Path $Internal "base_library.zip"),
    (Join-Path $Internal "python313.dll")
)) {
    if (-not (Test-Path $Need)) { throw "dist 未就绪，缺少: $Need（请先完成 PyInstaller 构建）" }
}

# 1) 启动脚本
Copy-Item (Join-Path $RepoRoot "packaging\portable\启动DocTool.cmd") $DistRoot -Force

# 2) 诊断脚本：以真实构建产物刷新基线
$bl = Join-Path $Internal "base_library.zip"
$py = Join-Path $Internal "python313.dll"
$gui = Join-Path $DistDir "DocTool.exe"
$cli = Join-Path $DistDir "doc-tool-cli.exe"

$blHash = (Get-FileHash $bl -Algorithm SHA256).Hash.ToLower()
$pyHash = (Get-FileHash $py -Algorithm SHA256).Hash.ToLower()
$appFiles = (Get-ChildItem $DistDir -Recurse -File).Count
$intFiles = (Get-ChildItem $Internal -Recurse -File).Count

$template = Get-Content (Join-Path $RepoRoot "packaging\portable\diagnose.cmd") -Encoding ascii
$patched = $template `
    -replace 'set "EXP_BL_SIZE=.*"', ('set "EXP_BL_SIZE={0}"' -f (Get-Item $bl).Length) `
    -replace 'set "EXP_BL_HASH=.*"', ('set "EXP_BL_HASH={0}"' -f $blHash) `
    -replace 'set "EXP_PY_SIZE=.*"', ('set "EXP_PY_SIZE={0}"' -f (Get-Item $py).Length) `
    -replace 'set "EXP_PY_HASH=.*"', ('set "EXP_PY_HASH={0}"' -f $pyHash) `
    -replace 'set "EXP_GUI_SIZE=.*"', ('set "EXP_GUI_SIZE={0}"' -f (Get-Item $gui).Length) `
    -replace 'set "EXP_CLI_SIZE=.*"', ('set "EXP_CLI_SIZE={0}"' -f (Get-Item $cli).Length) `
    -replace 'set "EXP_APP_FILES=.*"', ('set "EXP_APP_FILES={0}"' -f $appFiles) `
    -replace 'set "EXP_INT_FILES=.*"', ('set "EXP_INT_FILES={0}"' -f $intFiles)

$diagOut = Join-Path $DistRoot "diagnose.cmd"
[void][System.IO.File]::WriteAllLines($diagOut, [string[]]$patched, (New-Object System.Text.ASCIIEncoding))

Write-Host "已暂存: dist\启动DocTool.cmd" -ForegroundColor Green
Write-Host "已暂存: dist\diagnose.cmd（基线已刷新: app=$appFiles internal=$intFiles）" -ForegroundColor Green
