# 公司代码签名证书生成指南

> 适用范围：Windows 桌面软件 / 安装包 / 驱动等需要代码签名的场景。
> 配套脚本：`scripts/new-code-signing-cert.ps1`（一键生成自签名证书 + 签名）。

代码签名证书分为两大类，生成方式完全不同：

| 类型 | 用途 | 能否自己生成 | 信任级别 |
|---|---|---|---|
| **商业证书（OV/EV）** | 对外正式发布 | 否，必须向 CA 购买 | 全 Windows 默认信任 |
| **自签名证书** | 内部测试 / 内网分发 | 是 | 目标机器需手动安装信任 |

## 配套脚本用法（scripts/new-code-signing-cert.ps1）

脚本提供三种模式，详细参数可用 `Get-Help .\scripts\new-code-signing-cert.ps1` 查看：

| 模式 | 命令 | 产物 |
|---|---|---|
| 生成自签名证书 | `.\new-code-signing-cert.ps1 -CompanyName "公司全称" -Password "密码"` | `cert-out\codesign.pfx`（含私钥）+ `codesign.cer`（公钥） |
| 生成 CSR（申请商业证书） | `.\new-code-signing-cert.ps1 -MakeCsr -CompanyName "公司全称" -Password "密码"` | `cert-out\codesign.csr`（提交 CA）+ `codesign-request.pfx`（私钥备份，勿外传）+ `codesign-request.cer` |
| 生成证书并签名 exe | `.\new-code-signing-cert.ps1 -CompanyName "公司全称" -Password "密码" -SignFile ".\dist\DocTool.exe"` | 签名后的 exe + 证书 |

要点：

- **CSR 模式**：密钥与 CSR 全部在内存中生成（.NET `CertificateRequest`，RSA-2048 / SHA-256，
  PEM 格式 64 列换行），私钥备份为 PFX；CA 返回正式证书后用该 PFX 装配签名证书。
- `-Trust`：生成后导入本机「受信任的根证书颁发机构 / 受信任的发布者」（仅测试机）。
- 签名需要 Windows SDK 的 `signtool.exe`（未找到时脚本会提示安装）。
- 产物默认输出到 `scripts\cert-out\`（可用 `-OutputDir` 指定）；该目录已加入 `.gitignore`，
  证书与私钥严禁提交到代码仓库。

---

## 一、商业代码签名证书（正式发布）

这是让 Windows SmartScreen、浏览器等认可「受信任发布者」的唯一方式，**不能自己生成**，必须向 CA（证书颁发机构）购买。

### 1.1 选择 CA 与证书类型

- **常见 CA**：DigiCert、Sectigo、GlobalSign、Certum（国内可通过代理商购买，支持人民币付款、中文资料审核）。
- **OV 证书**（Organization Validation）：验证公司真实存在，价格较低，一般 1–3 个工作日签发。
- **EV 证书**（Extended Validation）：审核更严（需营业执照、对公电话、域名邮箱等），私钥必须存放在 **USB Key / HSM 硬件令牌**中且不可导出；能更快建立 SmartScreen 信誉，首次运行提示「未知发布者」的概率更低。

### 1.2 申请流程

```
1. 本机生成密钥对 + CSR（证书签名请求）   ← 见 1.3，私钥永远留在本地
2. 向 CA 提交 CSR 和公司资料（营业执照、对公电话、域名邮箱等）
3. CA 电话/邮件核实公司信息，审核通过后签发
4. 交付：OV 证书为 PFX 文件；EV 证书为硬件令牌（U 盾），私钥不可导出
5. 用 signtool 对软件签名（见第三章）
```

### 1.3 生成本地密钥与 CSR（提交给 CA 用）

推荐用 OpenSSL（方法 B，见 2.3）生成 CSR，然后把 `codesign.csr` 文件提交给 CA：

```bash
openssl req -new -newkey rsa:2048 -nodes \
  -keyout codesign.key -out codesign.csr \
  -subj "/C=CN/O=公司全称/CN=公司全称"
```

也可以使用配套脚本的 CSR 模式（见脚本说明），或在 Windows 上用 `certreq`：

```ini
; request.inf
[Version]
Signature="$Windows NT$"

[NewRequest]
Subject="CN=公司全称, O=公司全称, C=CN"
KeySpec=1
KeyUsage=0x80
MachineKeySet=true

