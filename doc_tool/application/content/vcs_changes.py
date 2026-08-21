# -*- coding: utf-8 -*-
"""版本控制变更检测：Git > SVN > 本地快照兜底。

本模块是纯 Python 应用层服务（无 Qt、无 CLI 依赖），回答一个问题：

    「当前打开的文档项目里，有哪些尚未提交的实际变化？」

语义约定（需求第十二条）：
- Git 基线 = HEAD：staged + unstaged + untracked 全部算「工作树变化」，
  绝不拿「当前分支 vs main」做比较。
- SVN 基线 = 工作副本的 BASE 修订。
- 检测来源（source）：git / svn / local。local 表示版本控制不可用或
  不在版本控制内，由调用方继续使用原有本地快照机制（不回退删除）。
- 项目目录虽在仓库内、但被 ``.gitignore`` 忽略或从未 add 时，git 对它
  永远报「无变化」；此时同样回退 local，否则真实的新增/修改会被静默
  吞掉（见 ``GitChangeDetector.tracks_path``）。

隔离原则（需求第四条/第五条）：
- Repository Context 可共享：Git/SVN 仓库可能同时包含多个文档子项目。
- Project Context 必须隔离：每个窗口的检测器只保留属于自己
  ``project_root`` 目录内的变更。
- 仓库级状态缓存以 ``repository_root`` 为 key，且缓存内容必须是
  **未按项目过滤的仓库级原始变更**；每个窗口拿到缓存后仍按自己的
  ``project_root`` 过滤。绝不允许把「已按某项目过滤的报告」放进缓存
  供其它窗口复用——那正是多窗口串项目的根因。

数据结构：
- ``ChangedFile``：仓库级文件变更（含重命名旧路径、staged/unstaged/
  untracked 标记），为后续「需求 → 详细设计影响分析」预留干净接口。
- ``ChangedChapter``：映射到章节后的变更（chapter_id/title），
  资源（assets）变更会反查引用它的 Markdown 章节。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.tree import strip_number_prefix

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangedFile:
    """单条仓库级文件变更（相对仓库根的 POSIX 路径）。"""

    path: str  # 相对 repository_root 的 POSIX 路径
    change_type: str  # added | modified | deleted | renamed
    source: str  # git | svn | local
    project_root: str  # 文档项目根目录（绝对路径，检测时所属项目）
    abs_path: str = ""  # 绝对路径（便捷字段，未解析时为空）
    old_path: Optional[str] = None  # 仅 renamed：仓库内旧路径（POSIX）
    staged: bool = False  # git：已暂存到 index
    unstaged: bool = False  # git：工作树相对 index 有改动
    untracked: bool = False  # git/SVN：未跟踪文件（新增）

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "changeType": self.change_type,
            "source": self.source,
            "projectRoot": self.project_root,
            "absPath": self.abs_path,
            "oldPath": self.old_path,
            "staged": self.staged,
            "unstaged": self.unstaged,
            "untracked": self.untracked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChangedFile":
        return cls(
            path=str(data.get("path", "")),
            change_type=str(data.get("changeType", "modified")),
            source=str(data.get("source", "local")),
            project_root=str(data.get("projectRoot", "")),
            abs_path=str(data.get("absPath", "")),
            old_path=data.get("oldPath"),
            staged=bool(data.get("staged", False)),
            unstaged=bool(data.get("unstaged", False)),
            untracked=bool(data.get("untracked", False)),
        )


@dataclass(frozen=True)
class ChangedChapter:
    """章节级变更（映射后），供改动面板/后续影响分析消费。"""

    chapter_id: str  # "3.7.28"；项目级（project.yml）为空串
    title: str  # "客户管理"；项目级为 "项目配置"
    path: str  # 相对 content_root 的 POSIX 路径；project.yml 为 "project.yml"
    change_type: str  # added | modified | deleted | renamed
    source: str  # git | svn | local
    old_path: Optional[str] = None  # renamed 时的旧章节路径
    is_asset: bool = False  # 资源变更映射到的章节（章节本身未变）


@dataclass(frozen=True)
class ChangeReport:
    """一次检测的结果。source=local 表示应继续走本地快照兜底。"""

    source: str  # git | svn | local
    repository_root: Optional[str] = None  # 仓库根（git/svn 时）
    project_root: str = ""
    files: Tuple[ChangedFile, ...] = ()
    error: Optional[str] = None  # 检测过程中的非致命错误说明


# 仓库级原始变更条目（未按项目过滤，缓存用）。
# git: (path, change_type, old_path, staged, unstaged, untracked)
# svn: (path, change_type, untracked)
RepoEntry = Tuple

# 项目内部目录（相对 project_root）：不是文档变更，且回滚时绝不能
# 删除应用自身状态（.state）或构建产物（output/logs）。
_PROJECT_INTERNAL_DIRS = (".state", "output", "logs")

# 项目在版本控制视野之外（被忽略/未纳入索引）时的兜底说明。
UNTRACKED_PROJECT_NOTICE = (
    "项目未纳入 Git（被 .gitignore 忽略或从未 add），已回退本地快照检测"
)


def _project_path_spec(repo_root: Path, project_root: Path) -> str:
    """项目根相对仓库根的 pathspec；项目根即仓库根时返回 ``.``。"""
    rel = Path(project_root).relative_to(Path(repo_root)).as_posix()
    return "." if rel in ("", ".") else rel


def _filter_repo_entries(
    entries: Sequence[RepoEntry],
    repo_root: Path,
    project_root: Path,
    source: str,
    *,
    svn_mode: bool = False,
) -> List[ChangedFile]:
    """按 project_root 过滤仓库级原始变更并构造 ChangedFile 列表。

    这是 Project Context 隔离的唯一过滤点：无论缓存内容来自哪个窗口，
    都只保留属于当前 project_root 目录内的路径。
    """
    project_rel = project_root.relative_to(repo_root).as_posix()
    prefix = project_rel + "/" if project_rel != "." else ""
    project_root_str = str(project_root)
    files: List[ChangedFile] = []
    seen: set = set()
    for entry in entries:
        if svn_mode:
            path, change_type, untracked = entry
            old_path = None
            staged = unstaged = False
        else:
            path, change_type, old_path, staged, unstaged, untracked = entry
        if path in seen or not path.startswith(prefix):
            continue
        if prefix:
            proj_rel = path[len(prefix):]
        else:
            proj_rel = path
        if proj_rel.split("/", 1)[0] in _PROJECT_INTERNAL_DIRS:
            # 应用自身状态/产物目录不出现在报告（也绝不参与回滚）。
            continue
        seen.add(path)
        abs_path = (repo_root / path).resolve()
        files.append(
            ChangedFile(
                path=path,
                change_type=change_type,
                source=source,
                project_root=project_root_str,
                abs_path=str(abs_path),
                old_path=old_path,
                staged=staged,
                unstaged=unstaged,
                untracked=untracked,
            )
        )
    return files


# ---------------------------------------------------------------------------
# 仓库根查找
# ---------------------------------------------------------------------------


def find_git_repo_root(start: Path) -> Optional[Path]:
    """从 start 向父目录查找 .git（目录或 worktree 指针文件），返回仓库根。

    找不到返回 None。仅做文件系统探测，不执行 git 命令。
    """
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        git_marker = candidate / ".git"
        if git_marker.exists():
            return candidate
    return None


def find_svn_wc_root(start: Path) -> Optional[Path]:
    """从 start 向父目录查找 .svn 元数据目录，返回工作副本根。"""
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".svn").is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Git 解析
# ---------------------------------------------------------------------------

# 状态码 → 变更类型
_GIT_TYPE_FROM_STATUS = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed"}


def _run(
    args: Sequence[str],
    cwd: Path,
    timeout: float,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> subprocess.CompletedProcess:
    """执行子进程（默认 subprocess.run，测试可注入假 runner）。"""
    if runner is not None:
        return runner(list(args), cwd=str(cwd))
    return subprocess.run(
        list(args),
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _decode(bytes_value: bytes) -> str:
    """git 输出按 UTF-8 解码；非法字节以替换符保留，不中断解析。"""
    if bytes_value is None:
        return ""
    return bytes_value.decode("utf-8", errors="replace")


def parse_git_status_z(output: bytes) -> Dict[str, Tuple[str, str, Optional[str]]]:
    """解析 ``git status --porcelain -z --untracked-files=all`` 输出。

    返回 ``{path: (X, Y, old_path)}``；old_path 仅在 rename 条目时非空
    （-z 模式下 rename 的路径顺序是 ``R  new\\0old\\0``，与行模式相反，
    已按实测确认）。
    """
    text = _decode(output)
    chunks = [chunk for chunk in text.split("\0") if chunk]
    result: Dict[str, Tuple[str, str, Optional[str]]] = {}
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        if len(chunk) < 3 or chunk[2] != " ":
            # 防御：异常格式（如路径含特殊字符）跳过该条目。
            index += 1
            continue
        codes = chunk[:2]
        path = chunk[3:]
        x, y = codes[0], codes[1]
        if x == "R" or y == "R":
            # -z 下 rename 条目为两段：new 在 codes 段，old 为下一 chunk。
            old_path = chunks[index + 1] if index + 1 < len(chunks) else None
            result[path] = (x, y, old_path)
            index += 2
        else:
            result[path] = (x, y, None)
            index += 1
    return result


def parse_git_name_status_z(output: bytes) -> Dict[str, Tuple[str, Optional[str]]]:
    """解析 ``git diff --name-status -z -M`` 输出 → ``{new: (type, old)}``。

    条目格式：``STATUS\\0path\\0`` 或 ``R{score}\\0old\\0new\\0``。
    """
    text = _decode(output)
    chunks = [chunk for chunk in text.split("\0") if chunk]
    result: Dict[str, Tuple[str, Optional[str]]] = {}
    index = 0
    while index < len(chunks):
        token = chunks[index]
        if token.startswith("R"):
            if index + 2 >= len(chunks):
                break
            old_path = chunks[index + 1]
            new_path = chunks[index + 2]
            result[new_path] = ("renamed", old_path)
            index += 3
        else:
            change_type = _GIT_TYPE_FROM_STATUS.get(token, "modified")
            if index + 1 >= len(chunks):
                break
            path = chunks[index + 1]
            result[path] = (change_type, None)
            index += 2
    return result


def _git_type_merge(
    staged: Optional[Tuple[str, Optional[str]]],
    unstaged: Optional[Tuple[str, Optional[str]]],
    status_x: str,
    status_y: str,
    untracked: bool,
) -> Tuple[str, Optional[str]]:
    """合并 staged/unstaged 两条 diff 记录为一个变更类型与旧路径。

    优先级：renamed > added > deleted > modified；staged 的旧路径优先。
    """
    old_path = None
    if staged is not None:
        old_path = staged[1] or old_path
    if unstaged is not None:
        old_path = unstaged[1] or old_path

    staged_type = staged[0] if staged is not None else None
    unstaged_type = unstaged[0] if unstaged is not None else None

    if untracked:
        return "added", old_path
    if staged_type == "renamed" or unstaged_type == "renamed" or status_x == "R" or status_y == "R":
        return "renamed", old_path
    if staged_type == "added" or unstaged_type == "added":
        return "added", old_path
    if staged_type == "deleted" and unstaged_type is None:
        return "deleted", old_path
    if unstaged_type == "deleted" and staged_type is None:
        return "deleted", old_path
    if staged_type == "deleted" or unstaged_type == "deleted":
        # staged 删除 + 工作树又改回（DD/DA 等罕见状态）：视为修改。
        return "modified", old_path
    return "modified", old_path


class GitChangeDetector:
    """基于 Git 的变更检测器（相对 HEAD 的工作树变化）。"""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        git_executable: Optional[str] = None,
    ) -> None:
        self._timeout = timeout
        self._runner = runner
        self._git = git_executable or shutil.which("git") or "git"

    def is_available(self) -> bool:
        """git 命令是否可执行。"""
        if self._runner is not None:
            return True  # 测试注入
        return shutil.which(self._git) is not None

    def tracks_path(self, repo_root: Path, path_spec: str) -> bool:
        """``path_spec`` 目录下是否存在被 git 跟踪的文件。

        用于区分「项目干净」与「项目在 git 视野之外」：项目目录被
        ``.gitignore`` 忽略（或从未 add 过）时，``git status`` 对它永远
        沉默，于是新增/修改会被静默吞掉、界面显示「无改动」。这种情况下
        必须回退本地快照，而不是相信 git 的沉默。

        命令失败或 git 不可用时返回 True（保守：维持 git 模式，绝不把
        干净且已跟踪的项目误判成「未纳入 git」）。
        """
        if not self.is_available():
            return True
        try:
            proc = _run(
                [self._git, "ls-files", "-z", "--", path_spec or "."],
                cwd=Path(repo_root),
                timeout=self._timeout,
                runner=self._runner,
            )
        except (OSError, subprocess.SubprocessError):
            return True
        if proc.returncode != 0:
            return True
        return bool((proc.stdout or b"").strip(b"\0"))

    def repo_changes(self, repo_root: Path) -> Tuple[List[RepoEntry], Optional[str]]:
        """读取仓库级原始变更（未按项目过滤，可安全缓存共享）。

        返回 ``(entries, error)``；git 不可用/执行异常时 entries 为空列表
        且 error 非空。entries 形如
        ``(path, change_type, old_path, staged, unstaged, untracked)``。
        """
        repo_root = Path(repo_root).resolve()
        if not self.is_available():
            return [], "git 命令不可用"
        try:
            # 1) untracked + staged/unstaged 标记
            status_proc = _run(
                [self._git, "status", "--porcelain", "-z", "--untracked-files=all"],
                cwd=repo_root,
                timeout=self._timeout,
                runner=self._runner,
            )
            if status_proc.returncode != 0:
                # git status 失败（仓库损坏/权限问题）：整体视为不可用，
                # 交由上层回退 SVN/本地快照，避免误报「无变化」。
                return [], "git status 执行失败：{0}".format(
                    _decode(status_proc.stderr)[:120]
                )
            status_map = parse_git_status_z(status_proc.stdout)
            # 2) staged（index vs HEAD）— 权威 rename 检测。
            #    无提交仓库（无 HEAD）等场景下 diff 会失败：此时退回
            #    status 码推导（untracked 全部按新增处理），不整体报错。
            staged_proc = _run(
                [self._git, "diff", "--cached", "--name-status", "-z", "-M", "HEAD"],
                cwd=repo_root,
                timeout=self._timeout,
                runner=self._runner,
            )
            staged_map = (
                parse_git_name_status_z(staged_proc.stdout)
                if staged_proc.returncode == 0
                else {}
            )
            # 3) unstaged（worktree vs index）— 权威 rename 检测
            unstaged_proc = _run(
                [self._git, "diff", "--name-status", "-z", "-M"],
                cwd=repo_root,
                timeout=self._timeout,
                runner=self._runner,
            )
            unstaged_map = (
                parse_git_name_status_z(unstaged_proc.stdout)
                if unstaged_proc.returncode == 0
                else {}
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return [], "git 执行失败：{0}".format(str(exc)[:160])

        entries: List[RepoEntry] = []
        seen: set = set()
        for new_path, (x, y, status_old) in status_map.items():
            if new_path in seen:
                continue
            seen.add(new_path)
            if x == "?" and y == "?":
                entries.append((new_path, "added", None, False, False, True))
                continue
            staged_entry = staged_map.get(new_path)
            unstaged_entry = unstaged_map.get(new_path)
            change_type, old_path = _git_type_merge(
                staged_entry, unstaged_entry, x, y, False
            )
            if old_path is None:
                old_path = status_old
            entries.append(
                (
                    new_path,
                    change_type,
                    old_path,
                    x != " ",
                    y != " ",
                    False,
                )
            )
        entries.sort(key=lambda item: item[0])
        return entries, None

    def detect(self, project_root: Path) -> ChangeReport:
        """检测 project_root 内相对 HEAD 的全部变化（含 staged/unstaged/untracked）。"""
        project_root = Path(project_root).resolve()
        repo_root = find_git_repo_root(project_root)
        if repo_root is None:
            return ChangeReport(source="local", project_root=str(project_root))
        entries, error = self.repo_changes(repo_root)
        if not entries and error:
            # git 存在但命令不可用/执行异常：视为本地兜底并记录原因。
            return ChangeReport(
                source="local",
                repository_root=str(repo_root),
                project_root=str(project_root),
                error=error,
            )
        files = _filter_repo_entries(
            entries, repo_root, project_root, "git"
        )
        if not files and not self.tracks_path(
            repo_root, _project_path_spec(repo_root, project_root)
        ):
            # 项目在 git 视野之外：git 的「无变化」不可信，回退本地快照。
            return ChangeReport(
                source="local",
                repository_root=str(repo_root),
                project_root=str(project_root),
                error=UNTRACKED_PROJECT_NOTICE,
            )
        return ChangeReport(
            source="git",
            repository_root=str(repo_root),
            project_root=str(project_root),
            files=tuple(files),
            error=error,
        )


# ---------------------------------------------------------------------------
# SVN 解析
# ---------------------------------------------------------------------------

_SVN_ITEM_TO_TYPE = {
    "modified": "modified",
    "added": "added",
    "deleted": "deleted",
    "replaced": "renamed",
    "missing": "deleted",
    "unversioned": "added",
    "conflicted": "modified",
    "merged": "modified",
    "obstructed": "modified",
    "incomplete": "modified",
}


def parse_svn_status_xml(output: bytes) -> Dict[str, Tuple[str, bool]]:
    """解析 ``svn status --xml`` 输出 → ``{path: (change_type, untracked)}``。

    path 相对执行 svn status 的目录（工作副本根）。
    """
    result: Dict[str, Tuple[str, bool]] = {}
    try:
        root = ET.fromstring(output.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return result
    for entry in root.iter("entry"):
        rel_path = str(entry.get("path", "")).replace("\\", "/")
        if not rel_path:
            continue
        wc_status = entry.find("wc-status")
        if wc_status is None:
            continue
        item = str(wc_status.get("item", "")).strip()
        untracked = item == "unversioned"
        copied = str(wc_status.get("copied", "")).strip().lower() == "true"
        change_type = _SVN_ITEM_TO_TYPE.get(item)
        if change_type is None:
            continue
        if copied and item == "added":
            # SVN 的 copy（含 rename 的"复制+删除"）→ 视作 renamed（旧路径不可得）。
            change_type = "renamed"
        result[rel_path] = (change_type, untracked)
    return result


class SvnChangeDetector:
    """基于 SVN 的变更检测器（相对工作副本 BASE 修订）。"""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        svn_executable: Optional[str] = None,
    ) -> None:
        self._timeout = timeout
        self._runner = runner
        self._svn = svn_executable or shutil.which("svn") or "svn"

    def is_available(self) -> bool:
        if self._runner is not None:
            return True  # 测试注入
        return shutil.which(self._svn) is not None

    def wc_changes(self, wc_root: Path) -> Tuple[List[RepoEntry], Optional[str]]:
        """读取工作副本原始变更（未按项目过滤，可安全缓存共享）。

        返回 ``(entries, error)``；entries 形如 ``(path, change_type, untracked)``。
        """
        wc_root = Path(wc_root).resolve()
        if not self.is_available():
            return [], "svn 命令不可用"
        try:
            proc = _run(
                [self._svn, "status", "--xml"],
                cwd=wc_root,
                timeout=self._timeout,
                runner=self._runner,
            )
            if proc.returncode != 0:
                return [], "svn status 返回非零：{0}".format(
                    _decode(proc.stderr)[:120]
                )
            status_map = parse_svn_status_xml(proc.stdout)
        except (OSError, subprocess.SubprocessError) as exc:
            return [], "svn 执行失败：{0}".format(str(exc)[:160])
        entries: List[RepoEntry] = []
        for rel_path, (change_type, untracked) in status_map.items():
            entries.append((rel_path, change_type, untracked))
        entries.sort(key=lambda item: item[0])
        return entries, None

    def detect(self, project_root: Path) -> ChangeReport:
        project_root = Path(project_root).resolve()
        wc_root = find_svn_wc_root(project_root)
        if wc_root is None:
            return ChangeReport(source="local", project_root=str(project_root))
        entries, error = self.wc_changes(wc_root)
        if not entries and error:
            # svn 存在但命令不可用/执行异常：视为本地兜底并记录原因。
            return ChangeReport(
                source="local",
                repository_root=str(wc_root),
                project_root=str(project_root),
                error=error,
            )
        files = _filter_repo_entries(
            entries, wc_root, project_root, "svn", svn_mode=True
        )
        return ChangeReport(
            source="svn",
            repository_root=str(wc_root),
            project_root=str(project_root),
            files=tuple(files),
            error=error,
        )


# ---------------------------------------------------------------------------
# 仓库级缓存（以 repository_root 为 key；缓存未过滤的仓库原始变更）
# ---------------------------------------------------------------------------

# {repository_root: (monotonic 时间戳, 原始 entries, error)}
_GIT_CACHE: Dict[str, Tuple[float, Tuple[RepoEntry, ...], Optional[str]]] = {}
_SVN_CACHE: Dict[str, Tuple[float, Tuple[RepoEntry, ...], Optional[str]]] = {}


def clear_vcs_cache() -> None:
    """清空全部仓库级缓存（测试用）。"""
    _GIT_CACHE.clear()
    _SVN_CACHE.clear()


class ChangeDetectionService:
    """窗口级变更检测门面：Git > SVN > local。

    每个窗口持有自己的实例（Project Context 隔离）；仓库级状态缓存
    以 repository_root 为 key 全局共享，且缓存内容为未过滤的原始变更，
    每个窗口取到后按自己的 project_root 过滤（Repository Context 可共享）。
    """

    def __init__(
        self,
        project_root: Path,
        content_root: Path,
        *,
        timeout: float = 20.0,
        cache_ttl: float = 2.0,
        git_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        svn_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._content_root = Path(content_root).resolve()
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        self._git = GitChangeDetector(timeout=timeout, runner=git_runner)
        self._svn = SvnChangeDetector(timeout=timeout, runner=svn_runner)
        # 「项目是否被 git 跟踪」的窗口级缓存：(monotonic, tracked)。
        # 只在项目零变更时才需要，且跟踪状态几乎不变，用较长 TTL 避免
        # 每次刷新都多起一个 git 进程。
        self._tracked_cache: Optional[Tuple[float, bool]] = None

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def content_root(self) -> Path:
        return self._content_root

    @staticmethod
    def _cached(
        cache: Dict[str, Tuple[float, Tuple[RepoEntry, ...], Optional[str]]],
        repo_root: Path,
        ttl: float,
    ) -> Optional[Tuple[Tuple[RepoEntry, ...], Optional[str]]]:
        entry = cache.get(str(repo_root))
        if entry is None:
            return None
        timestamp, entries, error = entry
        if time.monotonic() - timestamp > ttl:
            return None
        return entries, error

    def detect(self) -> ChangeReport:
        """执行检测：Git → SVN → local。

        local 报告不携带文件（文件级状态由调用方用本地快照推导），
        但 source 字段供界面标注「检测来源」。
        """
        # --- Git ---
        repo_root = find_git_repo_root(self._project_root)
        if repo_root is not None:
            cached = self._cached(_GIT_CACHE, repo_root, self._cache_ttl)
            if cached is not None:
                entries, error = cached
            else:
                entries, error = self._git.repo_changes(repo_root)
                _GIT_CACHE[str(repo_root)] = (time.monotonic(), tuple(entries), error)
            if entries or not error:
                files = _filter_repo_entries(
                    entries, repo_root, self._project_root, "git"
                )
                if not files and not self._git_tracks_project(repo_root):
                    # 项目被 .gitignore 忽略/从未 add：git 永远报「无变化」，
                    # 会吞掉真实的新增与修改 → 回退本地快照。
                    return ChangeReport(
                        source="local",
                        repository_root=str(repo_root),
                        project_root=str(self._project_root),
                        error=UNTRACKED_PROJECT_NOTICE,
                    )
                return ChangeReport(
                    source="git",
                    repository_root=str(repo_root),
                    project_root=str(self._project_root),
                    files=tuple(files),
                    error=error,
                )
            # git 存在但命令不可用/执行异常：记录错误，继续尝试 SVN。
            svn_report = self._detect_svn()
            if svn_report.source == "svn":
                return svn_report
            return ChangeReport(
                source="local",
                repository_root=str(repo_root),
                project_root=str(self._project_root),
                error=error,
            )
        # --- SVN ---
        return self._detect_svn()

    def _git_tracks_project(self, repo_root: Path) -> bool:
        """项目目录下是否有被 git 跟踪的文件（带窗口级缓存，TTL 60s）。"""
        cached = self._tracked_cache
        if cached is not None and time.monotonic() - cached[0] <= 60.0:
            return cached[1]
        tracked = self._git.tracks_path(
            repo_root, _project_path_spec(repo_root, self._project_root)
        )
        self._tracked_cache = (time.monotonic(), tracked)
        return tracked

    def _detect_svn(self) -> ChangeReport:
        wc_root = find_svn_wc_root(self._project_root)
        if wc_root is None:
            return ChangeReport(
                source="local", project_root=str(self._project_root)
            )
        cached = self._cached(_SVN_CACHE, wc_root, self._cache_ttl)
        if cached is not None:
            entries, error = cached
        else:
            entries, error = self._svn.wc_changes(wc_root)
            _SVN_CACHE[str(wc_root)] = (time.monotonic(), tuple(entries), error)
        if entries or not error:
            files = _filter_repo_entries(
                entries, wc_root, self._project_root, "svn", svn_mode=True
            )
            return ChangeReport(
                source="svn",
                repository_root=str(wc_root),
                project_root=str(self._project_root),
                files=tuple(files),
                error=error,
            )
        return ChangeReport(
            source="local",
            repository_root=str(wc_root),
            project_root=str(self._project_root),
            error=error,
        )

    def invalidate_cache(self) -> None:
        """项目内写操作后调用：使本窗口所属仓库的缓存失效，保证刷新及时。"""
        repo_root = find_git_repo_root(self._project_root)
        if repo_root is not None:
            _GIT_CACHE.pop(str(repo_root), None)
        wc_root = find_svn_wc_root(self._project_root)
        if wc_root is not None:
            _SVN_CACHE.pop(str(wc_root), None)

    # --- 映射到内容状态 ---

    def status_map(
        self, report: ChangeReport, all_files: Optional[Sequence[str]] = None
    ) -> Dict[str, str]:
        """把仓库级变更映射为相对 content_root 的状态字典。

        返回值兼容原有 ``ContentSnapshot.diff`` 语义：
        ``{rel_path: added | modified | deleted}``，rename 收敛为 modified。
        project.yml 以 ``project.yml`` 键出现（供改动面板展示）。
        资源（图片/表格，无论在 content_root 内还是项目级 assets/）变化在提供
        ``all_files``（内容索引路径）时反查引用它的章节；未提供时项目级资源
        变化不进入内容状态。

        反查出的章节一律标 ``modified``：章节文件本身没有变化，只是它渲染出
        的内容变了。绝不能继承资源的 added/deleted——那会让一个真实存在、
        未被改动的章节在改动面板里显示成「新增」，而「撤销新增」会把它删掉。
        章节自身的真实状态永远优先于反查结果。
        """
        status: Dict[str, str] = {}
        project_root = Path(self._project_root)
        asset_rels: List[str] = []  # 待反查引用章节的资源路径
        for item in report.files:
            if not item.abs_path:
                continue
            abs_path = Path(item.abs_path)
            change_type = item.change_type
            if change_type == "renamed":
                change_type = "modified"
            try:
                rel = abs_path.resolve().relative_to(self._content_root).as_posix()
            except ValueError:
                # 在 content_root 之外：project.yml / assets 等。
                try:
                    proj_rel = abs_path.resolve().relative_to(project_root).as_posix()
                except ValueError:
                    continue
                if proj_rel == "project.yml":
                    status["project.yml"] = "modified"
                else:
                    asset_rels.append(proj_rel)
                continue
            status[rel] = change_type
            if not rel.endswith((".md", ".markdown")):
                # content_root 内的资源（如 general/images/x.png）同样反查章节。
                asset_rels.append(rel)
        if all_files is not None:
            for asset_rel in asset_rels:
                for referencing in _find_referencing_files(
                    self._content_root, asset_rel, all_files
                ):
                    status.setdefault(referencing, "modified")
        return status

    def chapters(
        self,
        report: ChangeReport,
        all_files: Sequence[str],
    ) -> List[ChangedChapter]:
        """把仓库级变更映射为章节级变更（含资源反查引用章节）。

        ``all_files``：当前索引的 rel_path 列表（相对 content_root），
        用于把资源变更反查到引用它的 Markdown 章节。反查出的章节
        ``change_type`` 恒为 modified 且 ``is_asset=True``（章节本身未变）；
        章节自身已有变更条目时不再追加反查条目，避免同一章节重复出现。
        """
        chapters: List[ChangedChapter] = []
        project_root = Path(self._project_root)
        own_paths: set = set()  # 章节自身有变更的路径
        pending_assets: List[Tuple[str, ChangedFile]] = []
        for item in report.files:
            if not item.abs_path:
                continue
            abs_path = Path(item.abs_path)
            try:
                rel = abs_path.resolve().relative_to(self._content_root).as_posix()
            except ValueError:
                try:
                    proj_rel = abs_path.resolve().relative_to(project_root).as_posix()
                except ValueError:
                    continue
                if proj_rel == "project.yml":
                    chapters.append(
                        ChangedChapter(
                            chapter_id="",
                            title="项目配置",
                            path="project.yml",
                            change_type="modified",
                            source=item.source,
                        )
                    )
                    continue
                # 项目级资源（assets/…）：稍后反查引用它的章节。
                pending_assets.append((proj_rel, item))
                continue
            if rel.endswith((".md", ".markdown")):
                chapters.append(self._chapter_from_path(rel, item))
                own_paths.add(rel)
            else:
                # content_root 内的资源：稍后反查引用它的章节。
                pending_assets.append((rel, item))
        seen_assets: set = set()
        for asset_rel, item in pending_assets:
            for referencing in _find_referencing_files(
                self._content_root, asset_rel, all_files
            ):
                if referencing in own_paths or referencing in seen_assets:
                    continue
                seen_assets.add(referencing)
                chapters.append(
                    self._chapter_from_path(referencing, item, is_asset=True)
                )
        return chapters

    def _chapter_from_path(
        self, rel: str, item: ChangedFile, is_asset: bool = False
    ) -> ChangedChapter:
        stem = Path(rel).stem
        match = re.match(r"^(\d+(?:\.\d+)*)", stem)
        chapter_id = match.group(1) if match else ""
        title = strip_number_prefix(stem) if match else stem
        # 资源反查出的章节：章节文件本身没变，只能是 modified，且没有旧路径。
        change_type = "modified" if is_asset else item.change_type
        return ChangedChapter(
            chapter_id=chapter_id,
            title=title,
            path=rel,
            change_type=change_type,
            source=item.source,
            old_path=None if is_asset else item.old_path,
            is_asset=is_asset,
        )


def _find_referencing_files(
    content_root: Path, asset_rel: str, all_files: Sequence[str]
) -> List[str]:
    """找到引用某资源（图片/表格）的 Markdown 文件列表（相对 content_root）。

    按资源文件名在 ``](...)`` / ``![](...)`` 链接文本中出现的章节文件匹配；
    全量扫描仅在资源变化时发生，且只扫描包含文件名文本的文件，开销可控。
    """
    name = Path(asset_rel).name
    if not name:
        return []
    hits: List[str] = []
    for rel in all_files:
        if not rel.endswith((".md", ".markdown")):
            continue
        try:
            text = (content_root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # 只按链接目标文件名的精确 basename 匹配：子串匹配会把含该名字的
        # 其它文件（如 a.png 命中 ba.png 的引用）误报为引用章节。
        if any(
            Path(target.split("#", 1)[0].strip()).name == name
            for target in re.findall(r"!?\[[^\]]*\]\(([^)\s]+)", text)
        ):
            hits.append(rel)
    return hits


# ---------------------------------------------------------------------------
# 版本控制回滚（VCS 模式下改动面板「回滚全部」的恢复路径）
# ---------------------------------------------------------------------------


def _restore_tracked_paths(
    command: Sequence[str],
    repo_root: Path,
    tracked_paths: Sequence[str],
    timeout: float,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> Optional[str]:
    """对被跟踪路径执行恢复命令（git restore / svn revert），失败返回错误文本。"""
    if not tracked_paths:
        return None
    try:
        proc = _run(
            list(command) + ["--"] + list(tracked_paths),
            cwd=repo_root,
            timeout=timeout,
            runner=runner,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)[:200]
    if proc.returncode != 0:
        return _decode(proc.stderr)[:200]
    return None


def _delete_untracked_files(
    untracked_paths: Sequence[str],
) -> List[str]:
    """删除未跟踪（新增）文件，返回失败路径列表。"""
    failures: List[str] = []
    for abs_path in untracked_paths:
        if not abs_path:
            continue
        try:
            target = Path(abs_path)
            if target.is_file() or target.is_symlink():
                target.unlink()
        except OSError:
            failures.append(abs_path)
    return failures


def _git_rollback_all(
    report: ChangeReport,
    *,
    timeout: float = 60.0,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    delete_untracked: bool = True,
) -> List[str]:
    """git：恢复被跟踪文件到 HEAD；可选删除未跟踪新增文件。

    staged 新增/重命名的新路径在 HEAD 中不存在：``git restore --staged``
    对它们报 ``does not exist in 'HEAD'`` 并使整条命令失败，其余文件也
    无法恢复。这些路径改用 ``git rm --cached`` 仅撤出暂存区（工作树文件
    转为未跟踪），重命名的旧路径仍走 ``git restore`` 恢复。
    """
    failures: List[str] = []
    repo_root = Path(report.repository_root or "")
    added_or_renamed_new: List[str] = []
    restore_paths: List[str] = []
    untracked: List[str] = []
    for item in report.files:
        if item.untracked:
            untracked.append(item.abs_path)
            continue
        if item.change_type in ("added", "renamed"):
            if item.path not in added_or_renamed_new:
                added_or_renamed_new.append(item.path)
            if item.change_type == "renamed":
                if item.old_path and item.old_path not in restore_paths:
                    restore_paths.append(item.old_path)
            continue
        if item.path not in restore_paths:
            restore_paths.append(item.path)
        if item.old_path and item.old_path not in restore_paths:
            restore_paths.append(item.old_path)
    if added_or_renamed_new:
        error = _restore_tracked_paths(
            [shutil.which("git") or "git", "rm", "--cached"],
            repo_root,
            added_or_renamed_new,
            timeout,
            runner=runner,
        )
        if error:
            failures.append("git rm --cached 失败：{0}".format(error))
        elif delete_untracked:
            # 撤出暂存后这些文件转为未跟踪：随未跟踪文件一并删除。
            for item in report.files:
                if item.change_type in ("added", "renamed") and item.abs_path:
                    untracked.append(item.abs_path)
    if restore_paths:
        error = _restore_tracked_paths(
            [shutil.which("git") or "git", "restore", "--staged", "--worktree"],
            repo_root,
            restore_paths,
            timeout,
            runner=runner,
        )
        if error:
            failures.append("git restore 失败：{0}".format(error))
    if delete_untracked:
        failures.extend(_delete_untracked_files(untracked))
    return failures


def _svn_rollback_all(
    report: ChangeReport,
    *,
    timeout: float = 60.0,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    delete_untracked: bool = True,
) -> List[str]:
    """svn：revert 被跟踪文件；可选删除未版本化新增文件。

    ``svn revert`` 对 added（svn add 过）条目只撤出版本控制，文件以未版本化
    状态留在工作副本——它在 BASE 中本不存在，delete_untracked 时应一并删除，
    否则「回滚全部」后 added 文件静默残留（与 git 侧 staged 新增同源缺陷）。
    """
    failures: List[str] = []
    wc_root = Path(report.repository_root or "")
    tracked = [item.path for item in report.files if not item.untracked]
    untracked = [item.abs_path for item in report.files if item.untracked]
    error = _restore_tracked_paths(
        [shutil.which("svn") or "svn", "revert"],
        wc_root,
        tracked,
        timeout,
        runner=runner,
    )
    if error:
        failures.append("svn revert 失败：{0}".format(error))
    elif delete_untracked:
        # revert 成功后 added 条目转为未版本化：追加到删除列表。
        for item in report.files:
            if item.change_type == "added" and not item.untracked and item.abs_path:
                untracked.append(item.abs_path)
    if delete_untracked:
        failures.extend(_delete_untracked_files(untracked))
    return failures


def rollback_all(
    report: ChangeReport,
    *,
    timeout: float = 60.0,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    delete_untracked: bool = True,
) -> List[str]:
    """VCS 模式下回滚当前项目的全部未提交改动（改动面板「回滚全部」）。

    - git：``git restore --staged --worktree`` 恢复被跟踪文件到 HEAD（含
      staged/unstaged/rename），并删除未跟踪（新增）文件。
    - svn：``svn revert`` 恢复被跟踪文件，并删除未版本化文件。
    - local：无法回滚，返回说明。

    注意：本函数只处理报告内的文件（已按 project_root 过滤），不会触及
    同一仓库中其它文档项目的变更。返回失败路径/说明列表（空 = 全部成功）。
    """
    if report.source == "git":
        return _git_rollback_all(
            report, timeout=timeout, runner=runner, delete_untracked=delete_untracked
        )
    if report.source == "svn":
        return _svn_rollback_all(
            report, timeout=timeout, runner=runner, delete_untracked=delete_untracked
        )
    return ["当前项目不在版本控制内，无法执行版本控制回滚"]


# ---------------------------------------------------------------------------
# 版本控制提交与拉取（改动面板「提交改动」/「拉取更新」）
# ---------------------------------------------------------------------------


def _run_vcs_command(
    command: Sequence[str],
    cwd: Path,
    timeout: float,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> Optional[str]:
    """执行单条版本控制命令；成功返回 None，失败返回错误文本。"""
    try:
        proc = _run(list(command), cwd=cwd, timeout=timeout, runner=runner)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)[:200]
    if proc.returncode != 0:
        return _decode(proc.stderr)[:300]
    return None


def _git_commit_all(
    report: ChangeReport,
    message: str,
    *,
    timeout: float = 60.0,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> List[str]:
    """git：暂存并提交项目内全部未提交改动（新增/修改/删除/重命名）。

    提交范围 = 报告内变更文件（``git add -A -- <paths>`` 后
    ``git commit -m <msg> -- <paths>``），不会把同一仓库中其它文档项目的
    改动、也不会把 .state 等应用内部目录一并提交——与检测/回滚的
    Project Context 隔离一致。
    """
    failures: List[str] = []
    root_text = (report.repository_root or "").strip()
    if not root_text:
        return ["Git 仓库根不可用"]
    repo_root = Path(root_text)
    if not repo_root.is_dir():
        return ["Git 仓库根不可用"]
    message = (message or "").strip()
    if not message:
        return ["提交信息不能为空"]
    # 提交范围 = 报告内变更文件（已按 project_root 过滤并排除 .state 等
    # 内部目录），含重命名旧路径；绝不用整项目目录做 pathspec，否则会把
    # .state/ 等应用状态一并提交。
    paths: List[str] = []
    for item in report.files:
        if item.path not in paths:
            paths.append(item.path)
        if item.old_path and item.old_path not in paths:
            paths.append(item.old_path)
    if not paths:
        return ["当前项目没有可提交的改动"]
    paths.sort()
    git = shutil.which("git") or "git"
    error = _run_vcs_command(
        [git, "add", "-A", "--"] + paths, repo_root, timeout, runner=runner
    )
    if error:
        failures.append("git add 失败：{0}".format(error))
        return failures
    error = _run_vcs_command(
        [git, "commit", "-m", message, "--"] + paths,
        repo_root,
        timeout,
        runner=runner,
    )
    if error:
        failures.append("git commit 失败：{0}".format(error))
    return failures


def _svn_commit_all(
    report: ChangeReport,
    message: str,
    *,
    timeout: float = 60.0,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> List[str]:
    """svn：登记新增/删除后提交项目内全部未提交改动。

    SVN 不会自动登记未版本化新增与磁盘删除：新增文件先 ``svn add``、
    已删除文件先 ``svn rm``，再 ``svn commit`` 限定项目路径提交。
    """
    failures: List[str] = []
    root_text = (report.repository_root or "").strip()
    if not root_text:
        return ["SVN 工作副本根不可用"]
    wc_root = Path(root_text)
    if not wc_root.is_dir():
        return ["SVN 工作副本根不可用"]
    message = (message or "").strip()
    if not message:
        return ["提交信息不能为空"]
    svn = shutil.which("svn") or "svn"
    for item in report.files:
        if item.untracked:
            error = _run_vcs_command(
                [svn, "add", "--parents", "--force", item.path],
                wc_root,
                timeout,
                runner=runner,
            )
            if error:
                failures.append("svn add 失败（{0}）：{1}".format(item.path, error))
        elif item.change_type == "deleted":
            error = _run_vcs_command(
                [svn, "rm", "--force", item.path],
                wc_root,
                timeout,
                runner=runner,
            )
            if error:
                failures.append("svn rm 失败（{0}）：{1}".format(item.path, error))
    if failures:
        return failures
    # 提交目标 = 报告内变更文件（已排除 .state 等内部目录），避免把
    # 应用状态一并提交；无文件时报错返回。
    paths = sorted(item.path for item in report.files)
    if not paths:
        return ["当前项目没有可提交的改动"]
    error = _run_vcs_command(
        [svn, "commit", "-m", message, "--"] + paths,
        wc_root,
        timeout,
        runner=runner,
    )
    if error:
        failures.append("svn commit 失败：{0}".format(error))
    return failures


def commit_all(
    report: ChangeReport,
    message: str,
    *,
    timeout: float = 60.0,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> List[str]:
    """VCS 模式下提交当前项目的全部未提交改动（改动面板「提交改动」）。

    - git：``git add -A``（限定项目路径）后 ``git commit``（限定项目路径）。
    - svn：未版本化新增 ``svn add``、删除 ``svn rm``，再 ``svn commit``。
    - local：无法提交，返回说明。

    只处理报告内的文件（已按 project_root 过滤），不波及同一仓库中其它
    文档项目。返回失败说明列表（空 = 全部成功）。
    """
    if report.source == "git":
        return _git_commit_all(report, message, timeout=timeout, runner=runner)
    if report.source == "svn":
        return _svn_commit_all(report, message, timeout=timeout, runner=runner)
    return ["当前项目不在版本控制内，无法提交"]


@dataclass(frozen=True)
class PullResult:
    """一次拉取的结果（改动面板「拉取更新」的反馈）。

    - ``ok``：命令是否成功。git 合并冲突时 pull 返回非零，视为失败；
      svn update 冲突不改变退出码，ok 仍为 True 但 ``conflicts`` 非空。
    - ``summary``：人类可读摘要（更新了 N 个文件 / 已是最新版本）。
    - ``changed_files``：拉取带入的文件（相对仓库根）。
    - ``conflicts``：合并/更新冲突文件（需用户手工解决）。
    - ``error``：失败原因（含命令输出文本）。
    """

    ok: bool
    summary: str
    changed_files: Tuple[str, ...] = ()
    conflicts: Tuple[str, ...] = ()
    error: Optional[str] = None


def _git_unmerged_paths(
    repo_root: Path,
    git: str,
    timeout: float,
    runner: Optional[Callable[..., subprocess.CompletedProcess]],
) -> Tuple[str, ...]:
    """冲突后列出未合并路径（``git ls-files -u`` 各 stage 去重）。"""
    try:
        proc = _run(
            [git, "ls-files", "-u"], cwd=repo_root, timeout=timeout, runner=runner
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if proc.returncode != 0:
        return ()
    paths = sorted(
        {
            line.split("\t", 1)[1]
            for line in _decode(proc.stdout).splitlines()
            if "\t" in line
        }
    )
    return tuple(paths)


def _git_pull_changes(
    report: ChangeReport,
    *,
    timeout: float,
    runner: Optional[Callable[..., subprocess.CompletedProcess]],
) -> PullResult:
    """git：执行 git pull，对比拉取前后 HEAD 统计带入文件；冲突时列未合并路径。"""
    repo_root = Path((report.repository_root or "").strip())
    git = shutil.which("git") or "git"

    def run_capture(args: Sequence[str]):
        try:
            return _run([git] + list(args), cwd=repo_root, timeout=timeout, runner=runner)
        except (OSError, subprocess.SubprocessError):
            return None

    pre: Optional[str] = None
    proc = run_capture(["rev-parse", "HEAD"])
    if proc is not None and proc.returncode == 0:
        pre = _decode(proc.stdout).strip() or None

    proc = run_capture(["pull"])
    if proc is None:
        return PullResult(ok=False, summary="", error="git pull 执行失败")
    output = (_decode(proc.stdout) + _decode(proc.stderr)).strip()
    if proc.returncode != 0:
        conflicts = _git_unmerged_paths(repo_root, git, timeout, runner)
        error = (
            "git pull 失败：{0}".format(output)
            if output
            else "git pull 失败（退出码 {0}）".format(proc.returncode)
        )
        return PullResult(ok=False, summary="", conflicts=conflicts, error=error)

    post: Optional[str] = None
    proc2 = run_capture(["rev-parse", "HEAD"])
    if proc2 is not None and proc2.returncode == 0:
        post = _decode(proc2.stdout).strip() or None

    changed: List[str] = []
    if pre and post and pre != post:
        proc3 = run_capture(["diff", "--name-only", pre, post])
        if proc3 is not None and proc3.returncode == 0:
            changed = [
                line.strip()
                for line in _decode(proc3.stdout).splitlines()
                if line.strip()
            ]
    summary = "已是最新版本" if not changed else "更新了 {0} 个文件".format(len(changed))
    return PullResult(ok=True, summary=summary, changed_files=tuple(changed))


def _svn_pull_changes(
    report: ChangeReport,
    *,
    timeout: float,
    runner: Optional[Callable[..., subprocess.CompletedProcess]],
) -> PullResult:
    """svn：执行 svn update 并解析输出（U/A/D/G/E 为变更，C 为冲突）。"""
    wc_root = Path((report.repository_root or "").strip())
    svn = shutil.which("svn") or "svn"
    try:
        proc = _run([svn, "update"], cwd=wc_root, timeout=timeout, runner=runner)
    except (OSError, subprocess.SubprocessError):
        return PullResult(ok=False, summary="", error="svn update 执行失败")
    output = (_decode(proc.stdout) + _decode(proc.stderr)).strip()
    if proc.returncode != 0:
        error = (
            "svn update 失败：{0}".format(output)
            if output
            else "svn update 失败（退出码 {0}）".format(proc.returncode)
        )
        return PullResult(ok=False, summary="", error=error)

    changed: List[str] = []
    conflicts: List[str] = []
    in_summary = False
    revision: Optional[str] = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("Summary of conflicts"):
            in_summary = True
            continue
        if line.startswith("C "):
            conflicts.append(line[2:].strip())
        elif not in_summary and line.startswith(("U ", "A ", "D ", "G ", "E ")):
            changed.append(line[2:].strip())
        if line.startswith("Updated to revision") or line.startswith("At revision"):
            revision = line.rsplit(" ", 1)[-1].strip(".")
    if changed or conflicts:
        parts = []
        if changed:
            parts.append("{0} 个文件更新".format(len(changed)))
        if conflicts:
            parts.append("{0} 个冲突".format(len(conflicts)))
        summary = "，".join(parts)
        if revision:
            summary = "{0}（r{1}）".format(summary, revision)
    else:
        summary = "已是最新版本"
        if revision:
            summary = "{0}（r{1}）".format(summary, revision)
    return PullResult(
        ok=True,
        summary=summary,
        changed_files=tuple(changed),
        conflicts=tuple(conflicts),
    )


def pull_changes(
    report: ChangeReport,
    *,
    timeout: float = 120.0,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> PullResult:
    """VCS 模式下拉取远端最新变更（改动面板「拉取更新」）。

    - git：``git pull``（仓库级操作），对比拉取前后 HEAD 统计带入文件；
      合并冲突时返回 ``ok=False`` 并附未合并路径清单。
    - svn：``svn update``（工作副本级操作），解析输出统计 U/A/D/G/E 变更
      与 C 冲突文件。
    - local：无法拉取，返回 ``ok=False``。

    返回 ``PullResult``，面板据此展示成功摘要、变更数量与冲突文件。
    """
    if report.source == "git":
        verb = "git pull"
    elif report.source == "svn":
        verb = "svn update"
    else:
        return PullResult(ok=False, summary="", error="当前项目不在版本控制内，无法拉取")
    root_text = (report.repository_root or "").strip()
    if not root_text:
        return PullResult(ok=False, summary="", error="{0}：仓库根不可用".format(verb))
    root = Path(root_text)
    if not root.is_dir():
        return PullResult(ok=False, summary="", error="{0}：仓库根不可用".format(verb))
    if report.source == "git":
        return _git_pull_changes(report, timeout=timeout, runner=runner)
    return _svn_pull_changes(report, timeout=timeout, runner=runner)
