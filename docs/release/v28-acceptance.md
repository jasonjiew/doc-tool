# V2.8 受控发布验收记录（product-v28-team-standardization）

- 应用版本：**2.8.0**；项目模式版本：**2**（v1 仍可读可写）
- 验收环境：Windows + Python 3.13.13 + PySide6 6.8.3（仓库内 vendored）
- 证据目录：``docs/release/evidence/``

## A28 验收项状态

| 编号 | 验收项 | 状态 | 证据 |
|------|--------|------|------|
| A28-1 | 规范包可分发、可验证、可固定版本 | 通过 | ``v28-team-samples.json``（三包 valid/installed/reloaded）、``test_standard_pack_v28.py`` |
| A28-2 | 三类包跑建项→编辑→检查→交付 | 通过 | 三包 ``check=ok``，内核校验 ``PASS=18 FAIL=0`` |
| A28-3 | v1 → v2 迁移预览/备份/幂等与回退 | 通过 | ``v28-team-samples.json`` 的 ``migration``；``test_schema_v2_migration.py`` |
| A28-4 | 坏配置/缺章节变量默认继续，严格模式另测 | 通过 | ``termsFallback``（损坏回退）、``reviewGate``（默认 allowed / 严格拦截） |
| A28-5 | 部分重导入（冲突跳过、余项应用） | 通过 | ``test_reimport_plan_v28.py``（21 例，含真实 Git 冲突） |
| A28-6 | 真实团队试点（作者/评审人/文档负责人） | **待验收** | 需真实团队人员与现场；本工具不代替人员参与 |
| A28-7 | Word/冻结/安装升级验收 | **部分待验收** | Word 可用时已真实刷新域；人工版式与安装/卸载需人工复核 |

## 实际执行记录

- ``python tools/gen_v28_acceptance.py``（真实服务，无 mock）——三包均 ``valid=True installed=True reloaded=True check=ok``，
  迁移后 ``finalSchema=2``。证据：``docs/release/evidence/v28-team-samples.json``。
- ``python scripts/tests/run_tests.py --junit <path>``（全量套件）——见最新 ``v28-*.xml``。
- ``openspec validate product-v28-team-standardization --strict``。

## 明确保留的限制

1. **A28-6 真实团队试点**：本次会话无法组织真实人员参与，保留为待验收，**不标记通过**。
2. **A28-7 人工视觉版式与安装/卸载**：冻结包与安装器的真实安装、升级、卸载与透明加密环现需人工，
   保留为待验收。
3. ``git_stage_resolved`` 在“索引已有未合并条目”时仍返回 False，已记入待改项（未伪装通过）。