[EnhancedKeyUsageExtension]
OID=1.3.6.1.5.5.7.3.3
```

```cmd
certreq -new -inf request.inf codesign.csr
```

> 注意：CSR 生成后**私钥不能交给任何人**（包括 CA）。CA 只会用你的 CSR 里的公钥签发证书。

---

## 二、自签名证书（内部测试 / 内网分发）

完全自己生成，免费、即时，适合测试签名流程、内部工具分发。缺点：目标机器需**手动安装信任**，否则仍提示「未知发布者」。

### 2.1 方法 A：PowerShell（Windows 最简单，推荐）

```powershell
# 生成代码签名证书（存入当前用户证书库）
$cert = New-SelfSignedCertificate `
  -Type CodeSigningCert `
  -Subject "CN=贵公司名称, O=贵公司英文名, C=CN" `
  -CertStoreLocation Cert:\CurrentUser\My `
  -NotAfter (Get-Date).AddYears(3)

# 导出为 PFX（带密码，供 signtool 签名用）
$pwd = ConvertTo-SecureString -String "你的密码" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath "codesign.pfx" -Password $pwd
```

### 2.2 让自签名证书被本机信任（可选）

```powershell
# 导入到「受信任的根证书颁发机构」（本机信任，仅测试机使用）
$pwd = ConvertTo-SecureString -String "你的密码" -Force -AsPlainText
Import-PfxCertificate -FilePath "codesign.pfx" `
  -CertStoreLocation Cert:\LocalMachine\Root -Password $pwd
# 同时导入到「受信任的发布者」，签名后不再弹「未知发布者」
Import-PfxCertificate -FilePath "codesign.pfx" `
  -CertStoreLocation Cert:\LocalMachine\TrustedPublisher -Password $pwd
```

> 注意：根证书是最高信任级别，只应在受控的测试机/内网导入，不要在企业域外随便分发。

### 2.3 方法 B：OpenSSL（跨平台，也可用于申请商业证书）

先创建扩展文件 `codesign_ext.cnf`：

```ini
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=codeSigning
```

```bash
# 1. 生成私钥
openssl genrsa -out codesign.key 2048

# 2. 生成 CSR —— 把 codesign.csr 交给 CA 即可申请商业证书
openssl req -new -key codesign.key -out codesign.csr \
  -subj "/C=CN/O=公司全称/CN=公司全称"

# 3. 自签名（跳过 CA，仅内部用）
openssl x509 -req -days 3650 -in codesign.csr -signkey codesign.key \
  -out codesign.crt -extfile codesign_ext.cnf

# 4. 打包成 PFX
openssl pkcs12 -export -out codesign.pfx -inkey codesign.key -in codesign.crt
```

### 2.4 方法 C：certreq（Windows 自带）

适合向企业内网 CA（Active Directory 证书服务）申请，或生成 CSR 提交公共 CA，见 1.3 的示例。

---

## 三、签名操作（signtool）

Windows SDK 自带 `signtool`，位于：

```
C:\Program Files (x86)\Windows Kits\10\bin\<版本>\x64\signtool.exe
```

### 3.1 用 PFX 签名（必须加时间戳）

```cmd
signtool sign /fd SHA256 /f codesign.pfx /p 你的密码 ^
  /tr http://timestamp.digicert.com /td SHA256 your-app.exe
```

### 3.2 用证书库中的证书签名（EV U 盾等）

```cmd
signtool sign /fd SHA256 /sha1 <证书指纹> /tr http://timestamp.digicert.com /td SHA256 your-app.exe
```

### 3.3 验证签名

```cmd
signtool verify /pa /v your-app.exe
```

### 3.4 常用时间戳服务器

| 服务商 | 地址 |
|---|---|
| DigiCert（RFC3161） | `http://timestamp.digicert.com` |
| Sectigo（Comodo） | `http://timestamp.sectigo.com` |
| GlobalSign（RFC3161） | `http://timestamp.globalsign.com/tsa/r6advanced1` |
| 微软（Authenticode） | `http://timestamp.digicert.com`（旧：`http://timestamp.verisign.com/scripts/timstamp.dll`） |

---

## 四、关键注意事项

