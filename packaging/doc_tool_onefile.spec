# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：将康尚文档工具打包为 Windows onefile 应用（PySide6）。

任务 7.1（PySide6 迁移）：仅引入 QtCore/QtGui/QtWidgets，排除未用的
QtWebEngine/QtNetwork/QtQml/QtMultimedia 等大件，控制体积。

构建命令：
    pyinstaller packaging/doc_tool.spec --noconfirm --clean

产出：
    dist/KonsungDocTool/KonsungDocTool.exe        (GUI 入口)
    dist/KonsungDocTool/doc_tool-cli.exe           (CLI 入口，可选)
    dist/KonsungDocTool/scripts/                   (内核脚本)
    dist/KonsungDocTool/templates/                 (公司 Word 模板)
    dist/KonsungDocTool/config/                    (文档配置)
    dist/KonsungDocTool/doc_tool/resources/        (默认配置、许可、图标)
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

APP_VERSION = "1.0.0"

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

# PySide6（Qt Widgets）：不在此手动 collect_dynamic_libs——那会把整个
# PySide6_Addons wheel（Qt3D/Qml/Multimedia/Sql 等）全部打进去。改用
# PyInstaller 内置 PySide6 hook：它按应用实际 import 的 QtCore/QtGui/
# QtWidgets 收集所需 DLL 与 plugins（platforms/styles/imageformats），
# 未使用的 Addons 模块自然不打包。下方 excludes 再显式排除以双保险。

# yaml（PyYAML）：纯 Python，自动收集

# --- 收集本应用资源 ---
# scripts/ 目录：内核脚本（build_docx, validate_docx, refresh_fields, docx_common 等）
# 打包后位于 _MEIPASS/scripts/，kernel.py 的 ensure_kernel_importable() 会定位它
scripts_dir = str(REPO_ROOT / "scripts")
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

# 应用图标：EXE 图标 + 运行时窗口图标（QIcon）
icon_file = str(SPEC_DIR / "app.ico")
icon_datas = [(icon_file, "doc_tool/resources")] if os.path.isfile(icon_file) else []

# 合并所有数据和隐藏导入
all_datas = (
    lxml_datas
    + pywin32_datas
    + script_datas
    + template_datas
    + config_datas
    + license_datas
    + icon_datas
    + [
        # doc_tool/resources/ 下的默认配置与图标
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
        # 排除未使用的 PySide6 Addons 大件（仅保留 QtCore/QtGui/QtWidgets）
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel",
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtBluetooth",
        "PySide6.QtPositioning",
        "PySide6.QtWebSockets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtSvgWidgets",
        "shiboken6_tool",
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
    a.binaries,
    exclude_binaries=False,
    name="KonsungDocTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI 应用，不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file if os.path.isfile(icon_file) else None,
)

# onefile：无 COLLECT，全部打包进单个 exe

