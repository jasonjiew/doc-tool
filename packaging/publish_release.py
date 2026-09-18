# -*- coding: utf-8 -*-
"""GitLab Release 发布脚本：上传打包产物并创建/更新 Release。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request


<<<<<<< HEAD
# 内网 GitLab 地址与项目信息一律由环境变量注入，避免把内部主机名/项目 id 固化进源码。
GITLAB_BASE = os.getenv("GITLAB_BASE", "").rstrip("/")
PROJECT_PATH = os.getenv("GITLAB_PROJECT_PATH", "")
PROJECT_ID_RAW = os.getenv("GITLAB_PROJECT_ID", "")
=======
GITLAB_BASE = os.getenv("GITLAB_BASE", "http://192.168.0.242:8899")
PROJECT_ID = int(os.getenv("GITLAB_PROJECT_ID", "119"))
>>>>>>> fa51c9618cd827236a03a6afb362a6e2053e954e
VERSION = "2.5.0"
TAG_NAME = "v2.5.0"
PACKAGE_NAME = "DocTool"


<<<<<<< HEAD
def get_project_id() -> int:
    """返回 GitLab 项目 id；未配置时给出明确报错。"""
    if not PROJECT_ID_RAW:
        raise RuntimeError("请设置 GITLAB_PROJECT_ID 环境变量（GitLab 项目 id）")
    return int(PROJECT_ID_RAW)


PROJECT_ID = get_project_id() if PROJECT_ID_RAW else 0


=======
>>>>>>> fa51c9618cd827236a03a6afb362a6e2053e954e
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
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from doc_tool.domain.version import get_commit_id
    commit_sha = get_commit_id()[:7]
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
<<<<<<< HEAD
            url = f"{GITLAB_BASE}/{PROJECT_PATH}/-/package_files/{item['id']}/download"
=======
            url = f"{GITLAB_BASE}/application/ai/doc-tool/-/package_files/{item['id']}/download"
>>>>>>> fa51c9618cd827236a03a6afb362a6e2053e954e
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

## 本版变更（2.5.0）

- **Word 导入向导大纲树实时预览与格式安全拦截**：
  - 样式映射步骤引入实时大纲树预览（`generate_preview_heading_tree` / `HeadingPreviewWidget`），支持各级标题层级即时诊断、空标题与跳级拦截；
  - 样式普查展示正文样例文本（`sample_text`），直观区分标题与正文样式；
  - 严密拦截伪装成 `.docx` 的旧版 Word 97-2003 二进制 `.doc` 文件（前8字节魔数精准识别），提供友好修复引导；
  - 首次导入支持阶段事件（`ImportStageEvent`）回调，向导平滑呈现解包、解析、清洗、骨架生成实时进度。
- **离线 PDF 工具箱新增页面重排与高级参数配置**：
  - 扩展至 15 项常用离线 PDF 工具，新增「页面重排（reorder）」工具：支持倒序反转（`reverse`）、奇偶分组（`odd-even` / `even-odd`）、自定义序列与连续范围；
  - 深度补齐高级配置：图片转 PDF 页面尺寸/边距/方向、压缩级别与图像重采样质量、水印旋转/透明度/精确坐标定位等；
  - CLI 命令行同步支持页面重排与高级参数。
- **文档互转界面交互升级与文件签名安全防呆**：
  - 互转对话框重构为交互式表格清单，支持多文件拖放与列表管理、每项独立选择目标格式与全局批量覆盖；
  - 文件签名防呆拦截：基于文件头特征严格拦截伪装成文档的 Windows PE 可执行文件（MZ 特征）、假扩展名及 0 字节空文件；
  - 转换完成后支持一键定位并打开产物目录。
- **首页任务页体验升级与 Docs-as-Code 流水线引导**：
  - 新增 Docs-as-Code 3 步流水线引导条（导入拆解 → 协同撰写 → 规范出稿）与全局命令面板（Ctrl+K）快捷入口；
  - 最近项目列表支持实时关键字过滤、在文件资源管理器中定位、复制绝对路径、快速移除与失效项目标记；
  - 文档互转与 PDF 工具箱卡片增加功能直达胶囊（Pill），项目条增加保存并关闭项目（Ctrl+Shift+W）安全返回主页；
  - 页面支持响应式滚动排版，完美适配小屏幕与副屏显示。
- **命令面板条目委托修复**：
  - 修复 `PaletteItemDelegate` 状态标志属性访问偶发异常，保障多分辨率与高 DPI 下平滑渲染。

## 历史更新（2.4.0）

- **Mermaid 极速矢量预览与沉浸式大图查看器（Lightbox）**：
  - 引入 `want_png=False` 纯矢量 SVG 极速预览模式，跳过 CPU/Chromium 3x PNG 光栅化，实现毫秒级预览响应；
  - 增强图表语法兼容：支持 sequenceDiagram 小写 `note over`、虚线文字连线（`-. text .->`）与链式标签连线；
  - 新增 `DiagramViewer` 架构图/大图沉浸式交互查看器（Lightbox），支持平移抓手、滚轮缩放、双击还原及跳转至 Markdown 源码行；
  - Mermaid 编辑器对话框增加画布缩放、窗口自适应与 1:1 显示控制。
- **现代 Web 预览与编辑器双向联动**：
  - 新增基于 QWebEngineView + marked.js + mermaid.min.js 的现代前端预览引擎，原生支持全量官方 Mermaid 语法与主线程零卡顿；
  - 编辑器支持延迟预览（`lazy_preview`）与按需渲染（`ensure_preview_rendered`），大幅优化多文件同时打开速度；
  - 实现精准双向定位：预览标题反向定位编辑器源码行并高亮闪烁（`jump_to_heading`），Mermaid 图表反向定位源码。
- **异步操作加载遮罩（OperationLoadingOverlay & AsyncOperationWorker）**：
  - 为版本控制（Git/SVN）等耗时操作提供 60 FPS 渐变加载旋转指示器与模态防连击，杜绝主线程冻结；
  - 重构 `ProjectLoadingOverlay` 项目加载遮罩：增加步进药丸胶囊指示、进度条、平滑淡出动画及 Esc/跳过等待支持。
- **版本控制与改动比对体验**：
  - 改动面板支持统一差异（Unified diff）与分栏比对（Side-by-side diff）双视图切换；
  - 支持行内词级/字符级差异高亮；
  - 新建分支对话框支持选择基准分支与常用前缀胶囊（feature/, fix/, docs/ 等）。
- **文档质检与一键自动修复**：
  - 引入 `path_natural_sort_key` 自然排序键（1.2 排在 1.10 前，第2章在第10章前）；
  - 新增 `heading_format` 规则并支持标题空格、空标题、未闭合代码块一键自动修复。
- **Word 内核排版优化**：
  - 修订记录行支持超长摘要自然跨页拆分与自动重复表头，章节名自动映射内部超链接；
  - 评审导出 DOCX 补齐中文字体（微软雅黑、Consolas、Times New Roman）与标准边距。

## 历史更新（2.3.2）

- **修复独立校验模式错配（操作 → 校验项目 / F5）**：
  - **产物刷新状态自适应**：自动探测当前 Word 产物状态（优先读取 `.state.json`，缺失时自动探测 `word/settings.xml` 内 `updateFields` 消费状态）；
  - **精准匹配对应门禁**：对正式合并生成（已由 Word 刷新）的产物自动采用刷新后语义门禁，消除 33+ 处复杂表格 OOXML 重排格式假阳性与模板样式误报；对草稿产物保持严格逐字节门禁；
  - **增强时效与产物防呆提醒**：源 Markdown 修改时间晚于产物时在日志中清晰友好提示；未生成产物时提供弹窗指引先执行构建或合并。

## 历史更新（2.3.1）

- **Mermaid 原生支持与裸流程图自愈**：
  - 原生支持 `graph TD` 语法与 Word 遗留段落注释裸流程图自愈提取。

## 历史更新（2.3.0）

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

- **安装版**：下载 `DocTool-Setup-{VERSION}.exe`，双击运行，按提示安装（默认安装到 `%LOCALAPPDATA%\\DocTool`，无需管理员权限）；
- **免安装便携版**：下载 `DocTool-{VERSION}-portable.zip`，解压到任意目录，首次先双击「安装证书.cmd」导入公司证书，之后双击「启动DocTool.cmd」启动。

> 遇到启动问题，双击安装目录/便携包根部的 `diagnose.cmd`，把生成的 `DocTool-diagnose.txt` 发给维护人员。

## 校验

- 安装版 SHA-256：`{setup_sha}`
- 便携版 SHA-256：`{portable_sha}`

## 构建来源

- 标签：{TAG_NAME}
- 提交：{commit_sha}（main）
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
<<<<<<< HEAD
    print(f"Release URL: {GITLAB_BASE}/{PROJECT_PATH}/-/releases/{TAG_NAME}")
=======
    print(f"Release URL: {GITLAB_BASE}/application/ai/doc-tool/-/releases/{TAG_NAME}")
>>>>>>> fa51c9618cd827236a03a6afb362a6e2053e954e


if __name__ == "__main__":
    main()