1. **必须加时间戳**：签名时带上 `/tr`（RFC3161）参数。否则证书过期后，已签名的软件会被判定为签名失效，用户无法安装。
2. **签名算法统一 SHA256**：不要再用 SHA1（Windows 7 之后默认不信任 SHA1 签名）。
3. **商业证书有效期**：2023 年起 CA 签发的最长 3 年，需提前规划续期。
4. **EV 证书私钥锁在硬件里**：只能插 U 盾在签名服务器上签名，无法复制到别处，注意保管与备份策略（CA 一般支持补发）。
5. **SmartScreen 信誉**：新证书签名的软件首次运行仍可能提示「未知发布者」，靠下载量慢慢建立信誉，EV 证书可加速。
6. **私钥安全**：自签名私钥（`codesign.key` / PFX）等同公司公章，必须加密存储、专人保管、禁止提交进 Git 仓库。
7. **CSR 一次性使用**：CSR 提交后即失效，如需重新申请请重新生成。

---

## 五、常见问题

**Q：自己生成的证书能被所有用户信任吗？**
A：不能。自签名证书默认不被任何机器信任，需要每台目标机器手动导入「受信任的根证书颁发机构」。要全 Windows 默认信任只能购买商业证书。

**Q：OV 和 EV 选哪个？**
A：预算有限且发布频率低选 OV；对用户信任度要求高（如面向大众的安装包）、需要快速建立 SmartScreen 信誉选 EV。EV 必须配硬件令牌。

**Q：证书过期了，已发布的软件还能运行吗？**
A：只要签名时加了时间戳，且软件本身未过期，证书过期后签名依然有效。这也是「必须加时间戳」的原因。

**Q：购买商业证书必须用硬件令牌吗？**
A：EV 必须；OV 通常交付 PFX 文件（部分 CA 也强制用令牌）。PFX 需妥善保管密码。

---

## 六、团队协作与共享指引

### 6.1 产物清单与共享级别

| 文件 | 内容 | 能否共享 | 共享渠道 |
|---|---|---|---|
| `scripts/new-code-signing-cert.ps1` | 主流程脚本（生成/签名/验证） | ✅ 可共享 | Git 仓库 |
| `docs/code-signing-certificate.md` | 本文档 | ✅ 可共享 | Git 仓库 |
| `scripts/cert-out/codesign.cer` | 证书公钥（用于目标机器安装信任） | ✅ 可共享 | Git 仓库 / 内网盘 / 邮件 |
| `scripts/cert-out/codesign.pfx` | **证书私钥（含导出密码）** | ❌ **严禁共享** | 仅签名负责人保管 |
| 导出密码 | PFX 口令 | ❌ **严禁共享** | 密码管理器 / 加密传递 |

### 6.2 团队角色分工（建议）

- **签名负责人（1~2 人）**：持有 `codesign.pfx` + 密码，负责每次打包后执行签名。签名命令：
  ```powershell
  .\scripts\new-code-signing-cert.ps1 -PfxFile .\scripts\cert-out\codesign.pfx `
      -Password "<密码>" -SignFile "<要签名的exe>"
  ```
- **普通成员**：只需要安装 `codesign.cer` 到本机信任库即可正常使用已签名软件；需要自己生成测试证书时，运行脚本的默认模式（`-CompanyName` 填自己团队名即可，互不影响）。

### 6.3 Git 安全约定

- 仓库 `.gitignore` 已包含 `*.pfx`、`*.key`、`*.pem` 规则，**私钥文件不会被提交**，请勿改动或移除。
- 提交前可用以下命令自查：
  ```cmd
  git check-ignore scripts/cert-out/codesign.pfx   :: 输出路径=已忽略（安全）
  ```
- `codesign.cer`（公钥）可以正常提交，方便团队成员拉取后一键安装信任。
- **切勿**把密码写进脚本、批处理或任何会进仓库的文件（如 `.cmd`、`build_exe.ps1`）。

### 6.4 其他团队机器的信任安装

团队成员拿到 `codesign.cer` 后，两种安装方式任选：

```powershell
# 方式一：命令行（当前用户，无需管理员）
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(".\codesign.cer")
foreach ($store in @("Root", "TrustedPublisher")) {
    $s = New-Object System.Security.Cryptography.X509Certificates.X509Store($store, "CurrentUser")
    $s.Open("ReadWrite"); $s.Add($cert); $s.Close()
}
```

```cmd
:: 方式二：双击 codesign.cer → 安装证书 → 本地计算机 → 受信任的根证书颁发机构
```

> 自签名证书仅限公司内部测试/内网分发。对外发布软件必须购买商业证书，届时仅替换 PFX 与证书，签名流程不变。
