# -*- coding: utf-8 -*-
"""未保存内容确认对话框：统一「保存/不保存/取消」或二选确认。

``confirm_unsaved_dialog`` 是 ``UnsavedResolver`` 的默认实现，按场景提供
按钮文案与数量：exit/switch 三选（保存/不保存/取消），delete 二选（放弃/
取消），rename 三选（先保存/放弃/取消）。离屏测试通过注入桩替换本对话框，
不弹真实窗口。
"""

from __future__ import annotations

from typing import List

from PySide6.QtWidgets import QMessageBox

from doc_tool.application.content.unsaved import (
    UnsavedChoice,
    UnsavedResolver,
)

# 场景 → 对话框上下文文案。
_CONTEXT_TEXT = {
    "exit": "退出",
    "switch": "切换项目",
    "delete": "删除文件",
    "rename": "重命名文件",
}


def confirm_unsaved_dialog(rel_paths: List[str], context: str) -> UnsavedChoice:
    """按场景弹出未保存确认，返回用户决策。"""
    box = QMessageBox()
    box.setWindowTitle("未保存的更改")
    box.setIcon(QMessageBox.Icon.Warning)
    label = _CONTEXT_TEXT.get(context, context)
    body = "\n".join("  " + rel for rel in rel_paths[:10])
    more = "" if len(rel_paths) <= 10 else "\n  …共 {0} 个".format(len(rel_paths))
    box.setText(
        "当前有未保存的编辑：\n{0}{1}\n\n{2}前请选择：".format(body, more, label)
    )

    if context == "delete":
        discard = box.addButton("放弃", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is discard:
            return UnsavedChoice.DISCARD
        return UnsavedChoice.CANCEL

    if context == "rename":
        save = box.addButton("先保存", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("放弃", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return UnsavedChoice.SAVE
        if clicked is discard:
            return UnsavedChoice.DISCARD
        return UnsavedChoice.CANCEL

    save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
    discard = box.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is save:
        return UnsavedChoice.SAVE
    if clicked is discard:
        return UnsavedChoice.DISCARD
    return UnsavedChoice.CANCEL
