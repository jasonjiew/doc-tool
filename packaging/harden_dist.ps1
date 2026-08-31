# Transparent-encryption hardening for the dist tree (idempotent).
#
# On machines with a transparent-encryption client (EsafeNet DocGuard and
# similar), *.pyd / *.py files are stored encrypted at rest and DocTool.exe
# is not a trusted process, so in-place startup fails with 'DLL load failed
# while importing Shiboken' (ERROR_BAD_EXE_FORMAT). The encryption policy
# does not cover *.dll / *.pyc, so this script rewrites the dist tree to use
# only those forms:
#   1) every *.pyd under _internal is rewritten as *.dll (copy = trusted read
#      decrypts the bytes and the new .dll file is stored plaintext; a plain
#      rename would keep the ciphertext on disk);
#   2) _internal\scripts\*.py (runtime-imported kernel modules) are compiled
#      to *.pyc, which SourcelessFileLoader imports without any patching.
# packaging\rthook_hardened_runtime.py (registered via the spec runtime_hooks)
# makes the import system recognize the renamed *.dll extension modules.
#
# ASCII-only: Windows PowerShell 5.1 parses a .ps1 without a BOM as the
# system ANSI codepage.

[CmdletBinding()]
param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path }

$DistDir = Join-Path $RepoRoot "dist\DocTool"
$Internal = Join-Path $DistDir "_internal"
if (-not (Test-Path -LiteralPath $Internal)) {
    Write-Host "harden_dist: $Internal not found - skipping (onefile mode or dist not built yet)." -ForegroundColor DarkGray
    exit 0
}

# 1) *.pyd -> *.dll
$pydCount = 0
Get-ChildItem -LiteralPath $Internal -Recurse -File -Filter *.pyd | ForEach-Object {
    $dst = Join-Path $_.Directory.FullName ($_.BaseName + ".dll")
    if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Force }
    Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
    Remove-Item -LiteralPath $_.FullName -Force
    $pydCount++
}

# 2) scripts\*.py -> *.pyc (same interpreter version as the frozen runtime).
# NOTE: compileall / py_compile both write "<name>.pyc.<pid>" temp files and
# os.replace() them - the transparent-encryption filter driver breaks that
# rename with WinError 17 (ERROR_NOT_SAME_DEVICE). Compile manually and write
# the .pyc bytes directly instead (no rename anywhere).
$scripts = Join-Path $Internal "scripts"
$pyCount = 0
if (Test-Path -LiteralPath $scripts) {
    $pyFiles = @(Get-ChildItem -LiteralPath $scripts -File -Filter *.py)
    if ($pyFiles.Count -gt 0) {
        $pyCompile = @'
import glob, os, sys
from importlib._bootstrap_external import _code_to_timestamp_pyc
d = sys.argv[1]
for p in sorted(glob.glob(os.path.join(d, "*.py"))):
    st = os.stat(p)
    with open(p, "rb") as f:
        src = f.read()
    code = compile(src, p, "exec")
    data = _code_to_timestamp_pyc(code, int(st.st_mtime), st.st_size)
    with open(p + "c", "wb") as f:
        f.write(data)
'@
        $pyCompile | & python - $scripts
        if ($LASTEXITCODE -ne 0) { throw "script compile failed (exit $LASTEXITCODE) on $scripts" }
        foreach ($f in $pyFiles) {
            $pyc = Join-Path $f.Directory.FullName ($f.BaseName + ".pyc")
            if (-not (Test-Path -LiteralPath $pyc)) { throw "compile produced no .pyc for $($f.FullName)" }
            Remove-Item -LiteralPath $f.FullName -Force
            $pyCount++
        }
    }
}

if ($pydCount -gt 0 -or $pyCount -gt 0) {
    Write-Host ("harden_dist: rewrote {0} .pyd -> .dll, compiled {1} scripts/*.py -> .pyc" -f $pydCount, $pyCount) -ForegroundColor Green
} else {
    Write-Host "harden_dist: dist already hardened - nothing to do." -ForegroundColor DarkGray
}
