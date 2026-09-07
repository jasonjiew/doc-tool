# -*- coding: utf-8 -*-
"""GitLab Release 发布脚本：上传打包产物并创建/更新 Release。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request


GITLAB_BASE = os.getenv("GITLAB_BASE", "http://127.0.0.1:8899")
PROJECT_ID = int(os.getenv("GITLAB_PROJECT_ID", "119"))
VERSION = "2.3.1"
TAG_NAME = "v2.3.1"
PACKAGE_NAME = "DocTool"


def get_token() -> str:
    token = os.getenv("GITLAB_TOKEN")
    if not token and len(sys.argv) > 1:
        token = sys.argv[1]
    if not token:
        raise RuntimeError("请设置 GITLAB_TOKEN 环境变量或通过命令行参数传入 Token: python packaging/publish_release.py <TOKEN>")
    return token


def calc_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().upper()


def upload_file(token: str, filename: str, filepath: str) -> None:
    url = f"{GITLAB_BASE}/api/v4/projects/{PROJECT_ID}/packages/generic/{PACKAGE_NAME}/{VERSION}/{filename}"
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"正在上传 {filename} ({size_mb:.1f} MB)...", flush=True)

    with open(filepath, "rb") as f:
        data = f.read()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"PRIVATE-TOKEN": token},
        method="PUT",
    )
    with urllib.request.urlopen(req) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"上传失败: {resp.status} {resp.read()}")
    print(f"  上传完成: {filename}")


def get_package_files(token: str) -> list[dict]:
    # 1. 获取 package_id
    url = f"{GITLAB_BASE}/api/v4/projects/{PROJECT_ID}/packages?package_name={PACKAGE_NAME}"
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
    with urllib.request.urlopen(req) as resp:
        pkgs = json.loads(resp.read())

    pkg_id = None
    for p in pkgs:
        if p.get("name") == PACKAGE_NAME and p.get("version") == VERSION:
            pkg_id = p["id"]
            break

    if pkg_id is None:
        raise RuntimeError(f"未找到 Package {PACKAGE_NAME} {VERSION}")

    # 2. 获取 package_files
    url = f"{GITLAB_BASE}/api/v4/projects/{PROJECT_ID}/packages/{pkg_id}/package_files"
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def create_or_update_release(token: str, description: str, links: list[dict]) -> dict:
    url = f"{GITLAB_BASE}/api/v4/projects/{PROJECT_ID}/releases"
    payload = {
        "name": TAG_NAME,
        "tag_name": TAG_NAME,
        "description": description,
        "assets": {"links": links},
    }
    data = json.dumps(payload).encode("utf-8")

    # 检查是否已存在
    check_url = f"{GITLAB_BASE}/api/v4/projects/{PROJECT_ID}/releases/{TAG_NAME}"
    try:
        req = urllib.request.Request(check_url, headers={"PRIVATE-TOKEN": token})
        with urllib.request.urlopen(req) as resp:
            exists = resp.status == 200
    except urllib.error.HTTPError as e:
        exists = e.code != 404

    if exists:
        print(f"Release {TAG_NAME} 已存在，正在更新...", flush=True)
        # 更新 release
        put_payload = {"name": TAG_NAME, "description": description}
        req = urllib.request.Request(
            check_url,
            data=json.dumps(put_payload).encode("utf-8"),
            headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    else:
        print(f"正在创建 Release {TAG_NAME}...", flush=True)
        req = urllib.request.Request(
            url,
            data=data,
            headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())


def main():
    token = get_token()
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir = os.path.join(repo_root, "packaging", "Output")

    files_to_upload = [
        (f"DocTool-Setup-{VERSION}.exe", os.path.join(out_dir, f"DocTool-Setup-{VERSION}.exe")),
        (f"DocTool-Setup-{VERSION}.exe.sha256", os.path.join(out_dir, f"DocTool-Setup-{VERSION}.exe.sha256")),
        (f"DocTool-{VERSION}-portable.zip", os.path.join(out_dir, f"DocTool-{VERSION}-portable.zip")),
        (f"DocTool-{VERSION}-portable.zip.sha256", os.path.join(out_dir, f"DocTool-{VERSION}-portable.zip.sha256")),
        (f"DocTool-{VERSION}-sbom.txt", os.path.join(out_dir, f"DocTool-{VERSION}-sbom.txt")),
        (f"DocTool-{VERSION}.cdx.json", os.path.join(out_dir, f"DocTool-{VERSION}.cdx.json")),
        (f"DocTool-{VERSION}.spdx.json", os.path.join(out_dir, f"DocTool-{VERSION}.spdx.json")),
    ]

    cer_path = os.path.join(repo_root, "scripts", "cert-out", "codesign.cer")
    if os.path.exists(cer_path):
        files_to_upload.append(("codesign.cer", cer_path))

    for name, path in files_to_upload:
        if not os.path.exists(path):
            raise FileNotFoundError(f"文件不存在: {path}")
        upload_file(token, name, path)

    # 获取 package_files 信息并生成 links
    package_files = get_package_files(token)
    name_to_file = {f["file_name"]: f for f in package_files}

    exe_file = name_to_file.get(f"DocTool-Setup-{VERSION}.exe")
    zip_file = name_to_file.get(f"DocTool-{VERSION}-portable.zip")

    exe_mb = f"{exe_file['size'] / (1024 * 1024):.1f}" if exe_file else "45.7"
    zip_mb = f"{zip_file['size'] / (1024 * 1024):.1f}" if zip_file else "73.0"

    links = []
    link_specs = [
        (f"DocTool-Setup-{VERSION}.exe", f"DocTool-Setup-{VERSION}.exe（安装版，{exe_mb} MB）"),
        (f"DocTool-Setup-{VERSION}.exe.sha256", "安装版 SHA-256"),
        (f"DocTool-{VERSION}-portable.zip", f"DocTool-{VERSION}-portable.zip（免安装便携版，{zip_mb} MB）"),
        (f"DocTool-{VERSION}-portable.zip.sha256", "便携版 SHA-256"),
        (f"DocTool-{VERSION}-sbom.txt", "依赖清单 SBOM"),
        (f"DocTool-{VERSION}.cdx.json", "CycloneDX SBOM"),
        (f"DocTool-{VERSION}.spdx.json", "SPDX SBOM"),
        ("codesign.cer", "codesign.cer（公司证书公钥）"),
    ]

    for filename, display_name in link_specs:
        if item := name_to_file.get(filename):
            url = f"{GITLAB_BASE}/application/ai/doc-tool/-/package_files/{item['id']}/download"
            links.append({
                "name": display_name,
                "url": url,
                "direct_asset_url": url,
                "link_type": "other"
            })

    setup_sha = calc_sha256(os.path.join(out_dir, f"DocTool-Setup-{VERSION}.exe"))
    portable_sha = calc_sha256(os.path.join(out_dir, f"DocTool-{VERSION}-portable.zip"))

    description = f"""# Doc Tool v{VERSION}

