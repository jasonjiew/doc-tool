# -*- coding: utf-8 -*-
"""项目相对路径解析与目录包含校验。

任务 1.4：实现 ``ProjectPaths`` 相对路径解析、项目根包含校验和中文特殊路径测试。

所有持久化资源路径必须相对项目根；解析后仍须位于项目根内，否则视为安全错误。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

from doc_tool.domain.errors import PathEscapeError


# 项目内标准子目录（相对项目根），均为相对路径，不写入安装机器绝对路径。
DIR_ORIGINAL = "original"
DIR_TEMPLATE = "template"
DIR_CONTENT = "content"
DIR_ASSETS = "assets"
DIR_OUTPUT = "output"
DIR_LOGS = "logs"
DIR_STATE = ".state"

# 源文档与模板的固定文件名（项目内稳定，不依赖外部文件名）。
SOURCE_DOCX_NAME = "source.docx"
TEMPLATE_DOCX_NAME = "template.docx"
MANIFEST_NAME = "project.yml"
LOCK_NAME = "project.lock"


class ProjectPaths:
    """项目工作区路径解析与约束。

    项目根由用户选择，所有资源路径相对项目根存储和解析。
    解析任意相对路径后必须仍在项目根内，防止 ``..`` 或绝对路径越界。
    """

    def __init__(self, project_root: Union[str, Path]) -> None:
        self.root: Path = Path(project_root).resolve()

    # --- 标准路径属性 ---

    @property
    def manifest_file(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def original_dir(self) -> Path:
        return self.root / DIR_ORIGINAL

    @property
    def source_docx(self) -> Path:
        return self.original_dir / SOURCE_DOCX_NAME

    @property
    def template_dir(self) -> Path:
        return self.root / DIR_TEMPLATE

    @property
    def template_docx(self) -> Path:
        return self.template_dir / TEMPLATE_DOCX_NAME

    @property
    def content_root(self) -> Path:
        return self.root / DIR_CONTENT

    @property
    def assets_root(self) -> Path:
        return self.root / DIR_ASSETS

    @property
    def output_dir(self) -> Path:
        return self.root / DIR_OUTPUT

    @property
    def logs_dir(self) -> Path:
        return self.root / DIR_LOGS

    @property
    def state_dir(self) -> Path:
        return self.root / DIR_STATE

    @property
    def lock_file(self) -> Path:
        return self.state_dir / LOCK_NAME

    def content_dir(self, document_type: str) -> Path:
        """指定文档类型的章节 Markdown 根目录。"""
        return self.content_root / document_type

    def assets_dir(self, document_type: str) -> Path:
        """指定文档类型的资源根目录。"""
        return self.assets_root / document_type

    def images_dir(self, document_type: str) -> Path:
        return self.assets_dir(document_type) / "images"

    def tables_dir(self, document_type: str) -> Path:
        return self.assets_dir(document_type) / "tables"

    # --- 相对路径与包含校验 ---

    def to_relative(self, absolute_path: Union[str, Path]) -> str:
        """将绝对路径转为相对项目根的 POSIX 风格字符串。

        越界时抛出 ``PathEscapeError``，确保写入清单的路径不会指向项目外。
        """
        target = Path(absolute_path).resolve()
        self._ensure_inside(target)
        rel = target.relative_to(self.root)
        return rel.as_posix()

    def resolve(self, relative_path: str) -> Path:
        """将相对项目根的路径解析为绝对路径，并校验仍在项目根内。

        支持中文、空格、括号、``&`` 等合法 Windows 路径字符。
        """
        if not relative_path:
            raise PathEscapeError(
                "空路径不允许。",
                suggested_action="请提供有效的相对路径。",
                details={"input": "(empty)"},
            )
        # 显式拒绝绝对路径和盘符（Windows），防止绕过项目根。
        cleaned = relative_path.replace("\\", "/")
        if os.path.isabs(relative_path) or cleaned.startswith("/"):
            raise PathEscapeError(
                "不允许使用绝对路径作为项目内资源路径。",
                suggested_action="请使用相对项目根的路径。",
                details={"input": relative_path},
            )
        joined = self.root / cleaned
        resolved = joined.resolve()
        self._ensure_inside(resolved)
        return resolved

    def is_inside(self, absolute_path: Union[str, Path]) -> bool:
        """判断绝对路径是否在项目根内（不抛异常）。"""
        try:
            target = Path(absolute_path).resolve()
            self._ensure_inside(target)
            return True
        except PathEscapeError:
            return False

    def _ensure_inside(self, target: Path) -> None:
        """校验目标路径在项目根内，使用路径前缀匹配防穿越。"""
        root_str = str(self.root)
        target_str = str(target)
        # 必须等于根或以根 + 分隔符开头，防止 ``/project`` 误匹配 ``/project-other``。
        if target_str != root_str and not target_str.startswith(root_str + os.sep):
            raise PathEscapeError(
                "资源路径越出项目根目录。",
                suggested_action="请检查 Markdown 中的资源引用路径。",
                details={
                    "projectRoot": self._safe_display(self.root),
                    "resolved": self._safe_display(target),
                },
            )

    @staticmethod
    def _safe_display(path: Path) -> str:
        """用于错误详情的脱敏路径显示（不暴露完整业务路径结构）。"""
        return str(path)

    def ensure_directories(self, document_type: str) -> None:
        """创建项目标准目录结构（幂等）。"""
        for directory in (
            self.original_dir,
            self.template_dir,
            self.content_dir(document_type),
            self.images_dir(document_type),
            self.tables_dir(document_type),
            self.output_dir,
            self.logs_dir,
            self.state_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        return "ProjectPaths(root={0!r})".format(str(self.root))
