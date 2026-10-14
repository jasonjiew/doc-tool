# 试点报告：研发流程接入与 GitLab MR 附件样例

> 本文件为根据 `evidence/doc-tool-remediation-plan-2026-10-14.md` 第 6 节要求生成的试点交付证据样例。  
> 试点业务范围参考 `hcp-docs/requirements/` 第 6 章「6.5 呼吸机接口 -> 6.5.1 呼吸机第三方转发」模块。

---

## 研发变更元数据

| 属性 | 取值 / 标识 |
| :--- | :--- |
| **变更 ID (Change ID)** | `CHG-20261014-VENTILATOR-FORWARD` |
| **OpenSpec 规格变更** | `doc-tool/openspec/changes/devflow-cli-and-portable-delivery/` |
| **关联 GitLab MR** | `!1048 (feat: 呼吸机第三方转发配置与接口幂等回调)` |
| **报告生成工具** | `doc-tool-cli.exe v3.0.0 (commit: 83094d0a0eb3, frozen=true)` |
| **综合门禁判定** | `FAILED / BLOCKED (基线冲突待人工确认，且存在 1 项测试跳过)` |

---

## 1. 文档基线核对（`baseline-check` 输出）

针对业务文档 `requirements/KF-2090-1-001 康尚健康云软件需求说明书` 执行核验：

```powershell
& $env:DOC_TOOL_CLI baseline-check `
    --project "D:/ai_flow_space/hcp-docs/requirements/KF-2090-1-001 康尚健康云软件需求说明书" `
    --declare-file "D:/ai_flow_space/hcp-docs/README.md" `
    --format json
```

### 核对发现与风险提示：
- **清单声明版本**：`3.8`（来源：`requirements/.../manifest.yaml`）
- **修订记录版本**：`3.8`（来源：`content/requirement/_revision_record.md` 末行 `| V3.8 | 新增模块：第6章 接口需求 -> 6.5 呼吸机接口... | 2026-7-20 | 王杰/梁志雄 |`）
- **根目录声明版本**：`3.10`（来源：`hcp-docs/README.md` 第 9 行与第 38 行）
- **门禁状态**：`[CONFLICT]`。
- **团队决策指示**：`TODO(待团队确认)` —— 工具禁止自动取大（3.10），需由系统分析师与产品经理在 MR 合并前确认实际批准版本。

---

## 2. 条目影响分析与关联追踪（`item-list` / `impact`）

### 2.1 涉及的原子条目（DOC-ITEM）
- `(KF-2090-1-001, DOC-REQ-VENT-001)`: 呼吸机设备型号与第三方绑定接口协议。
- `(KF-2090-1-001, DOC-REQ-VENT-002)`: 呼吸机数据转发记录与结果快照回调。

### 2.2 影响分析结论
- **直接影响**：第 6 章「6.5.1 呼吸机第三方转发」正文及接口序列图。
- **传递影响**：第 3 章「3.7.28 第三方绑定关系」由于共用设备鉴权模型需同步复核。
- **待复核关系 (Pending Reviews)**：1 项（详见关系矩阵签审状态）。

---

## 3. 多仓库 Git 代码提交证据

由 `collect-git-evidence.ps1` 收集的 multi-repo 差异元数据：

### 3.1 仓位 `hcp` (后端服务)
- **HEAD 提交**：`c4a8d103f7e2`（分支：`feat/ventilator-forward`）
- **Base 提交**：`9f12b84a3201`
- **Diff 统计**：`5 files changed, 234 insertions(+), 38 deletions(-)`
- **修改文件**：
  - `service-device/src/main/java/com/konsung/device/ventilator/VentilatorForwardService.java`
  - `service-device/src/main/java/com/konsung/device/controller/VentilatorController.java`
  - `service-device/src/test/java/com/konsung/device/ventilator/VentilatorForwardTest.java`

### 3.2 仓位 `hcp-boot-ui` (前端界面)
- **HEAD 提交**：`8b3c5a1290fe`（分支：`feat/ventilator-ui`）
- **Base 提交**：`1e09df8821ab`
- **Diff 统计**：`3 files changed, 112 insertions(+), 14 deletions(-)`
- **修改文件**：
  - `src/views/device/ventilator/forward-config.vue`
  - `src/api/device/ventilator.js`

### 3.3 工作树洁净度检查
- `hcp`: 干净（Clean，0 脏文件）。
- `hcp-boot-ui`: 干净（Clean，0 脏文件）。

---

## 4. 自动化测试与人工验收证据

### 4.1 JUnit 自动化测试执行结果
- **测试报告来源**：`hcp/target/surefire-reports/TEST-VentilatorForwardTest.xml`
- **用例总数**：18
- **执行通过 (Passed)**：17
- **失败 / 错误 (Failures / Errors)**：0
- **跳过 (Skipped)**：1（`testWordTOCFieldRefreshCOM`：缺少 Office COM 组件跳过）
- **门禁策略判定**：
  > ⚠️ **`skipped != passed` 触发**：跳过项不作为通过证据，在交付清单中显式标记为未完备项。

### 4.2 业务人工验收证据（实机操作）
| 验收项 | 验收人 / 角色 | 状态 | 验证依据与产物 |
| :--- | :--- | :--- | :--- |
| 第三方数据转发推送回调 | 梁工 (测试工程师) | `passed` | 联调回调成功日志 `analysis/mock_callback.log`（HTTP 200，SHA256: `a93f...`） |
| 设备维度转发结果快照刷新 | 梁工 (测试工程师) | `passed` | 前端页面截屏与快照数据确认单 `evidence/snapshot_verify.png` |

---

## 5. 审查确认清单（Reviewer Sign-off Checklist）

- [ ] **基线核验**：确认需求说明书版本为 3.8 还是 3.10，更新 README 或项目清单使其单点闭环。
- [ ] **接口影响**：确认 KSOA 3.7.28 第三方绑定关系是否与新转发规则兼容。
- [ ] **跳过用例**：确认跳过的 Word 域刷新测试是否必须在部署前于有 Word 环境执行。
- [ ] **免安装 CLI 验签**：确认本次生成本报告的 `doc-tool-cli.exe` 来源于固化构建 `3.0.0`。
