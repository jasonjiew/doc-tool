# DocTool clean-machine repro diagnostics (ASCII-only output).
# Paste this whole file into a PowerShell window on the affected machine
# (no admin needed), or run:  powershell -ExecutionPolicy Bypass -File this.ps1
# It writes a report to  Desktop\doctool-clean-repro.txt  and prints to console.
# Purpose: collect the facts needed to explain why the INSTALLED 1.4.4 app
# fails with 'DLL load failed while importing Shiboken' while the PORTABLE
# package works on the same machine.

$ErrorActionPreference = 'SilentlyContinue'
$out = Join-Path $env:USERPROFILE 'Desktop\doctool-clean-repro.txt'
'' | Set-Content -Path $out -Encoding UTF8
function L($m) { $m | Add-Content $out; Write-Host $m }

function TryRun($exe, $wd, $label) {
    $p = Start-Process -FilePath $exe -WorkingDirectory $wd -PassThru
    Start-Sleep -Seconds 6
    $a = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if ($a) {
        L ("  OK    " + $label + "   (title='" + $a.MainWindowTitle + "')")
        Stop-Process $p.Id -Force
    } else {
        $tail = ''
        $lg = Join-Path $env:TEMP 'DocTool-startup.log'
        if (Test-Path $lg) {
            $err = Get-Content $lg -Tail 20 | Where-Object { $_ -match 'import error|error:' }
            if ($err) { $tail = ($err | Select-Object -Last 1) }
        }
        L ("  FAIL  " + $label + "   [" + $tail + "]")
    }
}

