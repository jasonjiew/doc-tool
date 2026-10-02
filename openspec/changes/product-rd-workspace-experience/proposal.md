## Why

V2.8/V2.9 已提供工作区、设置模型、显式追踪、影响和版本集合服务，研发文档团队仍需通过文件或代码操作其中多项能力。接通日常界面后，用户才能完成需求—设计—测试联动，已有服务投入才能形成可用产品。

## What Changes

- 新增可选研发工作区入口：成员角色、项目概览、下一步操作，以及完整项目设置；单文档直接编辑和出稿保持可用。
- 将稳定条目、双端关系、分页矩阵、来源跳转和影响复核接入界面，沿用已有显式关系与内容版本语义。
- 将版本集合列表、差异、导出包和恢复副本接入界面，使用已有集合服务及 CORE 统一出稿接口。
- 按真实回归证据区分已有测试问题与产品问题；提供缺少成员、无 Git、无 Word、部分成功时的可操作结果。

## Capabilities

### New Capabilities

- `rd-workspace-surface`: 研发工作区、成员管理、概览与设置的用户交互。
- `rd-traceability-surface`: 稳定条目、显式关系、矩阵及影响复核的用户交互。
- `rd-collection-surface`: 版本集合查看、比较、打包和恢复副本的用户交互。

### Modified Capabilities

无。底层工作区、关系、复核及集合语义沿用现有规范；本 change 补充界面契约。

## Impact

主要涉及 `doc_tool/ui/main_window.py`、内容工作台、新工作区面板及应用适配层；复用 `workspace.py`、`overview.py`、`settings.py`、`content/traceable_items.py`、`relations.py`、`trace_matrix.py`、`impact.py`、`collection.py`、`collection_ops.py`。关联 CORE 的有效内容捕获和统一导出；不重复建设 V3.1 交接引擎或 V3.2 持久队列。6 批/24 项，详见 tasks；本次只规划。
