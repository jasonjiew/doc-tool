param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath
)

$ErrorActionPreference = "Stop"
$installer = (Resolve-Path $InstallerPath).Path
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$testRoot = Join-Path $tempBase ("konsung-installer-smoke-" + [guid]::NewGuid().ToString("N"))
$installDir = Join-Path $testRoot "app"
$externalProject = Join-Path $testRoot "external-project"
$sentinel = Join-Path $externalProject "project-data.keep"
$unknownAppFile = Join-Path $installDir "user-owned.keep"

function Invoke-CheckedProcess {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Process failed with exit code $($process.ExitCode): $FilePath"
    }
}

try {
    New-Item -ItemType Directory -Path $externalProject -Force | Out-Null
    Set-Content -LiteralPath $sentinel -Value "preserve" -Encoding ascii

    $installArgs = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        ('/DIR="{0}"' -f $installDir)
    )
    Invoke-CheckedProcess -FilePath $installer -Arguments $installArgs

    $appExe = Join-Path $installDir "KonsungDocTool.exe"
    if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
        throw "Installed application executable is missing: $appExe"
    }

    Set-Content -LiteralPath $unknownAppFile -Value "preserve" -Encoding ascii

    # Run the same version again to exercise repair/overwrite behavior.
    Invoke-CheckedProcess -FilePath $installer -Arguments $installArgs
    if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
        throw "Application executable disappeared after repair install."
    }
    if (-not (Test-Path -LiteralPath $sentinel -PathType Leaf)) {
        throw "External project data was changed by repair install."
    }
    if (-not (Test-Path -LiteralPath $unknownAppFile -PathType Leaf)) {
        throw "Installer deleted an unknown application-directory file during repair."
    }

    $uninstaller = Join-Path $installDir "uninst\unins000.exe"
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        throw "Uninstaller is missing: $uninstaller"
    }
    Invoke-CheckedProcess -FilePath $uninstaller -Arguments @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
    )

    if (Test-Path -LiteralPath $appExe) {
        throw "Managed application executable remains after uninstall."
    }
    if (-not (Test-Path -LiteralPath $sentinel -PathType Leaf)) {
        throw "External project data was deleted by uninstall."
    }
    if (-not (Test-Path -LiteralPath $unknownAppFile -PathType Leaf)) {
        throw "Uninstall recursively deleted an unknown application-directory file."
    }

    Write-Host "[PASS] Silent install, repair, uninstall, and data preservation smoke test."
} finally {
    $uninstaller = Join-Path $installDir "uninst\unins000.exe"
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        try {
            Invoke-CheckedProcess -FilePath $uninstaller -Arguments @(
                "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
            )
        } catch {
            Write-Warning "Cleanup uninstaller failed: $($_.Exception.GetType().Name)"
        }
    }
    $resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
    if ($resolvedTestRoot.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
