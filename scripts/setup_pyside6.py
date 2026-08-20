# -*- coding: utf-8 -*-
"""开发环境 PySide6 离线安置脚本（DLP 环境下 pip 无法原子重命名的替代方案）。

背景：部分公司电脑安装了 DLP/安全软件，会拦截 ``pip install`` 在写入
site-packages 时的原子重命名（报 ``WinError 17``）。此时把 PySide6 wheel
下载并解压到仓库 ``.vendor/site-packages``，通过 ``PYTHONPATH`` 使用即可。

用法：
    python scripts/setup_pyside6.py            # 下载并解压 PySide6 到 .vendor
    PYTHONPATH=.vendor/site-packages python -m doc_tool.app
    PYTHONPATH=.vendor/site-packages python -m unittest discover -s scripts/tests

离线（已有 wheel）：把 shiboken6 / PySide6 / PySide6_Essentials /
PySide6_Addons 的 .whl 放到 .vendor/wheels 后运行本脚本（--offline）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR = REPO_ROOT / ".vendor"
WHEELS = VENDOR / "wheels"
SITE = VENDOR / "site-packages"

PIN = "6.8.3"
PACKAGES = [
    "shiboken6=={0}".format(PIN),
    "PySide6=={0}".format(PIN),
    "PySide6_Essentials=={0}".format(PIN),
    "PySide6_Addons=={0}".format(PIN),
]


def download() -> None:
    """用 pip download 下载（不安装），避免 DLP 拦截原子重命名。"""
    WHEELS.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "pip", "download",
        *PACKAGES,
        "--no-deps", "--no-cache-dir", "-d", str(WHEELS),
    ]
    print("下载 PySide6 wheel 到：", WHEELS)
    subprocess.check_call(cmd)


def extract() -> None:
    """把已下载的 wheel 解压到 site-packages（zipfile，无原子重命名）。

    只解压与 ``PIN`` 版本匹配的 wheel，并先清掉 site-packages 中旧的
    PySide6/shiboken6 目录：旧版本 wheel 残留 + 新版本混装会让
    shiboken6 与 PySide6 版本不一致，import 直接失败。
    """
    SITE.mkdir(parents=True, exist_ok=True)
    wheels = sorted(
        whl
        for whl in WHEELS.glob("*.whl")
        if "-{0}-".format(PIN) in whl.name
    )
    if not wheels:
        raise SystemExit(
            "未找到 {0} 版本的 wheel，请先运行：python scripts/setup_pyside6.py".format(PIN)
        )
    # 清掉旧版残留目录（zipfile 无法删除旧版本独有的文件）。
    for stale in SITE.glob("PySide6*"):
        if stale.is_dir():
            import shutil

            shutil.rmtree(str(stale), ignore_errors=True)
    for stale in SITE.glob("shiboken6*"):
        if stale.is_dir():
            import shutil

            shutil.rmtree(str(stale), ignore_errors=True)
    for whl in wheels:
        print("解压：", whl.name)
        with zipfile.ZipFile(whl) as z:
            z.extractall(SITE)
    print("完成。使用：PYTHONPATH={0} python -m doc_tool.app".format(SITE))


def verify() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SITE)
    subprocess.check_call(
        [sys.executable, "-c", "import PySide6; print('PySide6', PySide6.__version__)"],
        env=env,
    )


def main() -> int:
    offline = "--offline" in sys.argv
    if not offline:
        download()
    extract()
    verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
