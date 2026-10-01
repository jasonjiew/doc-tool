## Why

现有用户需要先理解 Word 导入、Markdown 章节、修订记录和多个工具入口，规范规则也缺少可共享配置。企业研发团队需要通过文档规范包快速起步，并在一个任务界面完成检查、评审和交付。

## What Changes

- 延续默认尽力完成：可选规范/规则/术语损坏回退内置或上次有效值，缺章节/变量给可读说明，个别重导入冲突跳过并应用其余项；待复核默认提醒，严格交付显式选择。
- 增加声明式文档规范包：Word 底模、章节骨架、变量、术语、规则和输出策略；提供脱敏的需求/设计/测试示例包。
- 引入可备份、可预览、失败可回滚的 project schema v2，显式章节顺序、变量、规范包版本；v1 继续读取与构建，升级由用户选择。
- 新建入口覆盖从规范包起步、接管已有 Word、导入 Markdown 成为可持续维护的项目。
- 项目概览聚合当前版本、变更、阻断问题、待评审、交付记录和下一步动作；设置页支持编辑规则、变量、门禁与样式映射。
- 将现有评审意见关联到内容版本，补齐待修改/待复核/通过/失效生命周期、修订记录事实预填、离线 HTML 评审包及幂等回流。
- 重新导入源 Word 采用异步计划/差异预览/选择应用/失败回滚，不覆盖未保存内容。
- 补齐 Markdown Git 冲突预览与明确选择后的解决流程，二进制及 SVN 不支持场景提供外部处理指引。

## Capabilities

### New Capabilities

- `document-standard-pack`: 规范包解析、验证、安装、固定版本及声明式文档类别。
- `project-schema-v2`: 清单迁移、显式章节编排与变量一致解析。
- `project-onboarding-overview`: 三种建项路径、任务概览与可编辑设置。
- `versioned-review-loop`: 基于内容版本的评审、离线意见回流、修订预填和重导入复核。

### Modified Capabilities

无。新增文档类别来自规范包 `documentKind`，不恢复企业专属硬编码 `documentType`。

## Impact

- 涉及 `domain/{manifest,version}.py`、迁移/导入服务、设置/首页/项目概览、章节排序/引用索引、规则/术语、评审存储/面板与 HTML 导出。
- 新增项目内 `standards/`、版本控制中的规则/术语文件、schema v2 字段及迁移备份；新 schema 对旧应用不兼容，必须只读提示并保留回退副本。
- 前置：`product-v27-reliable-delivery`；下一版为 `product-v29-change-traceability`。
