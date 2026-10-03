# V3.5 规范包制作执行台账

更新日期：2026-10-03（Asia/Shanghai）。执行基准 HEAD `d68b514` + 工作树。任务勾选只由 [V3.5 tasks](../openspec/changes/product-v35-standard-pack-authoring/tasks.md) 维护。统一入口见 [总路线图](product-master-roadmap.md)，能力现状见 [功能清单](product-function-catalog.md)。

本包沿用既有 `pack.yml` schema 1 与加载/安装契约；不发行第二种包格式，不执行任何脚本，不修改源项目或已固定安装包。

## 1. 批次状态

| 批次 | 状态 | 用户入口 | 证据 |
|---|---|---|---|
| 35-A 草稿与字段映射 | 完成 1.1～1.4 | 服务层 `application/pack_authoring.py` | [相关回归](../analysis/product-v35-pack-20261003/v35-related.xml) |
| 35-B 制作界面 | 完成 2.1～2.4 | 菜单「内容 → 规范包制作…」(Ctrl+Alt+P) | 同上 |
| 35-C 冻结与本地分享 | 完成 3.1～3.4 | 对话框「清单与冻结」页：冻结规范包 / 导出 ZIP / 打开所在目录 | 同上 |
| 35-D 隔离样例验证 | 完成 4.1～4.4 | 对话框「样例验证」页：在隔离样例中试用 / 打开样例成果 | [样例结果](../analysis/product-v35-pack-20261003/sample-result.json) |
| 35-E 验收与交接 | 5.1、5.2、5.4 完成；5.3 部分（窗口与键盘已自动验证；企业模板/真实 Word 试点待验收） | — | [闭环证据](../analysis/product-v35-pack-20261003/closed-loop.json) |

## 2. 实现要点

1. 资源映射以现有消费者为准（`RESOURCE_MAPPING`）：`variables.yml` ↔ 项目 `variables`、`terms.yml` ↔ `quality/terms.json`、`rules.yml` ↔ `quality/rules.json`、`template.docx` ↔ 项目底模、`skeleton/*.md` ↔ 选定章节；未知声明式字段进 `extra` 原样保留。
2. 草稿与可安装产物分离：`pack-draft.json` 允许缺 version/packId；`validate_draft` 只阻止导出，不阻止保存/重开。
3. 冻结按实际文件内容生成 `files` 摘要并用既有 `validate_pack_dir` 校验；同版本同摘要复用，同版本不同内容**另存新目录**且提示“未覆盖”。
4. 导出 ZIP 只含声明资源：显式排除 `.git`、`credentials.json` 等凭证、缓存、历史与产物目录；由既有 `extract_pack_zip` + `create_project_from_pack` 完成消费往返。
5. 隔离样例：在草稿目录下 `sample/pack-preview` 冻结 → `sample/sample-project` 建项 → 既有 `run_check` 与 CORE 出稿；结果区分结构合法/规则问题/可读成果/待刷新/正式成功/未验证，并绑定草稿摘要与 captureId；草稿变化后旧样例标为过期。
6. 顺带修复两处环境相关健壮性问题：`PackDraft.save` 与 `standard_pack.install_pack` 在拒绝目录级原子重命名的企业 PC 上回退为 `shutil.move`。

## 3. 每批交接记录

