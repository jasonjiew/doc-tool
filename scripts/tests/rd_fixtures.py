# -*- coding: utf-8 -*-
"""RD 工作区界面夹具：三成员工作区 + 稳定条目 + 显式关系 + 版本集合。

用于验证“创建研发工作区 → 声明条目/建立关系 → 查缺漏/影响 → 复核 →
形成版本集合”的最短路径，以及单文档无工作区时的可用性。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts"), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_project_build as T  # noqa: E402
from doc_tool.application.collection import build_manifest, register_manifest  # noqa: E402
from doc_tool.application.workspace import add_project, create_workspace  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

MARKER = "<!-- DOC-ITEM: projectId={project_id} kind={kind} id={item_id} alias={alias} -->"

#: 逻辑条目名 -> 稳定 UUID（确定性，便于关系文件与断言引用）。
ITEM_IDS = {
    "R-1": "6f1f5c4e-0d1a-5b2c-9f31-0a1b2c3d4e01",
    "D-1": "6f1f5c4e-0d1a-5b2c-9f31-0a1b2c3d4e02",
    "T-1": "6f1f5c4e-0d1a-5b2c-9f31-0a1b2c3d4e03",
}

MEMBER_SPECS = (
    ("documents/需求", "requirement", "需求规格", (
        ("1 概述/1.1 背景.md", "requirement", "R-1", "离线出稿", "系统应支持离线出稿。"),
    )),
    ("documents/设计", "design", "设计说明", (
        ("2 详细设计/2.1 架构.md", "design", "D-1", "装配式内核", "设计采用装配式内核。"),
    )),
    ("documents/测试", "test", "测试方案", (
        ("3 测试/3.1 用例.md", "test", "T-1", "出稿用例", "验证离线出稿。"),
    )),
)


def build_member(root: Path, name: str, *, document_name: str,
                 items: Sequence[Sequence[str]]) -> Path:
    """一个带稳定条目的成员项目（复用既有项目夹具与清单模型）。"""
    project = Path(root) / name
    T._setup_project(str(project))
    manifest = T._make_manifest(str(project))
    manifest.documentName = document_name
    manifest.save(str(project))
    content = project / manifest.relative_content_root()
    for relative, kind, item_id, alias, body in items:
        path = content / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# {0}\n\n{1}\n\n{2}\n".format(
                relative[:-3], body,
                MARKER.format(
                    project_id=manifest.projectId, kind=kind,
                    item_id=ITEM_IDS.get(item_id, item_id), alias=alias,
                ),
            ),
            encoding="utf-8",
        )
    return project


def build_rd_workspace(root: Path, *, with_collection: bool = True) -> Dict[str, object]:
    """建成三成员工作区；返回目录、成员项目、projectId 与关系文件。"""
    import yaml

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace = create_workspace(root, name="研发交付", collection_version="1.0")
    workspace.save(root)
    projects: Dict[str, Path] = {}
    for name, _role, document_name, items in MEMBER_SPECS:
        projects[name] = build_member(root, name, document_name=document_name, items=items)
    for name, role, _document_name, _items in MEMBER_SPECS:
        add_project(workspace, projects[name], role=role, copy_external=False)
    workspace.save(root)
    ids = {name: ProjectManifest.load(path).projectId for name, path in projects.items()}
    relations = root / "relations.yml"
    relations.write_text(
        yaml.safe_dump(
            {
                "schemaVersion": 1,
                "relations": [
                    {
                        "relationId": "rel-design-satisfies",
                        "type": "satisfies",
                        "from": {"projectId": ids["documents/设计"], "itemId": ITEM_IDS["D-1"]},
                        "to": {"projectId": ids["documents/需求"], "itemId": ITEM_IDS["R-1"]},
                    },
                    {
                        "relationId": "rel-test-verifies",
                        "type": "verifies",
                        "from": {"projectId": ids["documents/测试"], "itemId": ITEM_IDS["T-1"]},
                        "to": {"projectId": ids["documents/需求"], "itemId": ITEM_IDS["R-1"]},
                    },
                ],
            },
            allow_unicode=True, sort_keys=False,
        ),
        encoding="utf-8",
    )
    if with_collection:
        manifest = build_manifest(projects["documents/需求"], version="1.0", label="基线 1.0")
        register_manifest(projects["documents/需求"], manifest)
    return {
        "root": root,
        "projects": projects,
        "ids": ids,
        "itemIds": dict(ITEM_IDS),
        "relations": relations,
        "requirement_root": projects["documents/需求"],
        "design_root": projects["documents/设计"],
        "test_root": projects["documents/测试"],
    }


class FakeRdHost:
    """记录动作的最小宿主：验证界面是否调用真实入口。"""

    def __init__(self, project_root: str = "", *, buffers=None, current_chapter: str = ""):
        self.project_root = str(project_root or "")
        self.buffers = dict(buffers or {})
        self.current_chapter = current_chapter
        self.statuses = []
        self.opened_sources = []
        self.opened_projects = []
        self.opened_paths = []
        self.applied_edits = []
        self.saved_chapters = []
        self.delivery_calls = []
        self.cursor_line = 0

    def rd_project_root(self):
        return self.project_root

    def rd_project_id(self):
        try:
            return str(ProjectManifest.load(self.project_root).projectId)
        except Exception:  # noqa: BLE001 - 夹具缺清单时按空身份
            return ""

    def rd_collect_buffers(self):
        return dict(self.buffers)

    def rd_current_chapter(self):
        return self.current_chapter

    def rd_cursor_line(self):
        return self.cursor_line

    def rd_open_source(self, rel_path, line_no, source):
        self.opened_sources.append((rel_path, line_no, source))
        return True

    def rd_open_project(self, path):
        self.opened_projects.append(str(path))
        return True

    def rd_open_path(self, path):
        self.opened_paths.append(str(path))
        return True

    def rd_apply_item_edit(self, rel_path, text, message):
        self.applied_edits.append((rel_path, text, message))
        self.buffers[rel_path] = text
        return True

    def rd_save_chapters(self, rel_paths):
        self.saved_chapters.append(list(rel_paths))
        return True

    def rd_member_delivery(self, root):
        self.delivery_calls.append(str(root))
        return "已复用批量交付入口：{0}".format(root)

    def rd_status(self, message):
        self.statuses.append(str(message))
