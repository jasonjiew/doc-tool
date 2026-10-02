# -*- coding: utf-8 -*-
"""V3.3 33-D 可选摘要/术语增强 provider（默认禁用，故障回本地）。

约束（design.md D4、specs 显式启用的两个增强用途/范围与输出约束/故障自动回本地）：

- 只在用户**显式启用**并点击增强动作时调用；保存/检查/出稿永不自动调用。
- 请求只带本次明确选中的上下文，默认上限 8000 字符，截断在结果中明示。
- 凭据只从用户级环境变量读取，绝不写入项目目录、交付包或日志。
- 响应必须通过结构/用途校验；只有本地 evidence ID 才能作为来源，其余只算
  措辞候选；含可执行指令的响应不执行、不入证据，仅记录说明。
- 超时/断网/无凭据/坏响应/取消/命令缺失都回退已有本地候选，单次调用即回退，
  不反复请求；provider 失败不影响编辑与交付。

``FakeWritingProvider`` 为测试替身（记录调用次数，可脚本化超时/坏结构/取消）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Sequence

from doc_tool.application.assist.models import (
    DEFAULT_MAX_REQUEST_CHARS, ENHANCE_BAD_RESPONSE, ENHANCE_CANCELLED,
    ENHANCE_COMMAND_MISSING, ENHANCE_DISABLED, ENHANCE_ERROR, ENHANCE_NETWORK,
    ENHANCE_NO_CREDENTIAL, ENHANCE_OK, ENHANCE_STATUS_LABELS, ENHANCE_TIMEOUT,
    ENHANCE_UNAVAILABLE, PROVIDER_DISABLED, PROVIDER_HTTP,
    PROVIDER_KINDS, PROVIDER_LOCAL_COMMAND, PURPOSE_REVISION_SUMMARY, PURPOSE_TERM,
    PURPOSES, AssistError, has_command_instruction, truncate_context, user_config_dir,
)

#: provider 用户级配置文件（放用户配置目录，绝不进入项目）。
PROVIDER_CONFIG_NAME = "provider.json"
#: 单条建议文本长度上限（超长响应按非法处理并跳过该条）。
MAX_SUGGESTION_CHARS = 4000


class ProviderError(AssistError):
    """provider 可预期失败（统一回退本地候选）。"""

    code = "E3310"


class ProviderTimeout(ProviderError):
    code = "E3311"


class ProviderNetworkError(ProviderError):
    code = "E3312"


class ProviderNoCredential(ProviderError):
    code = "E3313"


class ProviderCommandMissing(ProviderError):
    code = "E3314"


class ProviderBadResponse(ProviderError):
    code = "E3315"


class ProviderCancelled(ProviderError):
    code = "E3316"


@dataclass
class ProviderSuggestion:
    """provider 返回的一条建议（含来源可信度标记）。"""

    text: str
    source: str = "wording-candidate"   #: local-evidence | wording-candidate | blocked-instruction
    evidence_ids: List[str] = field(default_factory=list)
    instruction_like: bool = False

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "source": self.source,
            "evidenceIds": list(self.evidence_ids),
            "instructionLike": self.instruction_like,
        }


@dataclass
class ProviderResponse:
    """校验后的 provider 响应。"""

    purpose: str
    suggestions: List[ProviderSuggestion] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "suggestions": [item.to_dict() for item in self.suggestions],
            "skipped": list(self.skipped),
        }


def validate_provider_response(
    payload: Any,
    *,
    purpose: str,
    known_evidence_ids: Sequence[str] = (),
) -> ProviderResponse:
    """校验响应用途/结构/来源；非法结构抛 ``ProviderBadResponse``。

    - 只有出现在 ``known_evidence_ids``（本地记录）中的出处才可作为来源；
    - 含可执行指令特征的条目标记 ``instruction_like``，不执行、不入证据；
    - 超长/空/非字符串条目跳过并记录，不因个别坏条目丢弃整份响应。
    """
    if not isinstance(payload, Mapping):
        raise ProviderBadResponse("响应不是 JSON 对象。")
    response_purpose = str(payload.get("purpose") or "").strip()
    if response_purpose != purpose:
        raise ProviderBadResponse(
            "响应用途不符（期望 {0}，实际 {1}）。".format(purpose, response_purpose or "空")
        )
    raw_items = payload.get("suggestions")
    if raw_items is None:
        raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ProviderBadResponse("响应缺少 suggestions 列表。")
    known = {str(item) for item in (known_evidence_ids or ())}
    suggestions: List[ProviderSuggestion] = []
    skipped: List[str] = []
    for raw in raw_items:
        text = ""
        evidence_ids: List[str] = []
        if isinstance(raw, str):
            text = raw.strip()
        elif isinstance(raw, Mapping):
            text = str(raw.get("text") or raw.get("wording") or "").strip()
            raw_ids = raw.get("evidenceIds") or raw.get("evidence") or []
            if isinstance(raw_ids, (list, tuple)):
                evidence_ids = [str(item) for item in raw_ids if str(item).strip()]
        else:
            skipped.append("非法建议条目（类型 {0}）已跳过。".format(type(raw).__name__))
            continue
        if not text:
            skipped.append("空建议文本已跳过。")
            continue
        if len(text) > MAX_SUGGESTION_CHARS:
            skipped.append("超长建议（{0} 字符）已跳过。".format(len(text)))
            continue
        matched = [item for item in evidence_ids if item in known]
        dropped = [item for item in evidence_ids if item not in known]
        if dropped:
            skipped.append(
                "无本地出处的来源标记已忽略（{0}）。".format("、".join(dropped[:3]))
            )
        instruction_like = has_command_instruction(text)
        source = "local-evidence" if matched else "wording-candidate"
        if instruction_like:
            source = "blocked-instruction"
        suggestions.append(ProviderSuggestion(
            text=text,
            source=source,
            evidence_ids=matched,
            instruction_like=instruction_like,
        ))
    return ProviderResponse(purpose=purpose, suggestions=suggestions, skipped=skipped)


@dataclass
class ProviderConfig:
    """provider 用户级配置（不含凭据本身）。"""

    enabled: bool = False
    provider: str = PROVIDER_DISABLED
    command: str = ""
    args: List[str] = field(default_factory=list)
    endpoint: str = ""
    model: str = ""
    timeout_seconds: float = 8.0
    max_chars: int = DEFAULT_MAX_REQUEST_CHARS
    credential_env: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"

    def __post_init__(self) -> None:
        if self.provider not in PROVIDER_KINDS:
            self.provider = PROVIDER_DISABLED
        if self.provider == PROVIDER_DISABLED:
            self.enabled = False
        self.args = [str(item) for item in (self.args or ())]
        try:
            self.timeout_seconds = max(0.5, float(self.timeout_seconds or 8.0))
        except (TypeError, ValueError):
            self.timeout_seconds = 8.0
        try:
            self.max_chars = max(200, int(self.max_chars or DEFAULT_MAX_REQUEST_CHARS))
        except (TypeError, ValueError):
            self.max_chars = DEFAULT_MAX_REQUEST_CHARS

    @property
    def is_enabled(self) -> bool:
        return bool(self.enabled) and self.provider != PROVIDER_DISABLED

    def target_description(self) -> str:
        """展示目标（不含凭据值）。"""
        if not self.is_enabled:
            return "未启用（本地候选）"
        if self.provider == PROVIDER_LOCAL_COMMAND:
            command = self.command or "（未配置命令）"
            tail = " ".join(self.args)
            return "本地命令：{0}{1}".format(command, (" " + tail) if tail else "")
        if self.provider == PROVIDER_HTTP:
            return "HTTP：{0}{1}".format(
                self.endpoint or "（未配置端点）",
                "（模型 {0}）".format(self.model) if self.model else "",
            )
        return "未启用（本地候选）"

    def credential_present(self) -> bool:
        return bool(self.credential_env) and bool(os.environ.get(self.credential_env))

    def sanitized(self) -> dict:
        """可展示/可落盘的配置视图（只有环境变量名，没有凭据值）。"""
        data = {
            "enabled": bool(self.enabled),
            "provider": self.provider,
            "command": self.command,
            "args": list(self.args),
            "endpoint": self.endpoint,
            "model": self.model,
            "timeoutSeconds": self.timeout_seconds,
            "maxChars": self.max_chars,
            "credentialEnv": self.credential_env,
            "authHeader": self.auth_header,
            "authScheme": self.auth_scheme,
        }
        data["target"] = self.target_description()
        data["credentialPresent"] = self.credential_present()
        data["isEnabled"] = self.is_enabled
        return data

    def to_dict(self) -> dict:
        return self.sanitized()

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "ProviderConfig":
        data = data or {}
        config = cls(
            enabled=bool(data.get("enabled", False)),
            provider=str(data.get("provider") or PROVIDER_DISABLED),
            command=str(data.get("command") or ""),
            args=[str(item) for item in (data.get("args") or [])],
            endpoint=str(data.get("endpoint") or ""),
            model=str(data.get("model") or ""),
            timeout_seconds=data.get("timeoutSeconds", 8.0),
            max_chars=data.get("maxChars", DEFAULT_MAX_REQUEST_CHARS),
            credential_env=str(data.get("credentialEnv") or ""),
            auth_header=str(data.get("authHeader") or "Authorization"),
            auth_scheme=str(data.get("authScheme") or "Bearer"),
        )
        return config


class ProviderConfigStore:
    """用户级 provider 配置读写（默认 ``APPDATA%/doc-tool/assist/provider.json``）。"""

    def __init__(self, path=None) -> None:
        self._path = Path(path) if path else user_config_dir() / PROVIDER_CONFIG_NAME
        self.warnings: List[str] = []

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> ProviderConfig:
        self.warnings = []
        if not self._path.is_file():
            return ProviderConfig()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            self.warnings.append(
                "provider 配置不可解析（{0}），已按未启用处理；日常编辑不受影响。".format(exc)
            )
            return ProviderConfig()
        if not isinstance(data, Mapping):
            self.warnings.append("provider 配置结构不正确，已按未启用处理。")
            return ProviderConfig()
        return ProviderConfig.from_dict(data)

    def save(self, config: ProviderConfig, *, project_root=None) -> Path:
        """保存用户级配置；显式传入项目根时拒绝写进项目目录。"""
        target = Path(self._path)
        if project_root:
            try:
                target.resolve().relative_to(Path(project_root).resolve())
            except ValueError:
                pass
            else:
                raise ProviderError(
                    "provider 配置必须放在用户目录，不得写入项目或交付包。"
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = config.sanitized()
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.replace(str(tmp), str(target))
        except OSError:
            import shutil

            shutil.move(str(tmp), str(target))
        return target

    def describe(self) -> dict:
        config = self.load()
        return {
            "path": str(self._path),
            "warnings": list(self.warnings),
            "config": config.sanitized(),
        }


def resolve_credential(config: ProviderConfig) -> str:
    """从用户级环境变量读取凭据（只读，不缓存、不落盘）。"""
    if not config.credential_env:
        return ""
    return os.environ.get(config.credential_env, "") or ""

class WritingProvider:
    """可选增强 provider 协议：摘要与术语两个用途。"""

    def suggest_revision(self, context: Mapping[str, Any]) -> Any:  # pragma: no cover - 协议
        raise NotImplementedError

    def suggest_terms(self, context: Mapping[str, Any]) -> Any:  # pragma: no cover - 协议
        raise NotImplementedError


class LocalCommandProvider(WritingProvider):
    """本地模型命令 adapter：只调用用户预先配置的可执行文件与参数。

    模型文本永远不能改变命令或执行内容——argv 完全来自配置，请求只经 stdin
    传入 JSON，响应只经 stdout 读取。非零退出、超时、非 JSON 输出都映射为
    可回退的 provider 失败。
    """

    def __init__(self, config: ProviderConfig, *, runner: Optional[Callable] = None) -> None:
        self._config = config
        self._runner = runner or self._run_command

    @property
    def config(self) -> ProviderConfig:
        return self._config

    def suggest_revision(self, context: Mapping[str, Any]) -> Any:
        return self._invoke(PURPOSE_REVISION_SUMMARY, context)

    def suggest_terms(self, context: Mapping[str, Any]) -> Any:
        return self._invoke(PURPOSE_TERM, context)

    def _invoke(self, purpose: str, context: Mapping[str, Any]) -> Any:
        command = (self._config.command or "").strip()
        if not command:
            raise ProviderCommandMissing("未配置本地模型命令。")
        argv = [command] + [str(item) for item in (self._config.args or ())]
        payload = json.dumps(
            {"purpose": purpose, "context": dict(context or {})}, ensure_ascii=False
        )
        try:
            output = self._runner(argv, payload, float(self._config.timeout_seconds or 8.0))
        except FileNotFoundError as exc:
            raise ProviderCommandMissing(
                "本地模型命令不存在：{0}".format(command)
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderTimeout("本地模型命令超时（{0}s）。".format(self._config.timeout_seconds)) from exc
        except OSError as exc:
            raise ProviderError("本地模型命令无法执行：{0}".format(exc)) from exc
        try:
            return json.loads(output or "")
        except ValueError as exc:
            raise ProviderBadResponse("本地模型输出不是合法 JSON：{0}".format(exc)) from exc

    @staticmethod
    def _run_command(argv: Sequence[str], payload: str, timeout: float) -> str:
        completed = subprocess.run(
            list(argv),
            input=payload.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            shell=False,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace")[:200]
            raise ProviderError(
                "本地模型命令退出码 {0}：{1}".format(completed.returncode, stderr)
            )
        return (completed.stdout or b"").decode("utf-8", errors="replace")


class HttpProvider(WritingProvider):
    """用户配置的 HTTP adapter：端点/模型来自配置，凭据只来自用户环境变量。

    ``transport`` 可注入（测试用）：签名 ``(endpoint, payload, headers, timeout) -> str``，
    返回响应文本；抛 ``ProviderTimeout``/``ProviderNetworkError``/``OSError`` 分别
    对应超时/断网/其它故障。
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: Optional[Callable] = None,
        credential_resolver: Optional[Callable[[ProviderConfig], str]] = None,
    ) -> None:
        self._config = config
        self._transport = transport or self._urllib_transport
        self._credential_resolver = credential_resolver or resolve_credential

    @property
    def config(self) -> ProviderConfig:
        return self._config

    def suggest_revision(self, context: Mapping[str, Any]) -> Any:
        return self._invoke(PURPOSE_REVISION_SUMMARY, context)

    def suggest_terms(self, context: Mapping[str, Any]) -> Any:
        return self._invoke(PURPOSE_TERM, context)

    def _invoke(self, purpose: str, context: Mapping[str, Any]) -> Any:
        endpoint = (self._config.endpoint or "").strip()
        if not endpoint:
            raise ProviderError("未配置 HTTP 端点。")
        if not endpoint.lower().startswith(("http://", "https://")):
            raise ProviderError("HTTP 端点必须以 http:// 或 https:// 开头。")
        credential = self._credential_resolver(self._config) or ""
        if self._config.credential_env and not credential:
            raise ProviderNoCredential(
                "未在用户环境变量 {0} 找到凭据，未发起请求。".format(self._config.credential_env)
            )
        headers = {"Content-Type": "application/json"}
        if credential:
            value = "{0} {1}".format(self._config.auth_scheme or "Bearer", credential).strip()
            headers[self._config.auth_header or "Authorization"] = value
        payload = {
            "purpose": purpose,
            "model": self._config.model,
            "context": dict(context or {}),
        }
        try:
            body = self._transport(endpoint, payload, headers, float(self._config.timeout_seconds or 8.0))
        except (ProviderTimeout, ProviderNetworkError, ProviderError):
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeout("HTTP 请求超时（{0}s）。".format(self._config.timeout_seconds)) from exc
        except OSError as exc:
            raise ProviderNetworkError("HTTP 请求失败（断网/端点不可达）：{0}".format(exc)) from exc
        try:
            return json.loads(body or "")
        except ValueError as exc:
            raise ProviderBadResponse("HTTP 响应不是合法 JSON：{0}".format(exc)) from exc

    @staticmethod
    def _urllib_transport(
        endpoint: str, payload: Mapping[str, Any], headers: Mapping[str, str], timeout: float
    ) -> str:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(dict(payload), ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise ProviderError("HTTP 状态 {0}".format(exc.code), code="E3317") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeout("HTTP 请求超时（{0}s）。".format(timeout)) from exc
            raise ProviderNetworkError("HTTP 请求失败（断网/端点不可达）：{0}".format(reason)) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeout("HTTP 请求超时（{0}s）。".format(timeout)) from exc


class FakeWritingProvider(WritingProvider):
    """测试替身：可脚本化成功/超时/坏结构/取消，并记录每次调用。

    ``responses`` 形如 ``{purpose: dict | callable(context)}``；
    ``failure``/``failures`` 用于注入异常（如 ``ProviderTimeout``）。
    """

    def __init__(
        self,
        responses: Optional[Mapping[str, Any]] = None,
        *,
        failure: Optional[BaseException] = None,
        failures: Optional[Mapping[str, BaseException]] = None,
        calls: Optional[List[dict]] = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._failure = failure
        self._failures = dict(failures or {})
        self.calls: List[dict] = calls if calls is not None else []

    def suggest_revision(self, context: Mapping[str, Any]) -> Any:
        return self._respond(PURPOSE_REVISION_SUMMARY, context)

    def suggest_terms(self, context: Mapping[str, Any]) -> Any:
        return self._respond(PURPOSE_TERM, context)

    def _respond(self, purpose: str, context: Mapping[str, Any]) -> Any:
        self.calls.append({
            "purpose": purpose,
            "scope": str((context or {}).get("scope") or ""),
            "chars": len(str((context or {}).get("text") or "")),
            "truncated": bool((context or {}).get("truncated")),
            "evidenceIds": list((context or {}).get("evidenceIds") or ()),
        })
        failure = self._failures.get(purpose) or self._failure
        if failure is not None:
            raise failure
        scripted = self._responses.get(purpose)
        if scripted is None:
            return {"purpose": purpose, "suggestions": []}
        if callable(scripted):
            return scripted(context)
        return scripted


def build_provider(
    config: ProviderConfig,
    *,
    transport: Optional[Callable] = None,
    runner: Optional[Callable] = None,
    credential_resolver: Optional[Callable[[ProviderConfig], str]] = None,
) -> Optional[WritingProvider]:
    """按配置构造 provider；禁用或未知类型返回 None。"""
    if not config.is_enabled:
        return None
    if config.provider == PROVIDER_LOCAL_COMMAND:
        return LocalCommandProvider(config, runner=runner)
    if config.provider == PROVIDER_HTTP:
        return HttpProvider(
            config, transport=transport, credential_resolver=credential_resolver
        )
    return None


@dataclass
class ProviderRequestLogEntry:
    """一次增强请求的脱敏日志（只有目标/范围/长度/状态，无凭据）。"""

    purpose: str
    status: str
    target: str
    scope: str = ""
    requested_chars: int = 0
    actual_chars: int = 0
    truncated: bool = False
    attempts: int = 0
    at: str = ""

    def to_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "status": self.status,
            "target": self.target,
            "scope": self.scope,
            "requestedChars": self.requested_chars,
            "actualChars": self.actual_chars,
            "truncated": self.truncated,
            "attempts": self.attempts,
            "at": self.at,
        }


@dataclass
class EnhancementResult:
    """一次可选增强的结果（失败时始终带本地候选）。"""

    purpose: str
    status: str = ENHANCE_DISABLED
    target_description: str = ""
    scope_label: str = ""
    requested_chars: int = 0
    actual_chars: int = 0
    truncated: bool = False
    max_chars: int = DEFAULT_MAX_REQUEST_CHARS
    enhanced: List[ProviderSuggestion] = field(default_factory=list)
    local_candidates: List[str] = field(default_factory=list)
    used_local_candidates: bool = True
    blocked_instructions: List[str] = field(default_factory=list)
    attempts: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == ENHANCE_OK

    @property
    def status_label(self) -> str:
        return ENHANCE_STATUS_LABELS.get(self.status, self.status)

    def summary_lines(self) -> List[str]:
        lines = [
            "{0}｜目标：{1}｜范围：{2}".format(
                self.status_label, self.target_description, self.scope_label or "本次选中内容"
            ),
            "请求 {0} 字符{1}（上限 {2}）".format(
                self.actual_chars, "，已截断" if self.truncated else "", self.max_chars
            ),
        ]
        if self.used_local_candidates:
            lines.append("使用本地候选 {0} 条（正文与项目状态未改动）。".format(
                len(self.local_candidates)
            ))
        if self.enhanced:
            lines.append("增强建议 {0} 条（需逐条选择采纳）。".format(len(self.enhanced)))
        if self.blocked_instructions:
            lines.append("忽略 {0} 条含可执行指令的响应内容（从不执行）。".format(
                len(self.blocked_instructions)
            ))
        lines.extend(self.notes)
        return lines

    def to_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "status": self.status,
            "statusLabel": self.status_label,
            "target": self.target_description,
            "scope": self.scope_label,
            "requestedChars": self.requested_chars,
            "actualChars": self.actual_chars,
            "truncated": self.truncated,
            "maxChars": self.max_chars,
            "enhanced": [item.to_dict() for item in self.enhanced],
            "localCandidates": list(self.local_candidates),
            "usedLocalCandidates": self.used_local_candidates,
            "blockedInstructions": list(self.blocked_instructions),
            "attempts": self.attempts,
            "notes": list(self.notes),
            "summary": self.summary_lines(),
        }

