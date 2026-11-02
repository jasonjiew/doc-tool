# 表格结构与列对齐验收夹具

## 1. 包含转义竖线的表格

| 列一（标题） | 列二（转义竖线） | 列三（备注） |
| :--- | :--- | :--- |
| 普通文本 | 单元格内含 \| 转义竖线字符 | 应当只有三列，不能多出第四列 |
| 另一个条目 | 代码内竖线 `a \| b` | 正确转义不拆列 |

## 2. 三种列对齐

| 左对齐列 | 居中对齐列 | 右对齐列 |
| :--- | :---: | ---: |
| Left text | Centered text | 123.45 |
| L2 | C2 | 678.90 |
| L3 | C3 | 1000.00 |

## 3. 宽表横向阅读

| 字段A | 字段B (详细描述一) | 字段C (详细描述二) | 字段D (技术指标一) | 字段E (技术指标二) | 字段F (关联服务名称) | 字段G (状态码) | 字段H (执行时间) | 字段I (安全等级) | 字段J (备注信息) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| row-01 | Alpha service node description text | Data pipeline stream config | 99.95% availability | Latency <= 20ms | Auth Gateway Microservice | 200 OK | 2026-10-31 12:00:00 | Level 3 Confidential | No special remarks |
| row-02 | Beta worker task runner node | Batch compute cluster partition | 99.99% availability | Latency <= 5ms | Document Rendering Engine | 200 OK | 2026-10-31 12:00:01 | Level 2 Internal | Needs fast cache |

## 4. 长表格与后续正文完整性

| 序号 | 标识符 | 描述 | 状态 |
| --- | --- | --- | --- |
| 1 | item-001 | 基础配置单元 | 启用 |
| 2 | item-002 | 网络路由单元 | 启用 |
| 3 | item-003 | 身份鉴权网关 | 启用 |
| 4 | item-004 | 异步任务调度 | 启用 |
| 5 | item-005 | 日志采集管道 | 启用 |
| 6 | item-006 | 监控告警指标 | 启用 |
| 7 | item-007 | 数据库持久层 | 启用 |
| 8 | item-008 | 缓存加速层 | 启用 |
| 9 | item-009 | 离线分析任务 | 启用 |
| 10 | item-010 | 报表生成器 | 启用 |
| 11 | item-011 | 邮件通知服务 | 启用 |
| 12 | item-012 | 消息总线接收 | 启用 |
| 13 | item-013 | 文档转换引擎 | 启用 |
| 14 | item-014 | 静态资源代理 | 启用 |
| 15 | item-015 | 备份容灾控制器 | 启用 |

这是长表格之后的独立正文段落。长表格渲染之后，此段正文不能被截断，文字必须完整显示并可阅读。
