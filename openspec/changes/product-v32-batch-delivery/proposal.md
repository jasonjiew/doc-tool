## Why

多文档和产品变体增多后，逐个点生成、等待 Word、手工整理产物成为新的耗时点。V3.2 让负责人提交一组任务，先得到可用出稿包，再在有 Word 的环境对固定快照补刷新和正式登记。

## What Changes

- 增加本地持久任务队列，支持项目/工作区/变体批量生成、逐项状态、失败项重试、取消和中断后继续。
- 复用已有管线、TaskRunner、集合与状态文件；Word 操作串行，默认不额外部署后台服务。
- 增加可携带的待刷新交付包，固定正文/模板/模块/资源快照；另一台有 Word 的机器可完成刷新/检查/登记，无需读取原电脑路径或改动当前项目。
- 增加结果索引、选择归档和 CLI 批次/交付包操作，提供与实际 help 对齐的流水线示例。
- 默认个别失败仍输出其他成果；无 Word、PDF 不可用或格式降级只影响对应阶段。严格交付显式选择，原可读包保持可用。

## Capabilities

### New Capabilities

- `durable-delivery-jobs`: 批量任务、持久状态、部分重试和进度。
- `portable-refresh-package`: 固定输入交付包、跨机器刷新及幂等登记。
- `delivery-automation-interface`: 结果索引、批次 CLI 与流水线报告。

### Modified Capabilities

无。正式成功仍沿用 Word 刷新/后校验事实，新增持久队列和交付包包装现有流程。

## Impact

- 涉及 `pipeline.py`、`collection.py/collection_ops.py`、`domain/output_state.py`、`ui/task_bridge.py/task_dock.py`、CLI 与导出服务。
- 用户级保存队列，包有独立 schema 1；项目 schema 不升级，诊断/待刷新/部分/正式状态统一适配。
- 直接前置为 V2.7 管线报告、V2.9 固定快照/集合与 V3.0 变体解析；命令入口复用 V3.1 的渐进注册。
- 首版是用户主动提交和继续的本地队列；服务器调度、共享 Word 服务、自动发布远端均另行规划。
