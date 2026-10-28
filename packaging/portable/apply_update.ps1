# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    便携版外部原子切换与自动回滚脚本。

.DESCRIPTION
    由主进程在下载并解压便携包到 .upgrade_staging 后以脱离进程拉起。
    1. 等待原主进程 PID 退出。
    2. 将原 DocTool 目录重命名为 DocTool.prev 备份。
    3. 将 .upgrade_staging\DocTool 切入为目标 DocTool 目录，并同步受控启动脚本。
    4. 执行启动自检；若失败则自动回滚还原 DocTool.prev，确保旧版完好可用。
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir,

    [Parameter(Mandatory = $true)]
    [string]$StagingDir,

    [Parameter(Mandatory = $true)]
    [int]$PidToWait,

    [string]$ExeToLaunch = "",
    [string]$LogFile = ""
)

$ErrorActionPreference = "Continue"

if (-not $LogFile) {
    $LogFile = Join-Path $TargetDir "update.log"
}

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    try {
        $line | Out-File -FilePath $LogFile -Append -Encoding utf8
    } catch {
        # 忽略写日志异常
    }
}

Write-Log "=== 开始执行便携版在线升级 ==="
Write-Log "目标目录: $TargetDir"
Write-Log "暂存目录: $StagingDir"
Write-Log "等待进程 PID: $PidToWait"

# 1. 等待主进程退出（最多等待 30 秒）
if ($PidToWait -gt 0) {
    $waited = 0
    while ($waited -lt 60) {
        $proc = Get-Process -Id $PidToWait -ErrorAction SilentlyContinue
        if (-not $proc) {
            break
        }
        Start-Sleep -Milliseconds 500
        $waited++
    }

    $proc = Get-Process -Id $PidToWait -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Log "错误: 等待主进程 $PidToWait 退出超时，升级终止。"
        exit 1
    }
}
Write-Log "主进程已退出，开始目录切换..."

$docToolDir = Join-Path $TargetDir "DocTool"
$docToolPrev = Join-Path $TargetDir "DocTool.prev"

# 暂存中新的 DocTool 目录位置
$newDocTool = Join-Path $StagingDir "DocTool"
if (-not (Test-Path $newDocTool)) {
    # 可能是直接解压到 StagingDir
    $newDocTool = $StagingDir
}

# 2. 备份原版本：DocTool -> DocTool.prev
if (Test-Path $docToolPrev) {
    try {
        Remove-Item $docToolPrev -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Log "警告: 清理旧备份 DocTool.prev 失败: $_"
    }
}

$backedUp = $false
if (Test-Path $docToolDir) {
    try {
        Rename-Item -Path $docToolDir -NewName "DocTool.prev" -Force -ErrorAction Stop
        $backedUp = $true
        Write-Log "已备份原目录为 DocTool.prev"
    } catch {
        Write-Log "错误: 备份原 DocTool 目录失败: $_"
        exit 1
    }
}

# 3. 移动新版本目录
$switchSuccess = $false
try {
    Move-Item -Path $newDocTool -Destination $docToolDir -Force -ErrorAction Stop
    $switchSuccess = $true
    Write-Log "已切换新版本至 DocTool"
} catch {
    Write-Log "错误: 切换新版本目录失败: $_"
}

# 同步根目录受控脚本（如果暂存中包含）
foreach ($scriptName in @("启动DocTool.cmd", "preflight.ps1", "diagnose.cmd", "apply_update.ps1")) {
    $srcScript = Join-Path $StagingDir $scriptName
    if (Test-Path $srcScript) {
        try {
            Copy-Item -Path $srcScript -Destination (Join-Path $TargetDir $scriptName) -Force
            Write-Log "已更新根目录脚本: $scriptName"
        } catch {
            Write-Log "警告: 更新根目录脚本 $scriptName 失败: $_"
        }
    }
}

# 4. 验证与回滚检查
$preflight = Join-Path $TargetDir "preflight.ps1"
$verifyFailed = $false

if (-not $switchSuccess) {
    $verifyFailed = $true
} elseif (Test-Path $preflight) {
    try {
        Write-Log "执行 preflight 预检..."
        $preflightOut = & powershell -NoProfile -ExecutionPolicy Bypass -File $preflight -DistDir $docToolDir 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "错误: 新版本预检失败: $preflightOut"
            $verifyFailed = $true
        } else {
            Write-Log "新版本预检通过。"
        }
    } catch {
        Write-Log "错误: 运行 preflight 抛出异常: $_"
        $verifyFailed = $true
    }
}

# 回滚机制
if ($verifyFailed) {
    Write-Log ">>> 升级验证未通过，执行自动回滚 <<<"
    if (Test-Path $docToolDir) {
        Remove-Item $docToolDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($backedUp -and (Test-Path $docToolPrev)) {
        Rename-Item -Path $docToolPrev -NewName "DocTool" -Force -ErrorAction SilentlyContinue
        Write-Log "已回滚还原原 DocTool 目录。"
    }
    exit 2
}

# 5. 清理暂存目录
try {
    if (Test-Path $StagingDir) {
        Remove-Item $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "已清理暂存目录。"
    }
} catch {
    # 忽略暂存清理异常
}

# 6. 重启应用
if (-not $ExeToLaunch) {
    $ExeToLaunch = Join-Path $docToolDir "DocTool.exe"
}

if (Test-Path $ExeToLaunch) {
    Write-Log "启动新版本应用: $ExeToLaunch"
    Start-Process -FilePath $ExeToLaunch
} else {
    $cmd = Join-Path $TargetDir "启动DocTool.cmd"
    if (Test-Path $cmd) {
        Write-Log "启动脚本: $cmd"
        Start-Process -FilePath $cmd
    }
}

Write-Log "=== 便携版升级成功完成 ==="
exit 0
