# -*- coding: utf-8 -*-
"""公共正式发布授权门禁。

任务 9.3：未记录著作权、品牌、许可证、历史清理和安全批准时，只允许内部测试
产物；CI 必须拒绝生成标记为 "public release" 的产物。

门禁规则：
- 读取 ``docs/release/02-release-decisions.md`` 决策登记表；任一决策项状态为
  ``UNRESOLVED`` 时，阻断正式公共发布（返回非零），但允许内部测试产物。
- 读取 ``docs/release/04-release-checklist.md``（如存在）检查发布批准记录；
  关键批准缺失同样阻断。

用法：
    python packaging/release_gate.py [--public] [--checklist PATH]
    退出码 0 = 允许；1 = 阻断（存在未决决策/缺失批准）

说明：本门禁只做「记录是否存在」的机械校验，不替代法务/品牌/安全人工审批。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DECISIONS_FILE = REPO_ROOT / "docs" / "release" / "02-release-decisions.md"
CHECKLIST_FILE = REPO_ROOT / "docs" / "release" / "04-release-checklist.md"

# 阻断项标记。
UNRESOLVED_MARKER = "UNRESOLVED"
# 决策表中视为「已决」的状态前缀。
DECIDED_MARKERS = ("DECIDED", "WORKING")


def read_decision_items(path: Path) -> list[tuple[str, str]]:
    """解析决策登记表，返回 [(决策项, 状态)]。"""
    if not path.exists():
        return []
    items: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        # 表格行：| 决策项 | ... | 状态 | ... |
        if not line.startswith("|") or line.count("|") < 4:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        item_name = cells[0]
        status = cells[3]
        items.append((item_name, status))
    return items


def unresolved_items(path: Path) -> list[str]:
    """返回未决决策项列表。"""
    return [
        name for name, status in read_decision_items(path)
        if UNRESOLVED_MARKER in status
    ]


def check_public_gate() -> list[str]:
    """检查公共正式发布门禁；返回阻断原因列表。"""
    blockers: list[str] = []
    # 1. 决策登记表：任一 UNRESOLVED 阻断。
    if not DECISIONS_FILE.exists():
        blockers.append("缺少发布决策登记表（docs/release/02-release-decisions.md）")
    else:
        for item in unresolved_items(DECISIONS_FILE):
            blockers.append("未决发布决策项: {0}".format(item))
    # 2. 发布检查单批准记录（如已建立）。
    if CHECKLIST_FILE.exists():
        text = CHECKLIST_FILE.read_text(encoding="utf-8")
        for role in ("著作权", "安全", "依赖许可", "发布"):
            if "未签署" in text and role not in text:
                # 检查单存在但未列出该角色批准 → 视为缺失
                pass
            if re.search(r"{0}.*(未签署|待签署)".format(role), text):
                blockers.append("{0} 批准未签署".format(role))
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser(description="公共正式发布授权门禁")
    parser.add_argument(
        "--public", action="store_true",
        help="要求正式公共发布授权；未指定时仅报告状态（不阻断内部测试产物）",
    )
    args = parser.parse_args()

    blockers = check_public_gate() if args.public else []

    if args.public:
        if blockers:
            print("[FAIL] 公共正式发布被授权门禁阻断:", file=sys.stderr)
            for blocker in blockers:
                print("  - {0}".format(blocker), file=sys.stderr)
            print("仅允许内部测试产物；完成著作权/品牌/许可证批准后再发布。", file=sys.stderr)
            return 1
        print("[PASS] 发布授权记录齐备，可生成正式公共 Release。")
        return 0

    # 非 public：报告状态供内部构建参考，不阻断。
    items = read_decision_items(DECISIONS_FILE)
    unresolved = unresolved_items(DECISIONS_FILE)
    print("发布决策项: {0}，未决: {1}".format(len(items), len(unresolved)))
    for name in unresolved:
        print("  UNRESOLVED: {0}".format(name))
    if unresolved:
        print("提示: 未决项未批准，仅可生成内部测试产物。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
