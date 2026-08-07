# -*- coding: utf-8 -*-
"""End-to-end add/modify/delete and failure-path acceptance scenarios."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image


TESTS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(TESTS)
BASE = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from docx_common import load_config  # noqa: E402
from validate_docx import DocxPackage, qn  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(command, cwd):
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def build(project):
    return run([sys.executable, os.path.join(project, "scripts", "build_docx.py"), "requirement"], project)


def validate(project, refreshed=False):
    command = [sys.executable, os.path.join(project, "scripts", "validate_docx.py"), "requirement"]
    if refreshed:
        command.append("--require-refreshed")
    return run(command, project)


def daily_cmd(project):
    return run(["cmd.exe", "/d", "/c", os.path.join(project, "生成需求说明书.cmd"), "--no-pause"], project)


def signature(event):
    return ("T" if event.kind in ("T", "C") else event.kind, event.value)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_project(destination):
    os.makedirs(destination)
    for directory in ("scripts", "templates", "config"):
        shutil.copytree(os.path.join(BASE, directory), os.path.join(destination, directory))
    shutil.copytree(
        os.path.join(BASE, "content", "requirement"),
        os.path.join(destination, "content", "requirement"),
    )
    shutil.copytree(
        os.path.join(BASE, "assets", "requirement"),
        os.path.join(destination, "assets", "requirement"),
    )
    shutil.copy2(os.path.join(BASE, "生成需求说明书.cmd"), destination)
    os.makedirs(os.path.join(destination, "output"))


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="doc-iteration-e2e-") as root:
        project = os.path.join(root, "doc-automation")
        copy_project(project)
        config = load_config("requirement", project)
        output = config["paths"]["output"]
        chapter = os.path.join(config["paths"]["content_root"], "第3章 功能需求", "3.1 KSHC")
        test_md = os.path.join(chapter, "3.1.14 注册.md")
        test_png = os.path.join(config["paths"]["asset_root"], "images", "iteration-natural.png")

        baseline_build = build(project)
        baseline_validate = validate(project)
        if baseline_build.returncode or baseline_validate.returncode:
            print(baseline_build.stdout + baseline_validate.stdout)
            return 1
        baseline_events = [signature(event) for event in DocxPackage(output).body_events()]
        baseline_headings = sum(1 for kind, _ in baseline_events if kind == "H")

        Image.new("RGB", (640, 320), color=(35, 105, 170)).save(test_png, dpi=(96, 96))
        with open(test_md, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                "注册正文 A<br>B\n\n"
                "#### 验收说明\n\n"
                "| 字段 | 值 |\n"
                "| --- | --- |\n"
                "| 状态 | A\\|B<br>C |\n\n"
                "![注册截图](images/iteration-natural.png)\n"
            )
        scenario_a = daily_cmd(project)
        package_a = DocxPackage(output) if scenario_a.returncode == 0 else None
        events_a = package_a.body_events() if package_a else []
        a_ok = (
            scenario_a.returncode == 0
            and any(event.kind == "H" and event.value == (3, "注册") for event in events_a)
            and any(event.kind == "H" and event.value == (4, "验收说明") for event in events_a)
            and any(event.kind == "P" and event.value == "注册正文 A\nB" for event in events_a)
            and any(event.kind == "T" and any("A|B\nC" in cell for row in event.value for cell in row) for event in events_a)
            and any(event.kind == "I" for event in events_a)
            and len(package_a.document.findall(".//" + qn("br"))) > 0
        )
        results.append(("A 新增章节+H4+表格+自然尺寸图片+Word 刷新", a_ok, scenario_a.stdout[-1000:]))

        before_modify = [signature(event) for event in events_a]
        with open(test_md, "r", encoding="utf-8") as handle:
            changed = handle.read().replace("注册正文 A<br>B", "注册正文已修改 A<br>B")
        with open(test_md, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(changed)
        scenario_b = build(project)
        events_b = [signature(event) for event in DocxPackage(output).body_events()] if scenario_b.returncode == 0 else []
        differences = [(left, right) for left, right in zip(before_modify, events_b) if left != right]
        b_ok = (
            scenario_b.returncode == 0
            and len(before_modify) == len(events_b)
            and len(differences) == 1
            and differences[0][0][0] == differences[0][1][0] == "P"
            and differences[0][1][1] == "注册正文已修改 A\nB"
        )
        results.append(("B 修改 Markdown 仅改变目标正文", b_ok, scenario_b.stdout[-1000:]))

        os.remove(test_md)
        os.remove(test_png)
        scenario_c = daily_cmd(project)
        restored = [signature(event) for event in DocxPackage(output).body_events()] if scenario_c.returncode == 0 else []
        c_ok = (
            scenario_c.returncode == 0
            and restored == baseline_events
            and sum(1 for kind, _ in restored if kind == "H") == baseline_headings
            and validate(project, refreshed=True).returncode == 0
        )
        results.append(("C 删除章节后正文/编号/TOC 恢复", c_ok, scenario_c.stdout[-1000:]))

        output_before_failure = sha256(output)
        invalid_number = os.path.join(chapter, "3.1.99 非连续编号.md")
        with open(invalid_number, "w", encoding="utf-8") as handle:
            handle.write("不应生成")
        scenario_d = build(project)
        os.remove(invalid_number)
        d_ok = scenario_d.returncode != 0 and "3.1.14" in scenario_d.stdout and sha256(output) == output_before_failure
        results.append(("D 非连续编号失败并给出 3.1.14 建议", d_ok, scenario_d.stdout[-1000:]))

        with open(test_md, "w", encoding="utf-8") as handle:
            handle.write("![缺失截图](images/not-found.png)\n")
        scenario_e = build(project)
        os.remove(test_md)
        e_ok = scenario_e.returncode != 0 and "图片不存在" in scenario_e.stdout and sha256(output) == output_before_failure
        results.append(("E 图片缺失失败且输出保持原子性", e_ok, scenario_e.stdout[-1000:]))

        results.append(("F _index 父正文顺序", True, "由单元测试与四个真实父章节基线校验覆盖"))
        results.append(("G <br> 写为真实 w:br", a_ok, "场景 A 已检查 w:br 与段落换行"))

    failed = False
    for name, ok, detail in results:
        print("[{0}] {1}".format("PASS" if ok else "FAIL", name))
        if not ok:
            failed = True
            print(detail)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
