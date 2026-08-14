# 公共发布决策项登记

> 任务 1.2：将公共显示名、程序标识、组织设置键、图标、域名、著作权主体和
> 许可证列为发布决策项。**未知项保持显式阻断（UNRESOLVED），不填入猜测值。**
>
> 状态约定：
> - `WORKING`：本计划按此占位值实现（集中定义，后续可一次性更名）；
> - `UNRESOLVED`：未定，正式公开前必须由权利人/法务/品牌确认，CI 不得放行正式 Release；
> - `DECIDED`：已书面确认（由责任人填写日期与依据，见变更历史）。

## 决策项清单

| 决策项 | 占位值 / 状态 | 责任人 | 状态 | 备注 |
| --- | --- | --- | --- | --- |
| 公共显示名 | `Doc Tool` | — | WORKING | 首版实现用名；最终名称需商标检索与授权 |
| 程序标识 / 可执行文件 | `DocTool` / `DocTool.exe` | — | WORKING | 同上 |
| CLI 名 | `doc-tool` | — | WORKING | |
| 组织设置键（QSettings org） | `DocToolProject` | — | WORKING | 最终名称确定前可调整一次 |
| 安装目录段 | `DocTool`（`%LOCALAPPDATA%\DocTool` 或类似） | — | WORKING | 与内部版 `Konsung\DocTool` 隔离 |
| 安装器稳定 AppId | `8C61369A-D7C7-51D4-BD14-5B555EF93E52`（公共专用 UUID5） | wangjie | DECIDED | 2026-08-14 采用 installer.iss 已实现的公共专用 UUID5，不复用内部版；依据=packaging/installer.iss 任务 8.5/2.4 |
| 图标 | 中性图标（`packaging/app.ico` / `doc_tool/resources/app.ico`） | wangjie | DECIDED | 2026-08-14 采用 scripts/make_icon.py 生成的中性图标，无公司元素，权利人授权 |
| 公共域名 / 仓库地址 | 内部 GitLab 托管；本期不宣称公共域名 | wangjie | DECIDED | 2026-08-14 决策：本期发布托管于内部 GitLab（基线见 01-baseline-internal.md）；正式公共 URL 确定后更新 branding.PUBLIC_URL 并复签 |
| 著作权主体 | `Doc Tool Project`（中性公共发布主体；作者 wangjie 受托确认） | wangjie | DECIDED | 2026-08-14 权利人委托确认；正式公司/个人主体名称确定后一次性更名并同步 LICENSE 与检查单 |
| 主许可证 | MIT（OSI 批准） | wangjie | DECIDED | 2026-08-14 权利人选择 MIT；`LICENSE` 全文已加入；与依赖许可（PySide6 LGPL-3.0、lxml BSD、PyYAML MIT、Pillow MIT-CMU、pywin32 PSF）兼容 |
| 安全/维护联系邮箱 | `wangjie@konsung.com` | wangjie | DECIDED | 2026-08-14 维护者真实邮箱；SECURITY.md 私密报告渠道已同步 |

## 发布阻断规则

- 任一 `UNRESOLVED` 决策项在发布时仍未决 → 公共 Release 门禁必须失败。
- `WORKING` 值可随最终决策一次性更名；集中元数据模块是唯一变更点。
- 正式宣称开源（README 移除「准备中」状态、发布稳定版本）前，著作权、
  品牌、许可证三项必须为 `DECIDED` 并记录审批依据。

## 变更历史

- 2026-08-13：建立登记表；按 design.md 决策 3 填入 WORKING 占位值；未知项保持 UNRESOLVED。
- 2026-08-14：权利人（wangjie）委托确认，6 项未决项全部转为 DECIDED；新增 LICENSE（MIT），
  SECURITY.md 更新私密报告邮箱；公共发布门禁放行。
