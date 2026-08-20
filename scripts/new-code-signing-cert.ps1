<#
.SYNOPSIS
    一键生成代码签名证书（自签名）并可选对文件进行签名。

.DESCRIPTION
    提供三种模式：
    1. 默认：生成自签名代码签名证书并导出为 PFX（内部测试 / 内网分发用）。
    2. -MakeCsr：生成密钥 + CSR（证书签名请求），用于向商业 CA 申请正式证书。
    3. -SignFile：生成（或复用已有）证书后，用 signtool 对指定文件签名。

    详细说明见 docs/code-signing-certificate.md

.EXAMPLE
    # 生成自签名证书并导出 codesign.pfx
    .\new-code-signing-cert.ps1 -CompanyName "某某科技有限公司" -Password "YourP@ss123"

    # 生成 CSR 用于申请商业证书
    .\new-code-signing-cert.ps1 -MakeCsr -CompanyName "某某科技有限公司" -OutputDir .\csr-out

    # 生成证书并直接签名一个 exe
    .\new-code-signing-cert.ps1 -CompanyName "某某科技有限公司" -Password "YourP@ss123" `
        -SignFile ".\dist\myapp.exe" -TimestampUrl "http://timestamp.digicert.com"

    # 复用已有 PFX 只做签名
    .\new-code-signing-cert.ps1 -PfxFile ".\codesign.pfx" -Password "YourP@ss123" -SignFile ".\myapp.exe"

.NOTES
    依赖：Windows 10/11 或 Windows Server 2016+（New-SelfSignedCertificate）。
    签名需要 Windows SDK 的 signtool.exe（未找到时提示安装）。
#>
[CmdletBinding()]
param(
    # 公司名称（证书主体 CN/O，CSR 模式必填）
    [string]$CompanyName = "My Company",

    # PFX 导出密码（生成证书模式必填）
    [string]$Password,

    # 输出目录（默认脚本所在目录下 cert-out）
    [string]$OutputDir,

    # 证书有效期（天），自签名模式默认 1095（3 年）
    [int]$Days = 1095,

    # 仅生成 CSR 用于申请商业证书（不生成证书）
    [switch]$MakeCsr,

    # 要签名的文件路径（可选，同时执行签名）
    [string]$SignFile,

    # 复用已有的 PFX 文件（不再生成新证书）
    [string]$PfxFile,

    # 生成后导入本机「受信任的根证书颁发机构 / 受信任的发布者」（测试机用）
    [switch]$Trust,

    # 时间戳服务器（RFC3161），为空则不盖时间戳（强烈建议填写）
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

# ---------- 路径准备 ----------
if (-not $OutputDir) {
    $OutputDir = Join-Path $PSScriptRoot "cert-out"
}
$null = New-Item -ItemType Directory -Force -Path $OutputDir

# ---------- 模式一：生成 CSR（申请商业证书） ----------
if ($MakeCsr) {
    if (-not $Password) {
        # CSR 模式私钥也需要保护口令
        $Password = Read-Host "请输入 PFX/私钥 导出密码" -AsSecureString
        $Password = [System.Net.NetworkCredential]::new("", $Password).Password
    }
    $csrPath = Join-Path $OutputDir "codesign.csr"
    $pfxPath = Join-Path $OutputDir "codesign-request.pfx"
    $cerPath = Join-Path $OutputDir "codesign-request.cer"

    Write-Host "==> 正在生成密钥对与 CSR（提交给商业 CA 用）..." -ForegroundColor Cyan

    # 全部在内存中完成（.NET CertificateRequest）：生成 RSA-2048 密钥 → CSR（PEM），
    # 并用同一把密钥生成自签名占位证书，导出 PFX 私钥备份 / CER 公钥。
    # 不依赖证书库，也绕开 New-CertificateRequest——Windows 内置 PKI 模块没有该
    # cmdlet（那是第三方 PSPKI 模块的函数），且 -KeySpec Signature 的旧 CSP 密钥
    # 不支持 SHA-256 签名，无法生成 CSR。
    try {
        $rsaKey = [System.Security.Cryptography.RSA]::Create(2048)
        $subject = "CN=$CompanyName, O=$CompanyName, C=CN"
        $csrRequest = New-Object System.Security.Cryptography.X509Certificates.CertificateRequest(
            $subject, $rsaKey,
            [System.Security.Cryptography.HashAlgorithmName]::SHA256,
            [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
        )
        # .NET Framework 的 CreateSigningRequest() 返回 DER 字节数组（byte[]），
        # 需显式转 base64（仅 .NET Core 5+ 才直接返回 base64 字符串）。
        $csrBytes = $csrRequest.CreateSigningRequest()
        $base64 = [System.Convert]::ToBase64String($csrBytes)
        $wrapped = ($base64 -replace '(.{64})', ('$1' + "`r`n")).TrimEnd()
        $pem = "-----BEGIN CERTIFICATE REQUEST-----`r`n" + $wrapped + "`r`n-----END CERTIFICATE REQUEST-----"
        [System.IO.File]::WriteAllText($csrPath, $pem, [System.Text.Encoding]::ASCII)

        # 私钥备份：同一把密钥生成自签名占位证书并导出 PFX/CER。
        $selfSigned = $csrRequest.CreateSelfSigned((Get-Date).AddDays(-1), (Get-Date).AddDays($Days))
        [System.IO.File]::WriteAllBytes(
            $pfxPath,
            $selfSigned.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Pfx, $Password)
        )
        [System.IO.File]::WriteAllBytes(
            $cerPath,
            $selfSigned.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
        )
    } catch {
        throw "生成 CSR 失败: $($_.Exception.Message)`n可改用 certreq 或 OpenSSL 生成 CSR（见 docs/code-signing-certificate.md 第 1.3 / 2.3 / 2.4 节）。"
    }

    Write-Host "CSR 已生成: $csrPath" -ForegroundColor Green
    Write-Host "私钥备份 PFX 已生成: $pfxPath" -ForegroundColor Green
    Write-Host "请将此文件提交给 CA（DigiCert / Sectigo / GlobalSign 等）申请正式证书。"
    Write-Host "注意: 私钥备份在 $pfxPath，请妥善保管、勿外传；CA 返回证书后用它装配签名证书。"
    exit 0
}

