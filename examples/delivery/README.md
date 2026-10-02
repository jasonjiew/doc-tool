# V3.2 批次交付示例：无 Word runner 生成包 → 有 Word 机器补刷新

本目录是 `openspec/changes/product-v32-batch-delivery` 任务 6.3 的可复制示例：

- `batch.json`：schema 1 批次计划（两个成员 `members/Alpha`、`members/Beta`）。
- 本文件：按**真实 CLI help** 说明 Windows 无 Word runner 的取包流程，以及有 Word
  机器的补刷新流程。

> **平台声明（按实测）**：以下命令在 `Windows` + `Python 3.13.13` 实测；本机 `Word`
> 可用，因此「无 Word」分支用 `--no-refresh` 显式跳过 Word 刷新来复现（逐项转
> 「待刷新」）。**没有**在无 Word 的独立机器、也没有在第二台真实机器上实测；两机
> 交接与真实 Word 正式化属实机待验收项（V3.2 7.3）。其它操作系统未验证，不作为
> 支持范围声明。

## 0. 准备成员目录

`batch.json` 里的成员是**占位相对路径**，按「计划文件所在目录」或 `--base-dir` 解析：

```text
<你选的基准目录>/
  members/Alpha/project.yml + content/...
  members/Beta/project.yml  + content/...
```

把 `batch.json` 复制到你的工作目录，或直接用 `--base-dir` 指向成员所在目录
（这样不必改动示例文件）：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path
python doc_tool_cli.py delivery-plan --plan examples\delivery\batch.json `
  --base-dir D:\work\交付批次 --json
```

`delivery-plan` **只预览不执行**：逐条列出成员、变体、格式、输出目标与成员级问题
（成员目录不存在/缺 `project.yml` 只影响该项并集中提示）。退出码 `0` = 计划已解析；
`2` = 计划不可读或结构非法（schema 不符、没有 entries）。

## 1. 无 Word runner：先拿到可读稿与交付包

```powershell
# 1.1 串行执行：本机不做 Word 刷新，逐项转「待刷新」（可读 DOCX/DOCX+HTML 仍生成）
python doc_tool_cli.py delivery-run --plan examples\delivery\batch.json `
  --base-dir D:\work\交付批次 --store D:\work\交付批次\delivery-queue.json `
  --no-refresh --json

# 1.2 打成自足交付包（包内一律相对路径，含固定快照/报告/可读 DOCX）
python doc_tool_cli.py delivery-package --store D:\work\交付批次\delivery-queue.json `
  --target D:\work\交付批次\delivery-package.zip --json

# 1.3 查询队列与结果（只读；store 里有失败项也返回 0，失败信息在报告内）
python doc_tool_cli.py delivery-status --store D:\work\交付批次\delivery-queue.json --json
```

退出码（`delivery-run` / `delivery-retry` / `delivery-package` / `delivery-promote`）：

| 退出码 | 含义 |
|---|---|
| `0` | 至少得到一个所请求范围内的可用结果（可含部分失败/待刷新/可读稿） |
| `1` | 完全没有可用结果；或 `--strict` 严格阈值未满足 |
| `2` | 参数或输入非法（计划不可读、schema 不符、没有可执行成员、store 缺失、包不存在） |

`delivery-status` 是只读查询，正常返回 `0`；`delivery-plan` 只预览，`0` = 计划已解析、
`2` = 计划不可读或结构非法。机器报告：加 `--json` 时 stdout 只有一个 JSON 文档，
过程日志在 stderr。

## 2. 有 Word 的机器：按包内固定快照补刷新并登记

把 `delivery-package.zip` 拷到有 Word 的机器（或本机另一个目录）后：

```powershell
# 2.1 补刷新 + 本地登记（不需要原电脑的项目路径）
python doc_tool_cli.py delivery-promote D:\work\交付批次\delivery-package.zip `
  --destination D:\work\交付批次\正式化 --json

# 2.2 本机确实没有 Word 时：只保留待刷新可读稿，包不删除，稍后再试
python doc_tool_cli.py delivery-promote D:\work\交付批次\delivery-package.zip `
  --destination D:\work\交付批次\待刷新 --word-available no --json

# 2.3 只补没做完的成员（复用该项原轮快照，不重走全部任务）
python doc_tool_cli.py delivery-retry --store D:\work\交付批次\delivery-queue.json --json
```

- `delivery-promote` 的正式级别只由既有 `OutputState` 判定；无 Word / 刷新失败时保持
  `waiting-refresh`，**原包不删除**，可读 DOCX 仍在。
- 本地登记键 = `packageId + 输入 digest + 目标位置`：重复处理同一包同一目标目录返回
  `already-registered`（直接打开已有结果，不重复建历史）；登记失败保留新 DOCX 安全副本。
- 幂等范围只承诺**本地共同登记**，不承诺跨机器无共同记录的全局去重。

## 3. 取消、继续与中断（同一 store 上重复执行）

```powershell
# 只跑前 1 个成员，其余未开始项取消（已完成结果保留）
python doc_tool_cli.py delivery-run --plan examples\delivery\batch.json `
  --base-dir D:\work\交付批次 --store D:\work\交付批次\delivery-queue.json `
  --no-refresh --cancel-after 1 --json

# 继续上次未落定项（queued/interrupted）；已完成项默认跳过
python doc_tool_cli.py delivery-run --plan examples\delivery\batch.json `
  --base-dir D:\work\交付批次 --store D:\work\交付批次\delivery-queue.json `
  --no-refresh --continue --json
```

## 4. 没有做的事

示例脚本只产生本地可审阅结果：**没有**上传、通知、公开发布或任何远端写入步骤；
`--plan`/`--store`/`--target`/`--destination` 都指向你给的本地路径，示例默认不写仓库目录。

## 5. 本机实测记录

见 `docs/product-v32-execution-entry.md` 第 3、4 节（命令、退出码、JSON 报告形状与
未验收项）。仓库测试 `scripts/tests/test_v32_delivery_entry.py` 会用真实两章项目
夹具执行同一批命令（`--base-dir` 指向临时目录），因此本示例的成员路径解析、退出码
与报告字段是被自动测试覆盖的；`members/Alpha`、`members/Beta` 本身是占位路径。
