# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    对 Doc Tool 产物做 Authenticode 代码签名（可复用，构建脚本与手工共用）。

.DESCRIPTION
    签名材料与优先级：
      1. 环境变量 CODE_SIGNING_PFX / CODE_SIGNING_PASSWORD（CI 用，两个都要）；
      2. 仓库外 CODE_SIGNING_DIR（默认 ~/.doctool/signing）中的
         codesign.pfx + pfx-password.txt；不得从源码目录读取私钥。
    两者都没有时跳过签名并返回 0（不阻断未配置签名的内部构建），输出提示。

    行为要点：
    - 只签当前未签名的 PE（Status 为 NotSigned）；已有效签名的文件
      （如 python313.dll 的 PSF 签名、系统 DLL 的微软签名）保留不动。
    - 新版 signtool（10.0.28000，Windows 11 SDK）按扩展名拒绝签 .pyd：
      “This file format cannot be signed because it is not recognized”。
      本脚本按内容等价改用临时 .dll 替身签名后替换回原路径——Authenticode
      只看文件内容不看文件名，签名仍然有效。（2026-08 本机实测）
    - 全部签名发生在 PowerShell 可信进程链内，规避终端安全软件对 .pyd
      写入的过滤篡改。
    - 带 RFC3161 时间戳（默认 DigiCert），证书过期后签名仍有效。

.PARAMETER Target
    要签名的目录（递归签全部未签名 PE: exe/dll/pyd）或单个文件。

.PARAMETER TimestampUrl
    RFC3161 时间戳服务地址；传空串则不盖时间戳（不推荐）。

.EXAMPLE
    .\packaging\sign_artifacts.ps1 -Target dist\DocTool
    .\packaging\sign_artifacts.ps1 -Target packaging\Output\DocTool-Setup-1.4.3.exe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Target,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path

# --- 1. 签名材料 ---
$pfx = $env:CODE_SIGNING_PFX
$password = $env:CODE_SIGNING_PASSWORD
$signingDir = $env:CODE_SIGNING_DIR
if (-not $signingDir) { $signingDir = Join-Path $env:USERPROFILE ".doctool\signing" }
if ([string]::IsNullOrWhiteSpace($pfx)) {
    $localPfx = Join-Path $signingDir "codesign.pfx"
    if (Test-Path -LiteralPath $localPfx) { $pfx = $localPfx }
}
if (-not $pfx) {
    Write-Host "未配置签名材料（CODE_SIGNING_PFX/PASSWORD 或仓库外 CODE_SIGNING_DIR），跳过签名。" -ForegroundColor DarkGray
    return
}
if (-not (Test-Path -LiteralPath $pfx -PathType Leaf)) { throw "PFX 不存在: $pfx" }
$pfx = (Resolve-Path -LiteralPath $pfx).Path
if ($pfx.StartsWith($RepoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "签名私钥必须位于仓库外，请配置 CODE_SIGNING_PFX 或 CODE_SIGNING_DIR。"
}
if ([string]::IsNullOrWhiteSpace($password)) {
    $localPwFile = [IO.Path]::GetFullPath((Join-Path $signingDir "pfx-password.txt"))
    if ($localPwFile.StartsWith($RepoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "签名密码文件必须位于仓库外。"
    }
    if (Test-Path -LiteralPath $localPwFile) {
        $localPwFile = (Resolve-Path -LiteralPath $localPwFile).Path
        if ($localPwFile.StartsWith($RepoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "签名密码文件必须位于仓库外。"
        }
        $password = [IO.File]::ReadAllText($localPwFile).Trim()
    }
}
if ([string]::IsNullOrWhiteSpace($password)) { throw "缺少签名密码，请配置 CODE_SIGNING_PASSWORD 或外部密码文件。" }

# --- 2. signtool ---
$signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
    $roots = @(
        "C:\Program Files (x86)\Windows Kits\10\bin",
        "C:\Program Files\Windows Kits\10\bin",
        "D:\Program Files (x86)\Windows Kits\10\bin"
    ) | Where-Object { Test-Path $_ } | ForEach-Object {
        Get-ChildItem $_ -Directory | Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" }
    }
    $signtool = $roots | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $signtool) { throw "未找到 signtool.exe，请安装 Windows SDK（Signing Tools）。" }

# --- 3. 收集待签文件 ---
$item = Get-Item (Resolve-Path $Target)
if ($item.PSIsContainer) {
    $files = Get-ChildItem $item.FullName -Recurse -File -Include *.exe, *.dll, *.pyd |
        Where-Object { (Get-AuthenticodeSignature $_.FullName).Status -eq 'NotSigned' }
} else {
    $files = @($item)
}
if ($files.Count -eq 0) {
    Write-Host "没有需要签名的文件（$Target 均已签名或无 PE 文件）。" -ForegroundColor DarkGray
    return
}

# --- 4. 签名（.pyd 走替身） ---
$signed = 0
$failed = @()
foreach ($f in $files) {
    $signPath = $f.FullName
    $standin = $null
    if ($f.Extension -ieq '.pyd') {
        # signtool(28000) 拒签 .pyd 扩展名：复制替身成 .dll，签完替换回原文件
        $standin = $f.FullName + ".sigtmp.dll"
        Copy-Item -LiteralPath $f.FullName -Destination $standin -Force
        $signPath = $standin
    }
    $args = @("sign", "/fd", "SHA256", "/f", $pfx, "/p", $password)
    if ($TimestampUrl) { $args += @("/tr", $TimestampUrl, "/td", "SHA256") }
    $args += $signPath
    & $signtool @args 2>&1 | Out-Null
    $ok = ($LASTEXITCODE -eq 0)
    if (-not $ok) {
        # 重试一次（时间戳服务偶发超时）
        & $signtool @args 2>&1 | Out-Null
        $ok = ($LASTEXITCODE -eq 0)
    }
    if ($standin) {
        if ($ok) {
            Move-Item -LiteralPath $standin -Destination $f.FullName -Force
        } else {
            Remove-Item -LiteralPath $standin -Force -ErrorAction SilentlyContinue
        }
    }
    if ($ok) { $signed++ } else { $failed += $f.FullName }
}

Write-Host "签名完成: $signed 个文件（$Target）" -ForegroundColor Green
if ($failed.Count -gt 0) {
    $failed | ForEach-Object { Write-Host "  签名失败: $_" -ForegroundColor Red }
    throw "有 $($failed.Count) 个文件签名失败"
}
