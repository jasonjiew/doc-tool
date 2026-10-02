# -*- coding: utf-8 -*-
"""V3.3 本地写作辅助与可选模型（product-v33-authoring-assistance）。

批次对应关系：

- 33-A ``search_local``：显式范围的本地资料检索（来源/版本/定位/陈旧/未保存）。
- 33-B ``suggestions``：确定性建议与修订摘要候选（复用规则/术语/引用/复核）。
- 33-C ``adoption``：差异采纳与一次撤销（只改编辑缓冲，保存走 ContentWriter）。
- 33-D ``provider``：可选摘要/术语增强 provider（默认禁用，故障回本地候选）。
- 33-E ``service``：门面，把上述能力接到项目/编辑器/CLI 的既有入口。

无模型、无网络、无账户时基础功能完整可用。
"""

from __future__ import annotations

__all__ = ["models", "search_local", "suggestions", "adoption", "provider", "service"]