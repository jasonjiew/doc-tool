# Doc Tool startup pre-flight: verify the headers of the critical files and
# self-repair base_library.zip from its bundled backup when the endpoint
# security/encryption client on this machine has mangled it (typical symptom:
# file grows by 4 KB and loses its header, breaking the embedded Python
# interpreter with 'Failed to start embedded python interpreter!').
#
# Since 1.4.5 this script ALSO launches the app and watches the first seconds
# of startup: after the checks pass, DocTool.exe is started from here and the
# process is watched for up to 8 seconds. A quick nonzero exit means startup
# failed (endpoint security blocking the .pyd loads, or components corrupted
# after the header check) - the reason is captured from DocTool-startup.log so
# the launcher can show it instead of a silent black-window flash.
#
# Output (one line, captured by the launcher):
#   - empty          : all good, app is running
#   - "REPAIRED"     : base_library.zip was corrupt and restored from .bak
#   - "BROKEN: ..."  : a critical file is unreadable / not the expected format
#   - "STARTFAIL: exit=N" : app exited fast with code N; reason written to
#                      %TEMP%\dt_startfail_reason.txt
#   - "NOTSTARTED"   : the app could not be launched from here; the launcher
#                      falls back to starting it directly
#
# ASCII-only: Windows PowerShell 5.1 parses .ps1 without a BOM as the system
# ANSI codepage, so keep this file free of non-ASCII bytes.
$ErrorActionPreference = 'SilentlyContinue'

$b = $env:DT_SRC
if (-not $b) { exit 0 }

function Test-Pe([string]$p) {
    if (-not (Test-Path -LiteralPath $p)) { return $false }
    try {
        $s = [System.IO.File]::OpenRead($p)
        $x = New-Object byte[] 2
        $null = $s.Read($x, 0, 2)
        $s.Dispose()
        return ($x[0] -eq 0x4D -and $x[1] -eq 0x5A)  # MZ
    } catch {
        return $false
    }
}

function Test-Zip([string]$p) {
    if (-not (Test-Path -LiteralPath $p)) { return $false }
    try {
        $s = [System.IO.File]::OpenRead($p)
        $x = New-Object byte[] 2
        $null = $s.Read($x, 0, 2)
        $s.Dispose()
        return ($x[0] -eq 0x50 -and $x[1] -eq 0x4B)  # PK
    } catch {
        return $false
    }
}

function Get-StartupFailureReason {
    $log = Join-Path $env:TEMP 'DocTool-startup.log'
    if (-not (Test-Path -LiteralPath $log)) {
        $log = Join-Path $b 'DocTool-startup.log'
    }
    if (-not (Test-Path -LiteralPath $log)) { return '(no DocTool-startup.log found)' }
    try {
        $content = [System.IO.File]::ReadAllText($log, [System.Text.Encoding]::UTF8)
    } catch {
        return '(cannot read DocTool-startup.log)'
    }
    $lines = @($content -split "`r?`n")
    $last = -1
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -like '====*') { $last = $i; break }
    }
    if ($last -lt 0) { $last = 0 }
    $block = @($lines[$last..($lines.Count - 1)] | Where-Object {
        $_ -match 'import error|error|Exception'
    } | Select-Object -First 3)
    if ($block.Count -eq 0) { return '(startup log has no error lines)' }
    $text = ($block -join ' | ')
    if ($text.Length -gt 400) { $text = $text.Substring(0, 400) }
    # keep only printable ASCII so the launcher's 'type' output is safe
    $text = $text -replace '[^\x20-\x7E]', '?'
    return $text
}

$bad = @()
$repaired = $false

# NOTE: avoid '@($b+'\x', $b+'\y')' - the comma operator binds tighter than '+'
# in PowerShell and would concatenate the paths into one mangled string.
$peFiles = ($b + '\DocTool.exe|' + $b + '\doc-tool-cli.exe|' + $b + '\_internal\python313.dll|' + $b + '\_internal\shiboken6\Shiboken.pyd|' + $b + '\_internal\PySide6\QtCore.pyd|' + $b + '\_internal\PySide6\QtGui.pyd|' + $b + '\_internal\PySide6\QtWidgets.pyd').Split('|')
foreach ($f in $peFiles) {
    if (-not (Test-Pe $f)) { $bad += $f }
}

$bl = $b + '\_internal\base_library.zip'
$bk = $bl + '.bak'

if (Test-Zip $bl) {
    # primary header is fine; still restore when the filter driver inflated it
    if ((Test-Path -LiteralPath $bk) -and (Test-Zip $bk)) {
        if ((Get-Item -LiteralPath $bl).Length -ne (Get-Item -LiteralPath $bk).Length) {
            Copy-Item -LiteralPath $bk -Destination $bl -Force
            if ((Get-Item -LiteralPath $bl).Length -eq (Get-Item -LiteralPath $bk).Length) {
                $repaired = $true
            } else {
                $bad += $bl
            }
        }
    }
} else {
    if ((Test-Path -LiteralPath $bk) -and (Test-Zip $bk)) {
        Copy-Item -LiteralPath $bk -Destination $bl -Force
        if (Test-Zip $bl) {
            $repaired = $true
        } else {
            $bad += $bl
        }
    } else {
        $bad += $bl
    }
}

if ($bad.Count -gt 0) {
    $result = 'BROKEN: ' + (($bad | ForEach-Object { Split-Path $_ -Leaf }) -join ', ')
} else {
    # --- launch the app and watch the first seconds of startup ---
    $result = ''
    $exe = Join-Path $b 'DocTool.exe'
    if (-not (Test-Path -LiteralPath $exe)) {
        $result = 'NOTSTARTED'
    } else {
        try {
            $proc = Start-Process -FilePath $exe -PassThru
            if ($null -eq $proc) {
                $result = 'NOTSTARTED'
            } elseif (-not $proc.WaitForExit(8000)) {
                # still running after 8s -> treat as healthy
            } elseif ($proc.ExitCode -eq 0) {
                # exited on its own with 0 -> nothing to report
            } else {
                $result = 'STARTFAIL: exit=' + $proc.ExitCode
                $reason = Get-StartupFailureReason
                try {
                    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
                    [System.IO.File]::WriteAllText(
                        (Join-Path $env:TEMP 'dt_startfail_reason.txt'),
                        $reason,
                        $utf8NoBom
                    )
                } catch { }
            }
        } catch {
            $result = 'NOTSTARTED'
        }
        if (($result -eq '') -and $repaired) { $result = 'REPAIRED' }
    }
}

# Write the result to a temp file instead of stdout: PowerShell 5.1 can print
# a first-run banner to stdout which a cmd 'for /f' would capture as the
# result, and cmd blocks choke on unexpected stdout content.
$resultFile = Join-Path $env:TEMP 'dt_preflight_result.txt'
try {
    [System.IO.File]::WriteAllText($resultFile, $result, [System.Text.Encoding]::ASCII)
} catch {
    # cannot write the result file - leave it absent so the launcher fails open
}