```text
日期 / 执行 HEAD / 工作树基准 / 包 / 批次：2026-10-03 / d68b514 + 工作树 / product-v35-standard-pack-authoring / 35-A～35-E
完成任务编号 / 当前 tasks 勾选：1.1-1.4、2.1-2.4、3.1-3.4、4.1-4.4、5.1、5.2、5.4 / 19/20（5.3 企业模板与真实 Word 试点待验收）
复用的真实服务与直接依赖：standard_pack.py（校验/指纹/安装）、project_from_pack.py（建项）、settings.load_settings（资源读回）、check.run_check、CORE project_export
本批补的差额：见第 2 节；另修 install_pack/PackDraft.save 的目录重命名兜底
用户入口 / 操作步骤 / 实际结果 / 产物位置：菜单「内容 → 规范包制作…」→ 从当前项目/已有包创建草稿 → 编辑资源 → 保存草稿 → 冻结 → 导出 ZIP → 隔离样例试用；结果与证据见 analysis/product-v35-pack-20261003/
来源模式 / captureId / projectId-itemId / 源与缓冲事实：样例使用 CORE 已保存内容捕获并记录 captureId；样例项目隔离在草稿目录内，源项目与缓冲不被修改（断言源项目文件字节不变）
默认正常 / 自动兜底 / 待完善 / 未执行：正常＝项目→草稿→冻结→ZIP→同事建项闭环；兜底＝缺 version 仍可保存草稿、缺底模回退通用底模、坏可选资源不阻断建项、同版本冲突另存、包结构不可消费时不生成 ZIP；待完善＝高级规则仍以 JSON 原文编辑；未执行＝企业真实模板与 Word 视觉试点
相关验证命令 / 环境 / 退出码 / 报告：见第 4 节
Word、剪贴板、冻结、视觉或性能实测证据：样例 DOCX 为诊断构建（status 见 sample-result.json）；真实 Word 刷新与视觉为待验收
已有失败分类 / 环境缺失 / 剩余风险：企业模板视觉、Word 正式样例未在本机验证
下一直接任务 / 阻塞动作与可继续动作：35-E 5.3 实机视觉待环境；功能队列继续 V3.6
```

## 4. 验证命令与证据

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:PRODUCT_V35_EVIDENCE='1'
$env:PYTHONPATH='D:/ai_develop_project_space/doc-tool/tmp/v26-test-deps'
$env:QT_QPA_PLATFORM='offscreen'
& 'C:/Users/18098/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' scripts/tests/run_tests.py --junit analysis/product-v35-pack-20261003/v35-related.xml test_v35_standard_pack.py test_standard_pack_v28.py test_project_from_pack_v28.py test_bundled_standards_v28.py
```

- [隔离样例结果](../analysis/product-v35-pack-20261003/sample-result.json)：结构合法、可读 HTML 有、Word 为诊断构建、正式成功否、未验证项已列出。
- [制作到消费闭环](../analysis/product-v35-pack-20261003/closed-loop.json)：schema 1、ZIP 文件数、同事项目章节与变量读回。
- 本包新增 `scripts/tests/test_v35_standard_pack.py` 20 项用例（含界面字段定位、冻结冲突、ZIP 排除与隔离样例）。

## 5. 待验收项（保持未勾选）

| 项 | 原因 | 复验步骤 |
|---|---|---|
| 35-E 5.3 企业模板与真实 Word 试点 | 本机无企业模板与真实 Word 交互条件 | 选一份企业 DOCX 底模制作包 → 冻结导出 → 用 Word 打开样例项目正式出稿，核对封面/页眉与正文变量支持范围；记录未绑定字段 |
| 样例正式状态 | 需要真实 Word 刷新 | 用 Word 执行样例项目正式出稿，确认 `wordStatus` 由待刷新转为正式，并核对与可读 HTML 内容一致 |

全量回归（最终状态，含 36-C/36-D 补齐后）：`scripts/tests/run_tests.py` 默认清单 **171 个测试文件、0 失败、内部用例 2801 项**（1747s），报告 `analysis/product-full-regression-round2.xml`；此前一轮（本轮功能前）为 [171 文件 / 0 失败 / 2791 项](../analysis/product-full-regression-green.xml)。

## 实施后审查补记（2026-10-03）

已继承本包实现并补真实差额，范围、修复和验收见 [实施后报告](product-post-implementation-review-20261003.md)。本次相关回归27文件/552用例、最终规范回归4文件/75用例以及报告回归7用例通过；保留本包原实机未完成项，没有重置原勾选。当前新开发接 [MAIN+V3.7～V3.9](product-v37-v39-roadmap.md)，正常首项MAIN-A 1.1，已有批次先完成再插入；此前171文件全量为历史证据。
