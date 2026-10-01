## Why

需求、设计、测试文档已经能共同维护和追溯，但公共术语、接口约定和标准段落仍要反复复制，多个产品型号的文档也容易分叉。V3.0 让团队复用有版本的正文模块，并从同一项目生成明确的产品变体。

## What Changes

- 增加本地正文模块库：从章节提取模块，带图片/复杂表资源、填写参数、来源和版本，支持查找、预览及离线库交换。
- 增加项目内固定版本引用和可选复制编辑，预览、检查、Word、HTML 共用展开结果及来源定位；模块升级显示差异，由用户选择，不自动覆盖正文。
- 增加产品变体配置：明确章节范围、变量覆盖和模块版本选择，输出独立命名及差异报告。
- 复用 V2.8 变量/章节顺序和 V2.9 条目身份/影响服务；复用实例只有明确纳入追踪才计入覆盖率。
- 默认缺模块/参数/资源用合法缓存、原文或占位继续，按 `docs/product-flow-fallback-policy.md` 集中提示，严格交付可选。

## Capabilities

### New Capabilities

- `versioned-content-library`: 带资源的正文模块、本地库、不可变版本与库交换。
- `resolved-content-assembly`: 固定版本展开、参数、来源映射、升级和追踪实例。
- `document-variants`: 命名变体、统一有效内容及独立输出。

### Modified Capabilities

无。为现有渲染、预处理与追踪服务增加输入层，旧项目与普通正文行为保持兼容。

## Impact

- 涉及 `application/prepared_source.py`、`chapter_order.py`、`content/{preview,refactor,traceable_items,impact}.py`、资源服务、编辑器与构建入口。
- 新增项目内 `reuse/`、`variants.yml` 可选 sidecar（各自 schema 1）；保留 project schema 1/2，不强制迁移、不扩大外部任意路径读取。
- 直接前置为 V2.8 变量/顺序/规范读取、V2.9 身份与集合服务的相关接口；其余版本实机待验收不阻止独立开发。
- 首版范围为本地固定版本模块与声明式变体；排程和执行台账见 `docs/product-plan-v3.0-v3.3.md`。