# ---------- 模式二 / 三：生成（或复用）自签名证书 ----------
if (-not $Password) {
    $Password = Read-Host "请输入 PFX 导出密码" -AsSecureString
    $Password = [System.Net.NetworkCredential]::new("", $Password).Password
}

$pfxPath = Join-Path $OutputDir "codesign.pfx"
$cerPath = Join-Path $OutputDir "codesign.cer"

if ($PfxFile) {
    # 复用已有证书
    $pfxPath = (Resolve-Path $PfxFile).Path
    Write-Host "==> 复用已有 PFX: $pfxPath" -ForegroundColor Cyan
} else {
    Write-Host "==> 正在生成自签名代码签名证书..." -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject "CN=$CompanyName, O=$CompanyName, C=CN" `
        -CertStoreLocation Cert:\CurrentUser\My `
        -NotAfter (Get-Date).AddDays($Days) `
        -KeyExportPolicy Exportable `
        -KeySpec Signature

    $securePwd = ConvertTo-SecureString -String $Password -Force -AsPlainText

    # 导出 PFX（含私钥，签名用）
    Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $securePwd | Out-Null
    # 导出 CER（仅公钥，分发给目标机器安装信任用）
    Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null

    Write-Host "PFX 已生成: $pfxPath" -ForegroundColor Green
    Write-Host "CER 已生成: $cerPath（在目标机器双击安装到「受信任的根证书颁发机构」即可信任）" -ForegroundColor Green

    # 可选：导入本机信任（测试机常用）；交互式终端会询问，-Trust 直接导入
    $doImport = $Trust
    if (-not $doImport -and -not [Console]::IsInputRedirected) {
        $answer = Read-Host "是否导入本机「受信任的根证书颁发机构 / 受信任的发布者」？(y/N)"
        $doImport = $answer.Trim() -match "^[yY]"
    }
    if ($doImport) {
        # 用 .NET X509Store 导入（无 UI 弹窗，非交互环境也可用；CurrentUser 无需管理员）
        $trustCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($cerPath)
        foreach ($storeName in @("Root", "TrustedPublisher")) {
            $store = New-Object System.Security.Cryptography.X509Certificates.X509Store($storeName, "CurrentUser")
            $store.Open("ReadWrite")
            $store.Add($trustCert)
            $store.Close()
        }
        Write-Host "已导入本机当前用户信任库（Root / TrustedPublisher）。" -ForegroundColor Green
    }
}

# ---------- 可选：执行签名 ----------
if ($SignFile) {
    if (-not (Test-Path $SignFile)) {
        throw "要签名的文件不存在: $SignFile"
    }

    # 定位 signtool.exe（PATH → 常见目录 → 注册表 KitsRoot10，兼容 C:/D: 盘安装）
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signtool) {
        $searchRoots = @(
            "C:\Program Files (x86)\Windows Kits\10\bin",
            "C:\Program Files\Windows Kits\10\bin"
        )
        $kitsRoot = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots" -ErrorAction SilentlyContinue).KitsRoot10
        if ($kitsRoot) { $searchRoots += (Join-Path $kitsRoot "bin") }

        foreach ($root in $searchRoots) {
            $kits = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending
            foreach ($kit in $kits) {
                $candidate = Join-Path $kit.FullName "x64\signtool.exe"
                if (Test-Path $candidate) { $signtool = $candidate; break }
            }
            if ($signtool) { break }
        }
    }
    if (-not $signtool) {
        throw "未找到 signtool.exe，请先安装 Windows SDK（含 Signing Tools）。"
    }

    $signtoolPath = if ($signtool -is [System.Management.Automation.CommandInfo]) { $signtool.Source } else { $signtool }

    Write-Host "==> 正在签名: $SignFile" -ForegroundColor Cyan
    $args = @("sign", "/fd", "SHA256", "/f", $pfxPath, "/p", $Password)
    if ($TimestampUrl) {
        $args += @("/tr", $TimestampUrl, "/td", "SHA256")
    }
    $args += @((Resolve-Path $SignFile).Path)

    & $signtoolPath @args
    if ($LASTEXITCODE -ne 0) {
        throw "签名失败，signtool 退出码: $LASTEXITCODE"
    }
    Write-Host "签名完成: $SignFile" -ForegroundColor Green

    # 验证
    & $signtoolPath verify /pa /v (Resolve-Path $SignFile).Path
}

Write-Host "全部完成。输出目录: $OutputDir" -ForegroundColor Green
