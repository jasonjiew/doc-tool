# 公共发布决策项登记

> 任务 1.2：将公共显示名、程序标识、组织设置键、图标、域名、著作权主体和
> 许可证列为发布决策项。**未知项保持显式阻断（UNRESOLVED），不填入猜测值。**
>
> 状态约定：
> - `WORKING`：本计划按此占位值实现（集中定义，后续可一次性更名）；
> - `UNRESOLVED`：未定，正式公开前必须由权利人/法务/品牌确认，CI 不得放行正式 Release；
> - `DECIDED`：已书面确认（本文件尚无 DECIDED 项，确认后由责任人填写日期与依据）。

## 决策项清单

| 决策项 | 占位值 / 状态 | 责任人 | 状态 | 备注 |
| --- | --- | --- | --- | --- |
| 公共显示名 | `Doc Tool` | — | WORKING | 首版实现用名；最终名称需商标检索与授权 |
| 程序标识 / 可执行文件 | `DocTool` / `DocTool.exe` | — | WORKING | 同上 |
| CLI 名 | `doc-tool` | — | WORKING | |
| 组织设置键（QSettings org） | `DocToolProject` | — | WORKING | 最终名称确定前可调整一次 |
| 安装目录段 | `DocTool`（`%LOCALAPPDATA%\DocTool` 或类似） | — | WORKING | 与内部版 `Konsung\DocTool` 隔离 |
| 安装器稳定 AppId | 需为新公共产品生成（不复用 `F6D0000F-...`） | — | UNRESOLVED | 需确定 UUID 命名依据与责任人 |
| 图标 | 需中性图标 | — | UNRESOLVED | 需授权，且不得含公司元素 |
| 公共域名 / 仓库地址 | — | — | UNRESOLVED | 未定 |
| 著作权主体 | — | — | UNRESOLVED | 公司或个人的书面决定 |
| 主许可证 | — | — | UNRESOLVED | Apache-2.0 / MIT / MulanPSL-2.0 等，需权利人选择 |
| 安全/维护联系邮箱 | — | — | UNRESOLVED | 需真实可联系渠道 |

## 发布阻断规则

- 任一 `UNRESOLVED` 决策项在发布时仍未决 → 公共 Release 门禁必须失败。
- `WORKING` 值可随最终决策一次性更名；集中元数据模块是唯一变更点。
- 正式宣称开源（README 移除「准备中」状态、发布稳定版本）前，著作权、
  品牌、许可证三项必须为 `DECIDED` 并记录审批依据。

## 变更历史

- 2026-08-13：建立登记表；按 design.md 决策 3 填入 WORKING 占位值；未知项保持 UNRESOLVED。
