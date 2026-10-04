# -*- coding: utf-8 -*-
"""Word 相关操作的有界执行契约（V4.0 40-B）。

现有实现（``adapters/word_convert.py``、``application/word_check.py``）已经在
后台线程里跑 COM、超时后按 PID 结束本次专用 Word 进程树。本模块把这些散落的
事实收敛成一份**可核对、可展示、可测试**的运行契约，不做第二套 Word 业务：

- **阶段与预算**：等待忙锁、启动（含取得 PID 之前）、打开、处理、写成果、退出
  各有独立秒级预算；超预算只返回对应阶段事实，不静默无限续期。
- **停止预算**：超时后的清理单独计时。任务在“总预算 + 停止预算”内返回，就绪
  的调用方能在返回前收到超时与清理事实。
- **归属证据**：只把启动前后 PID 差集或 ``ActiveWindow`` 归属证明过的 ``WINWORD``
  视为自有；无法证明归属时只登记残留事实，不按进程名清理用户 Word。
- **诊断摘要**：阶段耗时、原因、是否已清理、是否有未知残留，默认不含业务正文。

与既有代码的关系：``word_convert._run_session`` 在关键动作后调用
:meth:`WordOperationReport.stage`，``convert_document`` 在超时分支用
:class:`WordOwnership` 证明归属后清理并登记阶段事实。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

# --- 阶段名称（用户可见的“现在在做什么”） ---
STAGE_BUSY_LOCK = "busy-lock"
STAGE_START = "start"
STAGE_OPEN = "open"
STAGE_PROCESS = "process"
STAGE_SAVE = "save"
STAGE_QUIT = "quit"
STAGE_CLEANUP = "cleanup"

def environment_facts() -> Dict[str, str]:
    """运行环境事实（可复制诊断用；不含正文与凭据）。

    取不到的项目按“未知”输出，不用占位符冒充真实值。
    """
    import platform
    import sys

    try:
        from doc_tool.domain.version import APP_VERSION

        app_version = str(APP_VERSION)
    except Exception:  # noqa: BLE001 - 版本模块不可用时保持未知
        app_version = "未知"
    return {
        "应用版本": app_version,
        "Python": sys.version.split()[0] if sys.version else "未知",
        "平台": platform.platform() or "未知",
        "架构": platform.machine() or "未知",
    }


# --- 跨进程阶段标记（V4.0 40-B） ---
#
# 刷新走独立 worker 进程时，阶段事实只能经管道回传；这里用一行稳定标记表达，
# 由 :func:`parse_stage_markers` 解析。标记只含阶段名与说明，不含业务正文。
STAGE_MARKER_PREFIX = "[DOC-TOOL-STAGE] "
#: 等待忙锁与启动共用“启动”预算，保持与 word_convert 同一阶段口径。
STAGE_ENTER = STAGE_BUSY_LOCK


def stage_marker(stage: str, detail: str = "") -> str:
    """生成一行阶段标记（写入 stderr，与 [REASON] 同一约定）。"""
    import json

    return STAGE_MARKER_PREFIX + json.dumps(
        {"stage": stage, "detail": detail}, ensure_ascii=False
    )


def parse_stage_markers(text: str) -> List[tuple]:
    """从 worker 输出里解析阶段标记，返回 ``[(stage, detail), ...]``。"""
    import json

    found: List[tuple] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith(STAGE_MARKER_PREFIX):
            continue
        try:
            payload = json.loads(line[len(STAGE_MARKER_PREFIX):])
        except Exception:  # noqa: BLE001 - 坏标记直接跳过，不猜阶段
            continue
        if isinstance(payload, dict) and payload.get("stage"):
            found.append((str(payload["stage"]), str(payload.get("detail") or "")))
    return found


def busy_lock_path(path) -> str:
    """Word 的 ``~$`` 属主锁文件路径（用于判断文档是否已被占用）。"""
    candidate = Path(path)
    return str(candidate.with_name("~$" + candidate.name))


def is_file_busy(path) -> bool:
    """目标文档是否已有 Word 属主锁（只读探测，不清理任何进程）。"""
    try:
        return Path(busy_lock_path(path)).exists()
    except Exception:  # noqa: BLE001 - 探测失败按未知（不阻塞其他动作）
        return False

STAGE_LABELS: Dict[str, str] = {
    STAGE_BUSY_LOCK: "等待 Word 忙锁",
    STAGE_START: "启动 Word",
    STAGE_OPEN: "打开文档",
    STAGE_PROCESS: "处理/刷新",
    STAGE_SAVE: "写入成果",
    STAGE_QUIT: "退出 Word",
    STAGE_CLEANUP: "清理本次专用进程",
}
STAGE_ORDER = (
    STAGE_BUSY_LOCK, STAGE_START, STAGE_OPEN, STAGE_PROCESS,
    STAGE_SAVE, STAGE_QUIT, STAGE_CLEANUP,
)

# --- 阶段终态 ---
STAGE_DONE = "done"
STAGE_TIMEOUT = "timeout"
STAGE_FAILED = "failed"
STAGE_PENDING = "pending"

# --- 归属证据 ---
OWNERSHIP_PID_DIFF = "pid-diff"
OWNERSHIP_ACTIVE_WINDOW = "active-window"
OWNERSHIP_HWND = "hwnd"
OWNERSHIP_UNKNOWN = "unknown"


@dataclass(frozen=True)
class WordBudgets:
    """一次 Word 任务的阶段预算（秒）。

    默认值来自既有真机实测：``word_convert`` 里 DOCX→PDF 约 6 秒、PDF→Word
    预热后 7.5 秒、Word 首次冷启动重排引擎约 84 秒，因此启动/处理预算按最坏
    情况留量；这些是可显式覆盖的阶段预算，不是对全部机器的秒数承诺。
    """

    start: float = 120.0
    open: float = 120.0
    process: float = 300.0
    save: float = 120.0
    quit: float = 60.0
    cleanup: float = 15.0

    def for_stage(self, stage: str) -> float:
        return float(getattr(self, _STAGE_ATTR.get(stage, "process")))

    def to_dict(self) -> Dict[str, float]:
        return {
            "start": self.start, "open": self.open, "process": self.process,
            "save": self.save, "quit": self.quit, "cleanup": self.cleanup,
        }


_STAGE_ATTR = {
    STAGE_BUSY_LOCK: "start",
    STAGE_START: "start",
    STAGE_OPEN: "open",
    STAGE_PROCESS: "process",
    STAGE_SAVE: "save",
    STAGE_QUIT: "quit",
    STAGE_CLEANUP: "cleanup",
}


def total_budget_seconds(budgets: WordBudgets) -> float:
    """一次任务的总预算 ≈ 各阶段之和（不含单独的清理预算）。"""
    return float(
        budgets.start + budgets.open + budgets.process + budgets.save + budgets.quit
    )


def budgets_for_timeout(timeout_seconds: float) -> WordBudgets:
    """把既有单值超时按既有默认比例展开成阶段预算。

    保持历史调用方语义：``total_budget_seconds`` 与传入值一致，不偷偷增加
    等待时间；清理预算单独保留。
    """
    base = WordBudgets()
    base_total = total_budget_seconds(base)
    ratio = (max(1.0, float(timeout_seconds)) / base_total) if base_total else 1.0
    return WordBudgets(
        start=base.start * ratio, open=base.open * ratio, process=base.process * ratio,
        save=base.save * ratio, quit=base.quit * ratio,
        cleanup=base.cleanup,
    )


@dataclass
class StageFact:
    """一个阶段的真实事实（名称/预算/耗时/终态/说明）。"""

    name: str
    budgetSeconds: float = 0.0
    elapsedSeconds: float = 0.0
    outcome: str = STAGE_DONE
    detail: str = ""

    @property
    def label(self) -> str:
        return STAGE_LABELS.get(self.name, self.name)

    @property
    def overBudget(self) -> bool:
        return bool(self.budgetSeconds) and self.elapsedSeconds > self.budgetSeconds

    def summary_line(self) -> str:
        suffix = (
            "（超预算 {0:.1f}s）".format(self.elapsedSeconds - self.budgetSeconds)
            if self.overBudget else ""
        )
        detail = "：{0}".format(self.detail) if self.detail else ""
        return "{0} {1:.1f}s{2}{3}".format(self.label, self.elapsedSeconds, suffix, detail)

    def to_dict(self) -> Dict[str, object]:
        return {
            "stage": self.name, "label": self.label,
            "budgetSeconds": round(self.budgetSeconds, 2),
            "elapsedSeconds": round(self.elapsedSeconds, 2),
            "outcome": self.outcome, "detail": self.detail,
            "overBudget": self.overBudget,
        }


@dataclass
class WordOwnership:
    """本次专用 Word 实例的归属证据。"""

    pid: Optional[int] = None
    proof: str = OWNERSHIP_UNKNOWN
    pidsBefore: List[int] = field(default_factory=list)

    @property
    def provable(self) -> bool:
        """是否可证明属于本任务（可安全清理）。"""
        return self.pid is not None and self.proof in (
            OWNERSHIP_PID_DIFF, OWNERSHIP_ACTIVE_WINDOW, OWNERSHIP_HWND,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "pid": self.pid, "proof": self.proof,
            "provable": self.provable,
            "pidsBefore": list(self.pidsBefore),
        }


@dataclass
class WordOperationReport:
    """一次 Word 任务的阶段、预算、归属与清理事实。"""

    operation: str = ""
    source: str = ""
    target: str = ""
    budgets: WordBudgets = field(default_factory=WordBudgets)
    stages: List[StageFact] = field(default_factory=list)
    ownership: WordOwnership = field(default_factory=WordOwnership)
    timeoutStage: str = ""
    timeoutDetail: str = ""
    cleanup: str = ""
    residual: bool = False
    residualDetail: str = ""
    startedAt: float = field(default_factory=time.monotonic)

    # --- 阶段记录 ---

    def stage(self, name: str, detail: str = "", *, outcome: str = STAGE_DONE,
              elapsed: Optional[float] = None) -> StageFact:
        fact = StageFact(
            name=name,
            budgetSeconds=self.budgets.for_stage(name),
            # 未显式给出耗时的阶段（由工作线程置位）只记录预算，不伪造耗时。
            elapsedSeconds=float(elapsed) if elapsed is not None else 0.0,
            outcome=outcome,
            detail=detail,
        )
        self.stages.append(fact)
        return fact

    def timed(self, name: str, started: float, detail: str = "",
              *, outcome: str = STAGE_DONE) -> StageFact:
        return self.stage(name, detail, outcome=outcome, elapsed=time.monotonic() - started)

    def has(self, name: str) -> bool:
        return any(item.name == name for item in self.stages)

    def stage_fact(self, name: str) -> Optional[StageFact]:
        for item in self.stages:
            if item.name == name:
                return item
        return None

    def note_timeout(self, stage: str, detail: str = "") -> None:
        """记录超时阶段，并把它标成超时终态。"""
        self.timeoutStage = stage
        self.timeoutDetail = detail
        fact = self.stage_fact(stage)
        if fact is None:
            self.stage(stage, detail, outcome=STAGE_TIMEOUT,
                       elapsed=self.budgets.for_stage(stage))
            return
        fact.outcome = STAGE_TIMEOUT
        if detail and not fact.detail:
            fact.detail = detail
        if not fact.elapsedSeconds:
            fact.elapsedSeconds = fact.budgetSeconds

    # --- 归属与清理 ---

    def set_ownership(self, ownership: WordOwnership) -> None:
        self.ownership = ownership

    def note_cleanup(self, detail: str, *, ok: bool = True) -> None:
        self.cleanup = detail
        self.stage(STAGE_CLEANUP, detail,
                   outcome=STAGE_DONE if ok else STAGE_FAILED, elapsed=0.0)

    def note_residual(self, detail: str) -> None:
        """无法证明归属或清理未完成时的残留事实。"""
        self.residual = True
        self.residualDetail = detail

    @property
    def elapsedSeconds(self) -> float:
        return time.monotonic() - self.startedAt

    @property
    def failed(self) -> bool:
        """是否有阶段以失败终态结束（如阶段内异常、写成果失败）。"""
        return any(item.outcome == STAGE_FAILED for item in self.stages)

    @property
    def ok(self) -> bool:
        return not self.timeoutStage and not self.residual and not self.failed

    @property
    def currentStage(self) -> str:
        return self.stages[-1].name if self.stages else ""

    def stage_lines(self) -> List[str]:
        """用户可读的阶段经过（严格按真实记录，不补造阶段）。"""
        return [item.summary_line() for item in self.stages]

    def diagnostic_summary(self, *, environment: bool = True) -> str:
        """可复制的诊断摘要：运行环境 + 阶段/耗时/原因/归属/清理事实。

        ``environment=True`` 时先给运行环境（应用版本/Python/平台/架构），
        再给本次操作的阶段事实；默认不含业务正文与凭据。
        """
        lines: List[str] = []
        if environment:
            for key, value in environment_facts().items():
                lines.append("{0}：{1}".format(key, value))
            lines.append("")
        lines.append("操作：{0}".format(self.operation or "word"))
        if self.source:
            lines.append("来源：{0}".format(Path(self.source).name))
        if self.target:
            lines.append("成果：{0}".format(Path(self.target).name))
        lines.append("预算（秒）：{0}".format(
            ", ".join("{0}={1:g}".format(key, value) for key, value in self.budgets.to_dict().items())
        ))
        if self.stages:
            lines.append("阶段：")
            lines.extend("  - {0}".format(item) for item in self.stage_lines())
        else:
            lines.append("阶段：未知（未记录到任何阶段）")
        lines.append("归属：{0}".format(
            "已证明（{0}，PID {1}）".format(self.ownership.proof, self.ownership.pid)
            if self.ownership.provable else "无法证明，未清理任何 Word 进程"
        ))
        lines.append("清理：{0}".format(self.cleanup or "未执行"))
        if self.residual:
            lines.append("残留待处理：{0}".format(self.residualDetail or "未知"))
        lines.append("总耗时：{0:.1f}s".format(self.elapsedSeconds))
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, object]:
        return {
            "operation": self.operation,
            "source": self.source,
            "target": self.target,
            "budgets": self.budgets.to_dict(),
            "stages": [item.to_dict() for item in self.stages],
            "currentStage": self.currentStage,
            "timeoutStage": self.timeoutStage,
            "timeoutDetail": self.timeoutDetail,
            "ownership": self.ownership.to_dict(),
            "cleanup": self.cleanup,
            "residual": self.residual,
            "residualDetail": self.residualDetail,
            "elapsedSeconds": round(self.elapsedSeconds, 2),
            "ok": self.ok,
            "failed": self.failed,
        }


# --- 归属证据 ---


def ownership_from_pid_diff(pid: Optional[int],
                            pids_before: Optional[Iterable[int]]) -> WordOwnership:
    """启动前后 PID 差集给出的归属证据。"""
    before = sorted(int(item) for item in (pids_before or ()))
    if pid:
        return WordOwnership(pid=int(pid), proof=OWNERSHIP_PID_DIFF, pidsBefore=before)
    return WordOwnership(pid=None, proof=OWNERSHIP_UNKNOWN, pidsBefore=before)


def ownership_from_object(word, pid: Optional[int] = None) -> WordOwnership:
    """按 ``ActiveWindow``/``Hwnd`` 证明归属；拿不到就不猜。"""
    if pid:
        return WordOwnership(pid=int(pid), proof=OWNERSHIP_ACTIVE_WINDOW)
    if word is not None:
        try:
            if hasattr(word, "ActiveWindow") and word.ActiveWindow is not None:
                return WordOwnership(pid=None, proof=OWNERSHIP_ACTIVE_WINDOW)
        except Exception:  # noqa: BLE001 - COM 查询失败按未知处理
            pass
    return WordOwnership(pid=None, proof=OWNERSHIP_UNKNOWN)


def is_busy_lock_error(exc: BaseException) -> bool:
    """判断异常是否属于“文件被占用/忙锁”类（用于阶段归类，不改变结果）。"""
    text = str(exc)
    lower = text.lower()
    tokens = (
        "being used by another", "另一个程序", "正由另一", "locked for editing",
        "cannot access", "无法访问", "permission denied", "拒绝访问",
        "0x800a1526", "call was rejected by callee", "被调用方拒绝",
        "忙", "busy",
    )
    return any(token in lower or token in text for token in tokens)


@dataclass
class StopOutcome:
    """停止与清理的真实结果（与“取消请求已确认”分开表达）。"""

    requested: bool = False
    stopped: bool = False
    cleaned: bool = False
    residual: bool = False
    detail: str = ""
    stoppedSeconds: float = 0.0

    @property
    def fullyStopped(self) -> bool:
        return bool(self.stopped and not self.residual)

    def summary_line(self) -> str:
        if not self.requested:
            return "未请求停止"
        if self.fullyStopped:
            return "已停止并完成清理（{0:.1f}s）".format(self.stoppedSeconds)
        if self.cleaned:
            return "已清理本次专用进程，残留待处理：{0}".format(self.detail or "未知")
        return "已请求停止，尚未确认终止：{0}".format(self.detail or "未知")

    def to_dict(self) -> Dict[str, object]:
        return {
            "requested": self.requested, "stopped": self.stopped,
            "cleaned": self.cleaned, "residual": self.residual,
            "fullyStopped": self.fullyStopped, "detail": self.detail,
            "stoppedSeconds": round(self.stoppedSeconds, 2),
        }


def stop_and_cleanup(
    report: WordOperationReport,
    *,
    kill: Optional[Callable[[], None]] = None,
    is_alive: Optional[Callable[[], bool]] = None,
    wait: Optional[Callable[[float], None]] = None,
    budget_seconds: Optional[float] = None,
) -> StopOutcome:
    """按停止预算终止本次专用资源并记录真实终态。

    - 只有 :attr:`WordOwnership.provable` 为真时才调用 ``kill``；
    - ``is_alive`` 在停止预算内轮询；仍未结束则记残留，不假称已停止；
    - 无法证明归属时不清理任何进程，只记录残留事实。
    """
    sleep = wait or time.sleep
    budget = float(budget_seconds if budget_seconds is not None else report.budgets.cleanup)
    started = time.monotonic()
    outcome = StopOutcome(requested=True)

    if not report.ownership.provable:
        detail = "无法证明该 Word 实例属于本任务，只结束自有后台线程，不清理用户 Word"
        outcome.residual = True
        outcome.detail = detail
        report.note_residual(detail)
        outcome.stoppedSeconds = time.monotonic() - started
        return outcome

    if kill is not None:
        try:
            kill()
            outcome.cleaned = True
        except Exception as exc:  # noqa: BLE001 - 清理失败保留事实
            outcome.detail = "清理失败：{0}".format(exc)
            report.note_residual(outcome.detail)

    deadline = started + max(0.0, budget)
    if is_alive is not None:
        while time.monotonic() < deadline:
            try:
                if not is_alive():
                    outcome.stopped = True
                    break
            except Exception:  # noqa: BLE001 - 探测失败按未终止处理
                break
            sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    else:
        outcome.stopped = True

    outcome.stoppedSeconds = time.monotonic() - started
    if outcome.stopped:
        report.note_cleanup(
            "已在 {0:.1f}s 内终止本次专用进程（PID {1}）".format(
                outcome.stoppedSeconds, report.ownership.pid
            )
        )
    else:
        detail = "停止预算 {0:g}s 内未确认终止（PID {1}）".format(budget, report.ownership.pid)
        outcome.residual = True
        if not outcome.detail:
            outcome.detail = detail
        report.note_residual(detail)
    return outcome


def budget_lines() -> List[str]:
    """给设置页/说明用的受支持字段清单（只列真实生效的字段）。"""
    return [
        "start：启动 Word（含取得 PID 之前的等待）",
        "open：打开源文档",
        "process：处理/刷新/转换",
        "save：写出成果文件",
        "quit：退出 Word",
        "cleanup：超时后清理本次专用进程",
    ]


__all__ = [
    "STAGE_BUSY_LOCK", "STAGE_START", "STAGE_OPEN", "STAGE_PROCESS",
    "STAGE_SAVE", "STAGE_QUIT", "STAGE_CLEANUP", "STAGE_LABELS", "STAGE_ORDER",
    "STAGE_DONE", "STAGE_TIMEOUT", "STAGE_FAILED", "STAGE_PENDING",
    "environment_facts",
    "STAGE_MARKER_PREFIX", "STAGE_ENTER", "stage_marker", "parse_stage_markers",
    "busy_lock_path", "is_file_busy",
    "OWNERSHIP_PID_DIFF", "OWNERSHIP_ACTIVE_WINDOW", "OWNERSHIP_HWND", "OWNERSHIP_UNKNOWN",
    "WordBudgets", "StageFact", "WordOwnership", "WordOperationReport", "StopOutcome",
    "total_budget_seconds", "budgets_for_timeout", "ownership_from_pid_diff",
    "ownership_from_object", "is_busy_lock_error", "stop_and_cleanup", "budget_lines",
]