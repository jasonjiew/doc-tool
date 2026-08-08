# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：将康尚文档工具打包为 Windows onedir 应用。

任务 8.3：显式收集 lxml、Pillow、pywin32、模板、默认配置和许可文件。

构建命令：
    pyinstaller packaging/doc_tool.spec --noconfirm --clean

产出：
    dist/KonsungDocTool/KonsungDocTool.exe        (GUI 入口)
    dist/KonsungDocTool/doc_tool-cli.exe           (CLI 入口，可选)
    dist/KonsungDocTool/scripts/                   (内核脚本)
    dist/KonsungDocTool/templates/                 (公司 Word 模板)
    dist/KonsungDocTool/config/                    (文档配置)
    dist/KonsungDocTool/doc_tool/resources/        (默认配置、许可)
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# spec 文件位于 packaging/，仓库根是其父目录
SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

APP_VERSION = "0.1.0"

block_cipher = None

# --- 收集第三方库的隐式依赖 ---
# lxml：libxml2/libxslt 动态库和 Python 子模块
lxml_datas = collect_data_files("lxml")
lxml_binaries = collect_dynamic_libs("lxml")
lxml_hiddenimports = collect_submodules("lxml")

# Pillow：插件子模块（PIL.*）
pillow_hiddenimports = collect_submodules("PIL")

# pywin32：COM DLL 和 PythonCOM 类型库
pywin32_datas = collect_data_files("pywin32")
pywin32_binaries = collect_dynamic_libs("pywin32")
pywin32_hiddenimports = collect_submodules("win32com") + collect_submodules("pythoncom")

# tkinter：随 Python 分发，PyInstaller 自动收集
# yaml（PyYAML）：纯 Python，自动收集

# --- 收集本应用资源 ---
# scripts/ 目录：内核脚本（build_docx, validate_docx, refresh_fields, docx_common 等）
# 打包后位于 _MEIPASS/scripts/，kernel.py 的 ensure_kernel_importable() 会定位它
scripts_dir = str(REPO_ROOT / "scripts")
# 手动收集 scripts/ 下的 .py 文件（不含 tests/diagnostics）
script_datas = []
for name in os.listdir(scripts_dir):
    full = os.path.join(scripts_dir, name)
    if name.endswith(".py") and os.path.isfile(full):
        script_datas.append((full, "scripts"))
# migration/ 也需要打包（首次导入功能）
migration_dir = os.path.join(scripts_dir, "migration")
if os.path.isdir(migration_dir):
    script_datas.append((migration_dir, "scripts/migration"))

# templates/ 目录：公司 Word 模板
templates_dir = str(REPO_ROOT / "templates")
template_datas = []
if os.path.isdir(templates_dir):
    for name in os.listdir(templates_dir):
        full = os.path.join(templates_dir, name)
        if os.path.isfile(full):
            template_datas.append((full, "templates"))

# config/ 目录：文档配置
config_dir = str(REPO_ROOT / "config")
config_datas = []
if os.path.isdir(config_dir):
    for name in os.listdir(config_dir):
        full = os.path.join(config_dir, name)
        if os.path.isfile(full):
            config_datas.append((full, "config"))

# 第三方许可文件
license_file = str(REPO_ROOT / "THIRD_PARTY_LICENSES.txt")
license_datas = []
if os.path.isfile(license_file):
    license_datas.append((license_file, "."))

# 合并所有数据和隐藏导入
all_datas = (
    lxml_datas
    + pywin32_datas
    + script_datas
    + template_datas
    + config_datas
    + license_datas
    + [
        # doc_tool/resources/ 下的默认配置
        (str(REPO_ROOT / "doc_tool" / "resources" / "default_project.yml"),
         "doc_tool/resources"),
    ]
)

all_binaries = lxml_binaries + pywin32_binaries

all_hiddenimports = (
    lxml_hiddenimports
    + pillow_hiddenimports
    + pywin32_hiddenimports
    + [
        # scripts/ 下的内核模块作为数据文件打包，运行时由
        # kernel.ensure_kernel_importable() 动态加入 sys.path，不作为 hidden import
        "yaml",
    ]
)

a = Analysis(
    [str(REPO_ROOT / "doc_tool" / "app.py")],
    pathex=[str(REPO_ROOT)],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除开发/测试专用模块，减小体积
        "pytest",
        "mypy",
        "unittest.test",
        "test",  # Python 标准库 test 套件
        "tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KonsungDocTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 应用，不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="packaging/app.ico",  # 后续添加图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="KonsungDocTool",
)
