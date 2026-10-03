## Why

规范包、模板填充、样式映射和正文版式已有实现，企业成员仍需要把选模板、试效果、保存常用设置和再次出稿连成简单操作。负责人维护的规范应能直接复用，模板失效时也能继续获得可读文档。

## What Changes

- 在既有规范包/模板/recipe上提供本地模板目录与最近使用，区分新建骨架、填充已有模板和当前项目出稿。
- 保存受支持的版式/样式设置预设，实际字段白名单和失效项就地处理，普通快速出稿保持整份当前内容默认。
- 选模板后按需生成小样，展示实际底模、映射、表格/图片处理；HTML标为内容预览，真实分页由Word实证。
- 模板更换/版本差异可查看，修改副本和未知声明保留，规范schema 1消费保持。
- 完成负责人制作→成员选择→样例→当前内容出稿闭环，五批20项。

## Capabilities

### New Capabilities
- `enterprise-template-library`: 本地模板目录、用途选择、版本和现有规范资源复用。
- `template-recipe-and-trial`: 受支持预设、有效默认、小样和实际模板效果事实。

### Modified Capabilities
无。复用原模板/规范schema和实际导出参数，增加选择、试用和可重复工作流。

## Impact

涉及standard_pack/pack_authoring、template_fill/plan/presets、样式映射对话框、LayoutProfile、导出设置和样例成果。复用CORE及V3.5/V3.8资源制作，不新增在线市场、任意Word版式编辑器或模板字段猜测。
