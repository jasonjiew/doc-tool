# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：将 Doc Tool 打包为 Windows onedir 应用（PySide6）。

任务 7.1（PySide6 迁移）：仅引入 QtCore/QtGui/QtWidgets/QtPdf，排除未用的
QtWebEngine/QtNetwork/QtQml/QtMultimedia 等大件，控制体积。

构建命令：
    pyinstaller packaging/doc_tool.spec --noconfirm --clean

产出：
    dist/DocTool/DocTool.exe                   (GUI 入口)
    dist/DocTool/doc-tool-cli.exe              (CLI 入口，可选)
    dist/DocTool/scripts/                      (内核脚本)
    dist/DocTool/THIRD_PARTY_LICENSES.txt      (第三方许可)
    dist/DocTool/doc_tool/resources/           (默认配置、许可、图标)
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

# openpyxl / python-docx：均为函数内部延迟导入（table_convert / text_convert），
# PyInstaller 静态分析看不到，必须显式收集，否则漏打包导致
# XLSX 互转与 DOCX 转纯文本在净机器上 ImportError。
openpyxl_hiddenimports = collect_submodules("openpyxl")
openpyxl_datas = collect_data_files("openpyxl")
docx_hiddenimports = collect_submodules("docx")
docx_datas = collect_data_files("docx")

# yaml（PyYAML）：纯 Python，自动收集

# --- 收集本应用资源 ---
# scripts/ 目录：内核脚本（build_docx, validate_docx, refresh_fields, docx_common 等）
# 打包后位于 _MEIPASS/scripts/，kernel.py 的 ensure_kernel_importable() 会定位它
# 注意：不再收集 scripts/migration/（内部一次性迁移脚本，含公司文件名，不入公共产物）。
scripts_dir = str(REPO_ROOT / "scripts")
script_datas = []
for name in os.listdir(scripts_dir):
    full = os.path.join(scripts_dir, name)
    if name.endswith(".py") and os.path.isfile(full):
        script_datas.append((full, "scripts"))

# 运行必需资源只来自 doc_tool/resources/（默认配置、图标、许可）；仓库根
# templates/、config/、content/、assets/ 等公司材料绝不隐式打包（任务 8.2）。

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
    + openpyxl_datas
    + docx_datas
    + script_datas
    + license_datas
    + icon_datas
    + [
        # doc_tool/resources/ 下的默认配置与图标
        (str(REPO_ROOT / "doc_tool" / "resources" / "default_project.yml"),
         "doc_tool/resources"),
        (str(REPO_ROOT / "doc_tool" / "resources" / "web_preview"),
         "doc_tool/resources/web_preview"),
    ]
)

all_binaries = lxml_binaries + pywin32_binaries

all_hiddenimports = (
    lxml_hiddenimports
    + pillow_hiddenimports
    + pywin32_hiddenimports
    + openpyxl_hiddenimports
    + docx_hiddenimports
    + [
        "yaml",
        "docx_common",
        "build_docx",
        "validate_docx",
        "refresh_fields",
    ]
)

a = Analysis(
    [str(REPO_ROOT / "doc_tool" / "app.py")],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "scripts")],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(REPO_ROOT / "packaging" / "rthook_hardened_runtime.py")],
    excludes=[
        # 排除开发/测试专用模块，减小体积
        "pytest",
        "mypy",
        "unittest.test",
        "test",  # Python 标准库 test 套件
        "tests",
        # 排除未使用的 PySide6 Addons 大件（仅保留 QtCore/QtGui/QtWidgets/QtPdf）
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
        "PySide6.QtPdfWidgets",
        "PySide6.QtSvgWidgets",
        "shiboken6_tool",
        # multiprocessing 在公司受限环境下会经 socket/_socket 触发安全软件
        # 拦截冻结 exe 加载扩展模块。常规 GUI 与文档构建不依赖多进程 spawn；
        # Word 可用性预检在缺 multiprocessing 时降级为静态判定，不阻断流程。
        "multiprocessing",
        # 排除 openpyxl 可选依赖 numpy，保持分发包轻量且与 CI 依赖严格一致
        "numpy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

cli_analysis = Analysis(
    [str(REPO_ROOT / "doc_tool_cli.py")],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "scripts")],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(REPO_ROOT / "packaging" / "rthook_hardened_runtime.py")],
    excludes=a.excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
cli_pyz = PYZ(cli_analysis.pure, cli_analysis.zipped_data, cipher=block_cipher)

gui_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DocTool",
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

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="doc-tool-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file if os.path.isfile(icon_file) else None,
)

coll = COLLECT(
    gui_exe,
    cli_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DocTool",
)