class ProviderGateway:
    """增强入口：默认禁用、单次调用、失败即回退本地候选。"""

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        *,
        provider: Optional[WritingProvider] = None,
        provider_factory: Optional[Callable[..., Optional[WritingProvider]]] = None,
        log_limit: int = 50,
    ) -> None:
        self._config = config or ProviderConfig()
        self._provider = provider
        self._provider_factory = provider_factory or build_provider
        self._log: List[ProviderRequestLogEntry] = []
        self._log_limit = max(1, int(log_limit))
        self._call_count = 0

    @property
    def config(self) -> ProviderConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.is_enabled

    @property
    def provider_call_count(self) -> int:
        """实际发生的 provider 调用次数（用于断言日常流程不调用）。"""
        return self._call_count

    @property
    def request_log(self) -> List[ProviderRequestLogEntry]:
        return list(self._log)

    def request_log_dicts(self) -> List[dict]:
        return [entry.to_dict() for entry in self._log]

    def request_log_text(self) -> str:
        return json.dumps(self.request_log_dicts(), ensure_ascii=False)

    def set_config(self, config: ProviderConfig) -> None:
        self._config = config
        self._provider = None

    def set_provider(self, provider: Optional[WritingProvider]) -> None:
        self._provider = provider

    def enhance(
        self,
        purpose: str,
        *,
        context_text: str,
        local_candidates: Sequence[str] = (),
        evidence_ids: Sequence[str] = (),
        scope_label: str = "",
        cancel_token=None,
        max_chars: Optional[int] = None,
    ) -> EnhancementResult:
        """执行一次增强；任何失败都返回本地候选并集中说明。"""
        purpose = purpose if purpose in PURPOSES else PURPOSE_REVISION_SUMMARY
        limit = int(max_chars or self._config.max_chars or DEFAULT_MAX_REQUEST_CHARS)
        text, truncated, original_chars = truncate_context(context_text or "", limit)
        result = EnhancementResult(
            purpose=purpose,
            status=ENHANCE_DISABLED,
            target_description=self._config.target_description(),
            scope_label=scope_label,
            requested_chars=original_chars,
            actual_chars=len(text),
            truncated=truncated,
            max_chars=limit,
            local_candidates=[str(item) for item in (local_candidates or ()) if str(item).strip()],
            used_local_candidates=True,
            attempts=0,
        )
        if truncated:
            result.notes.append(
                "请求内容超过上限，已截断为前 {0} 字符（实际发送范围如上）。".format(limit)
            )
        if not self._config.is_enabled:
            result.notes.append(
                "provider 默认禁用：本次使用本地候选，未发起任何模型/网络请求。"
            )
            self._record(result)
            return result
        if self._is_cancelled(cancel_token):
            result.status = ENHANCE_CANCELLED
            result.notes.append("增强请求已取消，未发起调用；本地候选保持不变。")
            self._record(result)
            return result
        if self._config.provider == PROVIDER_HTTP and self._config.credential_env:
            if not self._config.credential_present():
                result.status = ENHANCE_NO_CREDENTIAL
                result.notes.append(
                    "未在用户环境变量 {0} 找到凭据，未发起请求；凭据不会写入项目或日志。".format(
                        self._config.credential_env
                    )
                )
                self._record(result)
                return result
        provider = self._resolve_provider()
        if provider is None:
            result.status = ENHANCE_UNAVAILABLE
            result.notes.append("provider 未配置或类型不可用，本次未发起调用。")
            self._record(result)
            return result

        context = {
            "purpose": purpose,
            "scope": scope_label,
            "text": text,
            "truncated": truncated,
            "maxChars": limit,
            "evidenceIds": [str(item) for item in (evidence_ids or ())],
        }
        self._call_count += 1
        result.attempts = 1
        try:
            if purpose == PURPOSE_REVISION_SUMMARY:
                payload = provider.suggest_revision(context)
            else:
                payload = provider.suggest_terms(context)
        except ProviderTimeout as exc:
            self._fallback(result, ENHANCE_TIMEOUT, exc)
        except ProviderNoCredential as exc:
            self._fallback(result, ENHANCE_NO_CREDENTIAL, exc)
        except ProviderNetworkError as exc:
            self._fallback(result, ENHANCE_NETWORK, exc)
        except ProviderCommandMissing as exc:
            self._fallback(result, ENHANCE_COMMAND_MISSING, exc)
        except ProviderCancelled as exc:
            self._fallback(result, ENHANCE_CANCELLED, exc)
        except ProviderBadResponse as exc:
            self._fallback(result, ENHANCE_BAD_RESPONSE, exc)
        except ProviderError as exc:
            self._fallback(result, ENHANCE_ERROR, exc)
        except Exception as exc:  # noqa: BLE001 - provider 故障不影响编辑
            self._fallback(result, ENHANCE_ERROR, exc)
        else:
            try:
                response = validate_provider_response(
                    payload, purpose=purpose, known_evidence_ids=evidence_ids
                )
            except ProviderBadResponse as exc:
                self._fallback(result, ENHANCE_BAD_RESPONSE, exc)
            else:
                enhanced = [item for item in response.suggestions if not item.instruction_like]
                blocked = [item for item in response.suggestions if item.instruction_like]
                result.enhanced = enhanced
                result.blocked_instructions = [item.text for item in blocked]
                result.status = ENHANCE_OK
                result.used_local_candidates = False
                if blocked:
                    result.notes.append(
                        "响应含 {0} 条可执行指令特征内容，已忽略且从不执行。".format(len(blocked))
                    )
                for note in response.skipped:
                    result.notes.append(note)
                if not enhanced:
                    result.notes.append("增强响应没有可用建议，保留本地候选。")
                    result.used_local_candidates = True
                for item in enhanced:
                    if item.source != "local-evidence":
                        result.notes.append(
                            "建议“{0}”无本地出处，仅作措辞候选，不作为事实证据。".format(
                                item.text[:30]
                            )
                        )
        self._record(result)
        return result

    # --- 内部 ---

    def _fallback(self, result: EnhancementResult, status: str, exc: BaseException) -> None:
        result.status = status
        result.enhanced = []
        result.used_local_candidates = True
        result.notes.append(
            "{0}：{1}；已回退本地候选，正文与项目状态未改动（不自动重试）。".format(
                ENHANCE_STATUS_LABELS.get(status, status), exc
            )
        )

    def _resolve_provider(self) -> Optional[WritingProvider]:
        if self._provider is not None:
            return self._provider
        self._provider = self._provider_factory(self._config)
        return self._provider

    @staticmethod
    def _is_cancelled(cancel_token) -> bool:
        if cancel_token is None:
            return False
        value = getattr(cancel_token, "is_cancelled", False)
        if isinstance(value, bool):
            return value
        if callable(value):
            try:
                return bool(value())
            except Exception:  # noqa: BLE001
                return False
        return bool(value)

    def _record(self, result: EnhancementResult) -> None:
        entry = ProviderRequestLogEntry(
            purpose=result.purpose,
            status=result.status,
            target=result.target_description,
            scope=result.scope_label,
            requested_chars=result.requested_chars,
            actual_chars=result.actual_chars,
            truncated=result.truncated,
            attempts=result.attempts,
            at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._log.append(entry)
        if len(self._log) > self._log_limit:
            del self._log[: len(self._log) - self._log_limit]