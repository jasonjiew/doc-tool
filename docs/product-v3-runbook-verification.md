# 验收清单本机可验证部分（自动执行结果）

生成时间：2026-10-02T07:01:03.682718+00:00
生成方式：`python scripts\release\verify_runbook.py --with-tests`（可按需加 `--with-word`）
完整验收步骤见 `docs/product-v3-acceptance-runbook.md`。

## 1. 本机已执行

| 项 | 步骤 | 结果 | 说明 |
|---|---|---|---|
| A1-A4 | 同步/归档前置核对（dry-run，未改动仓库） | 通过 | 授权后执行：python scripts\release\archive_changes.py --yes |
| C2 | 冻结/本机环境自检（写入与 docx 可读性） | 通过 | 本机环境通过自检（目录可写、docx 可读） |
| C2 | 冻结 CLI 环境自检（写入与 docx 可读性） | 受限 | 冻结产物受环境限制：PermissionError: [Errno 13] Permission denied: 'C:\\Users\\18098\\AppD；建议：当前环境不允许本程序写入该目录：请把 DocTool.exe 加入透明加密/杀软信任列表，或改选用户目录下的其它位置 |
| C3 | 高 DPI 缩放因子模拟回归（1 / 1.25 / 1.5） | 通过 | 物理缩放仍需实机 |
| C5 | Mermaid 渲染（mmdc） | 通过 | 使用 D:\ai_develop_project_space\doc-tool\tools\mermaid-cli\node_modules\.bin\mmdc.cmd 渲染成功 |
| B1 | B1 团队交接（真实文档 + 两独立副本代理） | 通过 | 用例通过（人工多人/多文档环节仍需人工） |
| B2 | B2 三类文档试点（自动化部分与数据） | 通过 | 用例通过（人工多人/多文档环节仍需人工） |
| C1 | C1 实机 Word 正式化 + 换机等效 | 通过 | 用例通过 |
| C1 | C1 进程级换机登记 | 通过 | 用例通过 |

## 2. 仍需人工/实机/授权

| 项 | 内容 | 依赖 | 说明 |
|---|---|---|---|
| A1-A4 | 真正归档（需用户授权） | authorization | 授权后执行 python scripts\release\archive_changes.py --yes |
| B1 | 真实团队多人交接 | human | 需两位真实同事与各自目录；自动化代理已通过 |
| B2 | 三类文档人工质量评价 | human | 需人工对建议质量评分；自动化数据已留档 |
| C2 | 冻结包写入类闭环 | env | 需把 DocTool.exe 加入透明加密/杀软信任列表，或换干净机器（实测：当前环境不允许本程序写入该目录：请把 DocTool.exe 加入透明加密/杀软信任列表，或改选用户目录下的其它位置） |
| C3 | 物理 125%/150% 显示器实测 | env | 需可切换缩放的真实显示器 |
| C4 | 真实两台物理机器交接 | env | 需第二台机器 |

## 3. 小结

- 本机执行 9 项：通过 8 项，受限/未通过 1 项
- 仍需外部条件 6 项：authorization、env、human
