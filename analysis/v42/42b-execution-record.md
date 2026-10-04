# V4.2 42-B 增量计算实施记录（待并入联合台账）

日期：2026-10-03 / HEAD `7ba19dd` + 本轮工作树 / change `product-v42-incremental-quality-workbench` / 批次 42-B

## 任务编号 / 已实现与本次差额

- **42-B 2.1**（已勾选）：`incremental_index.content_digest` 增加进程内 stat 指纹缓存，
  键为 `(绝对路径, st_size, st_mtime_ns)`；任一变化都会重新读取并重算 sha256，
  因此**同大小/同时间改写仍被发现**（不靠 mtime/size 单独判定未修改）。
  容量超限整体丢弃；另提供 `reset_digest_cache()`。
- **42-B 2.2**（已勾选）：`ContentLinter` 增加结果复用缓存，键包含
  真实正文摘要（每章路径 + 行数 + 内容 sha256）+ 规则启用/严重级别/参数 +
  解析器版本 + 文档类型集合 + terms；提供 `reset_lint_result_cache()` 与
  `use_result_cache=False` 强制完整重算。缓存结果与完整重算逐项一致。

## 命令 / 解释器与依赖 / 退出码

- `python -m pytest scripts\tests\test_v42_incremental_correctness.py -q -p no:cacheprovider` → **9 passed，退出码 0**
- `python -m pytest scripts\tests\test_format_check_search.py scripts\tests\test_quality_gates.py scripts\tests\test_main_d_lint_scope.py scripts\tests\test_v38_pack_skeleton_mode.py scripts\tests\test_v39_matrix_coverage.py -q -p no:cacheprovider` → **28 passed，退出码 0**
- `python -m pytest scripts\tests\test_v36_large_document.py scripts\tests\test_authoring_services.py scripts\tests\test_format_check_search.py -q -p no:cacheprovider` → **122 passed，退出码 0**
- `python analysis\v42\measure_staged.py` → 退出码 0
- 环境：Python 3.13.13 / pytest 9.1.1 / PySide6 6.8.3 / Windows-11-10.0.22631-SP0 / AMD64

## 量测事实（前后对比，原始样本见 analysis/v42/measure-staged.json）

| 章数 | 改动前 p95 改善 | 改动后 p95 改善 |
|---|---|---|
| 50 | +69.3% | **+78.6%** |
| 300 | +2.05% | **+11.0%** |
| 1000 | −8.7% | **+5.0% ~ +10.9%（多次运行有波动）** |

- 目标「主要热路径 p95 改善 ≥ 30%」→ **仍未达成**（仅 50 章档达标）。
- 「50 章不恶化超过 10%」→ 满足。
- 分阶段事实（1000 章 p95）：`discover` 162ms、`index` 456ms、`read` 100ms、
  `rules`（命中结果缓存）47ms。**剩余瓶颈是索引构建与目录遍历，不是规则遍历**。

## 被否决的改动（如实记录）

把 `discover_files` 从「按后缀 `rglob`」改成「一次 `rglob("*")` + Python 侧筛后缀」
**反而更慢**：1000 章 cold discover 149ms → 244ms（每个目录项都多一次 Python 层判断）。
已按实测回退，并在代码注释中记录结论来源，避免后人重复同一“直觉优化”。

## 任务勾选依据 / 未覆盖项

- 2.1 / 2.2 按上述命令与样本勾选。
- **2.3 未勾选**：跨章编号/术语/链接/覆盖及模块/变量的失效策略只做了“键包含正文与
  规则参数”这一层，尚未逐类验证移动/删除/依赖变化的失效边界。
- **2.4 未勾选**：活缓冲内存派生、坏缓存/旧版/容量不足回退已有实现基础，
  但“任务按项目/范围/代次登记、取消或切项目后不串入新工作集”未验证。

## 下一直接任务 / 可独立继续项

- 42-B 2.3 / 2.4，随后 42-C（问题工作台分组与时点）。
- 按实测继续压低 `index` 构建与 `discover` 的重复工作（这两个才是 300/1000 章的瓶颈）。