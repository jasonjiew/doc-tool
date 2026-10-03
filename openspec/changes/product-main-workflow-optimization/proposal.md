## Why

当前导入、编辑、检查和多格式出稿已有实现，V3.7～V3.9 主要补用户入口与交互。企业研发文档日常还需要核对内容/资源往返、未保存内容批量修改、章节引用联动和常见 Word 排版，才能从“能完成操作”推进到“少返工地得到可交付内容”。

## What Changes

- 导入后按章节核对标题、列表、表格、图片、链接和保留对象；Markdown 多来源中的不同目录同名资源独立解析，默认继续可用内容。
- 编辑支持当前缓冲的按范围查找替换、差异预览和局部应用；章节调整、批量修改及恢复复用现有写入/重构/撤销能力。
- 图片插入、缺图替换和章节引用修复贯通编辑、预览、检查与出稿，项目副本能独立打开资源。
- 当前章/选章/整份检查读取当前内容；输入后的预览/检查使用真实代次，支持确定性修复预览、撤销和局部重检。
- 为常见 Word 表达建立可复现样例：标题/列表、普通表格、图片、代码、链接和目录字段；默认版式/底模回退透明，来源范围及旧轮重试契约不变。
- 新增 MAIN-A～F 六批/24 项，与既有三包各自保留编号；已实现行为先验证，只补真实差额。

## Capabilities

### New Capabilities
- `core-intake-quality`: 常见内容导入核对、多来源资源身份、正常流程与局部继续。
- `core-authoring-productivity`: 当前缓冲批量修改、章节/资源引用联动、检查修复与预览连续性。
- `core-output-quality`: 常见内容表达、实际版式/底模、可读成果及多格式来源一致性。

### Modified Capabilities
无。新增组合验收和增强行为，沿用原 schema、项目正文、来源捕获、保存/引用及正式状态约束，不移除旧要求。

## Impact

复用 intake/import/project_from_markdown、content writer/refactor/chapter_reorder/replace/references、图像资源面板、ContentLinter、预览与 EffectiveSnapshot、project_export/layout_profile 和现有出稿适配。V3.7 负责共享日常交互，V3.8 负责导入/出稿设置及表格/规范制作 UI，MAIN 负责本文新增主功能差额与真实内容验收；共同调用同一业务接口。无需新增云服务、模型、账号或 Word 强制依赖。
