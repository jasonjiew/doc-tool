# V3.0 复用/变体格式与展开回退指南

配套：[使用说明与限制](product-v30-v33-usage.md)、[V3 总计划](product-plan-v3.0-v3.3.md)、[V3 台账](product-plan-v3-execution.md)。

## 1. 固定引用格式（正文内）

```doc-module id=<moduleId> version=<version> slot=<slotId>
key = value            # 可选：本次引用的参数覆盖（缺省用声明默认值）
```

- ```doc-module-copy ...``` 用于“复制编辑”：展开一次后即可在宿主章节里自由修改，不再跟随模块升级。
- `headingOffset` 可选，用于调整展开内容的标题层级；省略即按声明层级。
- 一个章节可含多个引用；同一 slot 在同一项目内重复引用会复用同一实例身份（覆盖率分母只计显式纳入的 host）。
- 引用写在**章节正文**里（普通 Markdown），不写在 front matter。

## 2. 项目侧声明（`reuse/assembly.yml`）

- 记录每个 slot 的固定参数：`reuse resolve`/`reuse build` 与预览、检查、Word、HTML 共用同一份解析入口。
- 选择性升级只改动被选中的 slot；未选中的固定副本保持原样（库升级不会自动改动已引用内容）。
- 库位置：项目内 `reuse/library/<moduleId>/<version>/`（不可变版本 + `module.yml` + `_body.md` + 资源）。
  如 `project.yml` 里写了 `reuse.library`，以该配置为准；否则项目内固定副本优先。

## 3. 变体格式（`variants.yml`，schema 1）

```yaml
schemaVersion: 1
variants:
  - variantId: model-a        # 稳定标识：命令、报告、产物目录都用它
    name: 甲型号
    include: []               # 只纳入列出的章节（为空=全部）
    exclude: [第2章]           # 排除章节（与 include 同时存在时先 include 再 exclude）
    variables: {productName: 甲型号}
    slots: {s1: {param: value}}   # 该变体下的 slot 参数覆盖
    modules: {m-alpha: 1.1.0}     # 该变体固定使用的模块版本
```

- 未写 `variants.yml` 时项目按“整份”处理，行为不变；未知 `variantId` 返回可读错误并列出可用值。
- 出稿会记录**实际有效范围**：纳入/排除章节、变量、各模块版本与 hash，报告里可核对。

## 4. 展开回退指南

| 情形 | 行为 | 用户可见结果 |
|---|---|---|
| 缺模块或版本 | 先找同版本缓存；仍缺则插入可见占位并提醒 | 其余正文继续出稿，报告列出占位位置 |
| 缺参数 | 用声明默认值；无默认则保留字面值并提醒 | 不静默改变作者原意 |
| 循环引用 | 只停止该引用（不递归展开） | 其它引用与正文继续 |
| 展开失败（IO/解析） | 保留原文并记录失败原因 | 构建不中断，阶段说明给出失败处数 |
| 交旧应用/外部作者 | `reuse clone` 生成普通 Markdown 副本（无引用标记、资源随行、可搬目录） | 副本内 `_copy.yml` 记录来源与模块版本 |
| 换目录/换机器打开副本 | 相对路径 + `verify_portable_copy` 自检 | 无问题即可直接使用 |

## 5. 版本源与 V3.0 发布号

- 应用版本源当前为 **2.9.0**（最近一次正式发布）。本轮**不修改**版本源。
- V3.0 尚未发布：**发布号在同批正式发布时按当时最高版本确定**（不与其它版本并列发布时沿用 2.9.0 + 单独功能说明）。此决定与 [V3 总计划](product-plan-v3.0-v3.3.md) 的“版本号在收尾依据实际最高版本校正”一致。
- 冻结包（PyInstaller）与实机 Word 版式检查属发布前实机项，未执行前不勾选对应收尾任务。
