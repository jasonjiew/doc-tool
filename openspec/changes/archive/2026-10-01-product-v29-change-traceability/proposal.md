## Why

企业的一次研发交付通常包含需求、设计和测试多份文档，而当前项目以单份文档为单位；追踪服务依赖章节编号，重排和跨文档同号会造成关联不稳定。团队需要稳定条目关系、可解释的变更影响及同一研发版本下的完整交付基线。

## What Changes

- 新增研发文档工作区，将独立文档项目按需求/设计/测试角色关联；单项目仍可独立使用。
- 引入稳定条目 ID 与显式多对多关系，支持人工关联、校验和可预览的旧编号迁移。
- 提供需求—设计—测试矩阵、未关联清单、变更影响队列与复核记录，GUI/CLI/导出一致。
- 关联的上游内容变更后将下游置为待复核；影响结果展示关系路径和依据，不自动修改下游正文。
- 冻结集合输入快照并保留可用成员成果；个别失败输出部分集合/缺失清单，完整基线另以事务登记，默认不把整次工作撤掉。
- 提供基线查询、比较、导出与完整/部分恢复为新副本，历史只读；遵循 `docs/product-flow-fallback-policy.md`，严格集合交付由用户显式选择。

## Capabilities

### New Capabilities

- `document-workspace`: 多文档工作区、路径/版本兼容、角色和项目聚合。
- `stable-traceability`: 稳定 ID、显式关系、矩阵、变更影响与复核。
- `workspace-release-baseline`: 不可变版本集合、完整快照、查询对照与安全恢复。

### Modified Capabilities

无。复用现有追踪/基线/历史服务并替换其不稳定识别策略，不把尚未归档的旧提案当作已存在主规范。

## Impact

- 涉及 `application/content/{traceability,baselines,history,index,refactor}.py`、评审与发布服务、工作区 UI、CLI 和项目迁移。
- 新增 `workspace.yml`（独立 schema 1）、文档内条目标记、版本控制中的关系文件和发布集合记录。
- 前置：`product-v28-team-standardization`；AI、共享章节/产品变体、远程正式化、完整 ALM 和实时协作仍为后续候选。