公司内部文档维护工具：把大型 Word 文档转成可维护、可审查、可可靠重建的 Markdown 项目，编辑完成后一键重建正式 DOCX 交付物。

## 本版变更（2.3.0）

- **全局命令面板与快速章节秒开（Ctrl+K / Ctrl+P）**：
  - **命令面板（Ctrl+K / Ctrl+Shift+P）**：现代化无边框居中浮层，一处聚合新建/打开项目、全部保存、正式出稿、文档全库校验、Word 逆向重新导入与环境诊断等全部核心动作，支持中英文模糊过滤与纯键盘无鼠标操控；
  - **章节秒开（Ctrl+P）**：快速遍历与智能索引项目中所有 Markdown 章节文档，提取一级标题与相对路径，支持拼音与文本关键字模糊即时过滤，回车毫秒级切页打开；
  - 针对多显示器环境副屏坐标、长路径左截断省略以及外部失焦自动关闭进行了专项排版与交互优化。
- **Markdown 表格智能编辑与管道对齐美化**：
  - **等宽管道符智能对齐**：基于 Unicode East Asian Width 自适应中英文字宽计算（汉字/全角标点计为 2 宽，ASCII 计为 1 宽），完整保留左/中/右对齐指示符（`:---:`, `---:`, `:---`）；
  - **单元格 Tab 智能导航**：光标处于表格时按 `Tab` / `Shift+Tab` 自动在单元格间跳转并高亮选中；表格末行末列按 `Tab` 自动插入新行骨架并进入首列编辑；
  - **表格一键美化（Ctrl+Alt+T / 右键菜单 / 工具栏按钮）**：连续表格智能嗅探，格式化后自动同步视口光标并完整接入撤销/重做（Undo/Redo）编辑栈。
- **实时预览区轻量代码块语法高亮**：
  - 内置零外部依赖词法高亮引擎，覆盖 Python、SQL、C/C++、Bash、JSON、YAML、HTML/XML 等常用代码语言；
  - 关键字、字符串、跨行块注释（`\"\"\"...\"\"\"`, `/*...*/`）、数值字面量（支持十六进制与二进制）精准着色，原生自适应深浅色主题；
  - 每个代码块注入行号定位锚点，支持大纲双向跳转与滚动行级同步。
- **改动评审稿导出与闭环**：
  - 支持将改动章节以修改前/修改后上下对照格式导出为会议级离线 Word 评审稿；
  - 评审包附带评审条目快照 `review_items.json`，支持公司评审单格式意见离线解析、幂等回流与章节绑定。

## 安装

- **安装版**：下载 `DocTool-Setup-2.3.0.exe`，双击运行，按提示安装（默认安装到 `%LOCALAPPDATA%\\DocTool`，无需管理员权限）；
- **免安装便携版**：下载 `DocTool-2.3.0-portable.zip`，解压到任意目录，首次先双击「安装证书.cmd」导入公司证书，之后双击「启动DocTool.cmd」启动。

> 遇到启动问题，双击安装目录/便携包根部的 `diagnose.cmd`，把生成的 `DocTool-diagnose.txt` 发给维护人员。

## 校验

- 安装版 SHA-256：`{setup_sha}`
- 便携版 SHA-256：`{portable_sha}`

## 构建来源

- 标签：v2.3.0
- 提交：3ed8394（main）
- 构建环境：Windows 11 / Python 3.13 / PyInstaller 6.22.1 / Inno Setup 6

## 已知限制

- 正式合并需要交互式 Windows 会话和 Microsoft Word；
- PDF 工具箱与 Markdown 解析各项功能为纯离线本地运算，无需连网，不上传任何隐私或敏感数据；
- 未配置公司代码签名证书时产物仅限受控试点。

## 升级与回滚

- 升级使用相同 AppId 与安装目录，自动关闭旧进程后覆盖；
- 旧设置（窗口几何、最近项目）首次启动时只读迁移，旧值保留便于回滚。
"""

    rel = create_or_update_release(token, description, links)
    print("\nRelease 发布成功！")
    print(f"Release URL: {GITLAB_BASE}/application/ai/doc-tool/-/releases/{TAG_NAME}")


if __name__ == "__main__":
    main()
