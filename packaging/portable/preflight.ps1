# Doc Tool startup pre-flight: verify the headers of the critical files and
# self-repair base_library.zip from its bundled backup when the endpoint
# security/encryption client on this machine has mangled it (typical symptom:
# file grows by 4 KB and loses its header, breaking the embedded Python
# interpreter with 'Failed to start embedded python interpreter!').
#
# Output (one line, captured by the launcher's for /f):
#   - empty          : all good
#   - "REPAIRED"     : base_library.zip was corrupt and has been restored from
#                      base_library.zip.bak
#   - "BROKEN: ..."  : a critical file is unreadable / not the expected format
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
} elseif ($repaired) {
    $result = 'REPAIRED'
} else {
    $result = ''
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