L "==== DocTool clean-machine repro ===="
L ("when: " + (Get-Date) + "   user: " + $env:USERNAME)
$os = Get-CimInstance Win32_OperatingSystem
L ("os  : " + $os.Caption + "  build " + $os.BuildNumber + "  arch " + $env:PROCESSOR_ARCHITECTURE)
$mp = Get-MpComputerStatus
if ($mp) {
    L ("defender: realtime=" + $mp.RealTimeProtectionEnabled + "  CFA=" + $mp.ControlledFolderAccessProtection + "  ASR=" + $mp.AttackSurfaceReductionRulesState)
} else {
    L "defender: n/a (query failed)"
}
L '--- security software processes (name matches only) ---'
tasklist | Select-String -Pattern 'esafe|safenet|ipguard|ipf_|huorong|hips|360|kaspersky|symantec|mcafee|MsMpEng|edr|dlp|sophos|trend' | ForEach-Object { L ('  ' + $_.Line.Trim()) }
L '--- python on PATH / stray python dlls in PATH dirs ---'
($env:PATH -split ';') | Where-Object { $_ } | ForEach-Object {
    if ($_ -match 'python|conda') { L ('  PATH: ' + $_) }
    $hit = Get-ChildItem -LiteralPath $_ -Filter 'python*.dll' -ErrorAction SilentlyContinue | Select-Object -First 3
    foreach ($h in $hit) { L ('  DLL-in-PATH: ' + (Join-Path $_ $h.Name) + '  size=' + $h.Length) }
}
where.exe python 2>$null | ForEach-Object { L ('  where python: ' + $_) }
L '--- installed app files vs official 1.4.4 (size + sha256) ---'
$inst = Join-Path $env:LOCALAPPDATA 'DocTool'
$official = @(
    @('DocTool.exe', '6699016', ''),
    @('doc-tool-cli.exe', '6303056', ''),
    @('_internal\python313.dll', '6129496', ''),
    @('_internal\python3.dll', '72536', 'CBC4876275178244905EE45A9EE6EC9FA4BFB9AAD6209A03B756D38A186F80D1'),
    @('_internal\base_library.zip', '1402481', ''),
    @('_internal\base_library.zip.bak', '1402481', ''),
    @('_internal\shiboken6\Shiboken.pyd', '32392', 'D823883139737F6591DB4CCE513CB7CF464636BA2D38525AB9894E2F0017DA6C'),
    @('_internal\PySide6\QtCore.pyd', '3442824', 'BA4413C25ECC3FB6F0456287CE8DD32C72225A45F42A0AA96F91C4A650A96B65'),
    @('_internal\PySide6\QtGui.pyd', '3992200', '8934AE4A884F87990B30BDB1BF8395AEA2A3FB558F472EE5C1890E879E59BAAB'),
    @('_internal\PySide6\QtWidgets.pyd', '5824648', 'AE79CC3E2715B18AA8800508BCCD953ECA7E627256302748AA7F8BA6C8717211'),
    @('_internal\msvcp140.dll', '565384', '38EA04A8369A8D578F194D50F9D050CD04821CE09EE1BC92AFF755D12E8421ED'),
    @('_internal\vcruntime140.dll', '120400', '052AD6A20D375957E82AA6A3C441EA548D89BE0981516CA7EB306E063D5027F4')
)
foreach ($row in $official) {
    $fp = Join-Path $inst $row[0]
    if (Test-Path $fp) {
        $i = Get-Item $fp
        $h = (Get-FileHash $fp -Algorithm SHA256).Hash
        $flag = ''
        if ($i.Length -ne [long]$row[1]) { $flag = '   <== SIZE MISMATCH' }
        elseif ($row[2] -and $h -ne $row[2]) { $flag = '   <== HASH MISMATCH' }
        L ("  {0}  size={1} (exp {2})  sha={3}{4}" -f $row[0], $i.Length, $row[1], $h, $flag)
    } else {
        L ('  ' + $row[0] + '   MISSING')
    }
}
L '--- tests (each waits 6s) ---'
if (Test-Path (Join-Path $inst 'DocTool.exe')) {
    TryRun (Join-Path $inst 'DocTool.exe') $inst '1. installed exe direct (cwd=install dir)'
    $cl = Get-ChildItem $inst -Filter '*DocTool.cmd' | Select-Object -First 1
    if ($cl) {
        $p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', ('"' + $cl.FullName + '"') -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 8
        $a = Get-Process DocTool -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($a) { L ("  OK    2. installed via launcher cmd (title='" + $a.MainWindowTitle + "')"); Stop-Process $a.Id -Force } else { L '  FAIL  2. installed via launcher cmd' }
    }
    $targets = @((Join-Path $env:TEMP 'DocToolReloc'), (Join-Path $env:USERPROFILE 'Desktop\DocToolReloc'), (Join-Path $env:LOCALAPPDATA 'DocToolReloc'))
    if (Test-Path 'D:\') { $targets += 'D:\DocToolReloc' }
    foreach ($t in $targets) {
        if (Test-Path $t) { Remove-Item $t -Recurse -Force }
        Copy-Item -LiteralPath $inst -Destination $t -Recurse
        if (Test-Path (Join-Path $t 'DocTool.exe')) {
            TryRun (Join-Path $t 'DocTool.exe') $t ('3. copy of install dir at ' + $t)
        } else {
            L ('  SKIP ' + $t + ' (copy failed - permissions?)')
        }
    }
} else {
    L ('INSTALL NOT FOUND at ' + $inst)
}
L '--- optional: portable zip relocated into AppData ---'
$zip = Read-Host 'Path to the WORKING portable zip (or Enter to skip)'
if ($zip -and (Test-Path $zip)) {
    $t = Join-Path $env:LOCALAPPDATA 'PortableReloc'
    if (Test-Path $t) { Remove-Item $t -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $t -Force
    $exe = Get-ChildItem $t -Recurse -Filter 'DocTool.exe' | Select-Object -First 1
    if ($exe) {
        TryRun $exe.FullName (Split-Path $exe.FullName) ('4. portable exe at ' + $exe.DirectoryName)
    }
} else {
    L '  skipped'
}
L '==== end ===='
L ('report: ' + $out)
