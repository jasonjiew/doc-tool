# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    生成团队分发便携包：dist\DocTool + 启动脚本 + 诊断脚本 →
    packaging\Output\DocTool-<版本>-portable.zip（+ .sha256）。

.DESCRIPTION
    唯一的便携包装配入口，供以下两处共用，避免两处实现漂移：
      * build_exe.ps1 -Portable（本地一键打包）
      * .gitlab-ci.yml package-installer（tag 流水线）
    装配前先调用 stage_dist.ps1 刷新启动/诊断脚本。
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path }

& (Join-Path $PSScriptRoot "stage_dist.ps1") -RepoRoot $RepoRoot

if (-not $Version) {
    Push-Location $RepoRoot
    try {
        $Version = (& python -c "from doc_tool.domain.version import APP_VERSION; print(APP_VERSION)").Trim()
    } finally {
        Pop-Location
    }
    if (-not $Version) { throw "无法读取 APP_VERSION" }
}

$OutDir = Join-Path $RepoRoot "packaging\Output"
New-Item -ItemType Directory -Force $OutDir | Out-Null
$Zip = Join-Path $OutDir "DocTool-$Version-portable.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }

Push-Location $RepoRoot
try {
    # 1.4.3 起随包携带成员引导与公司自签名证书（成员一键导入信任后，
    # 已签名 exe 不再被安全软件拦截；CI 运行环境无 cert-out，自动跳过证书）。
    $zipItems = @(
        (Join-Path $RepoRoot "dist\DocTool"),
        (Join-Path $RepoRoot "dist\启动DocTool.cmd"),
        (Join-Path $RepoRoot "dist\diagnose.cmd"),
        (Join-Path $RepoRoot "packaging\portable\请先读我.txt"),
        (Join-Path $RepoRoot "packaging\portable\安装证书.cmd")
    )
    $cer = Join-Path $RepoRoot "scripts\cert-out\codesign.cer"
    if (Test-Path $cer) {
        $zipItems += $cer
    } else {
        Write-Warning "未找到 scripts\cert-out\codesign.cer：便携包不含公司证书（CI 环境属预期）。"
    }
    Compress-Archive -Path $zipItems -DestinationPath $Zip -CompressionLevel Optimal
} finally {
    Pop-Location
}

$Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash
"$Hash  DocTool-$Version-portable.zip" | Out-File "$Zip.sha256" -Encoding ascii -NoNewline
$SizeMb = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Write-Host "便携包: $Zip（$SizeMb MB）" -ForegroundColor White
Write-Host "SHA-256: $Hash" -ForegroundColor White
Write-Host "分发说明：整包发给同事，解压后先读「请先读我.txt」——首次双击「安装证书.cmd」" -ForegroundColor DarkGray
Write-Host "          导入公司证书，之后双击「启动DocTool.cmd」启动；" -ForegroundColor DarkGray
Write-Host "          即使直接双击 DocTool.exe，1.4.2+ 也会自动迁移到 %TEMP% 后启动。" -ForegroundColor DarkGray
