## Why

现有检查已能读取活缓冲并应用可撤销修复，但120章端到端热路径实测仅约1.16倍提升，索引与检查成本需要更准确拆分。负责人还需要按规则、章节和变化集中处理问题，减少反复扫描及无效修正。

## What Changes

- 同机测量发现文件、摘要/读取、索引、规则检查、结果渲染与释放，不预设唯一瓶颈。
- 基于真实文本/规则/依赖指纹复用索引和可缓存检查结果，跨章规则有明确失效范围，未知依赖完整扫描兜底。
- 问题按章节/规则/本轮变化组织，明确检查范围及是否过期；普通warning保持非阻塞。
- 规则支持已实现字段编辑与选章试跑，确定性建议给差异、选中应用和撤销，旧建议需重新核对。
- 对50/300/1000章至少五次采样和完整结果对照，五批20项。

## Capabilities

### New Capabilities
- `incremental-quality-evaluation`: 真实依赖、缓存失效、范围和完整扫描一致性。
- `quality-workbench-actions`: 问题分组、规则试跑、建议差异及连续修正。

### Modified Capabilities
无。增强原检查工作流，保持规则、来源、身份及问题严重级别含义。

## Impact

涉及ContentIndexService/ChapterCache、ContentLinter/QualityRulesConfig、问题/检查面板、quick fix与请求代次。复用V3.6/MAIN缓存和缓冲服务，不建立第二套检查引擎；不依赖模型，不通过隐藏问题实现提速。
