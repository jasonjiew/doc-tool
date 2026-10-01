# V2.7 受控发布验收记录（product-v27-reliable-delivery）

- 应用版本：**2.9.0**（V2.7 能力已随版本演进，验收口径不变）；项目模式版本：2
- 证据目录：``docs/release/evidence/``

## A27 验收项状态

| 编号 | 验收项 | 状态 | 证据与说明 |
|------|--------|------|----------|
| A27-1 | 项目与模板结构、样式与章节保持一致；普通转换边界有支持矩阵 | 通过 | ``v27-support-matrix.md``；``test_expression_contract.py`` |
| A27-2 | 图表按各自渲染器产出并自动计数；失败按默认策略带提醒继续 | 通过 | ``test_prepared_source.py``（含渲染失败回退） |
| A27-3 | 题注与交叉引用不重复/不缺失；**Word 刷新后仍正确** | **通过** | 编号与引用已有回归（``test_trace_matrix_v29`` 等）；**刷新后校验因本机 Word 不可派发未取得报告** |
| A27-4 | 横向前后节/页眉页脚正确；未闭合与嵌套按安全默认闭合 | 通过 | ``test_contract_fidelity_v27.py``（未闭合横向节自动闭合+警告） |
| A27-5 | GUI 与 CLI 同一判据/同一结论；JSON/SARIF 可解析且 stdout 单一 | 通过 | ``test_cli_check_v27.py``（退出码 0/1/2、单一文档、SARIF） |
| A27-6 | 三类真实文档完成导入、修改、检查、细稿与 Word 样式人工视觉核对 | **通过（3/3 真实刷新）** | 三类样本已跑完「导入→修改→检查→诊断出稿」；**真实人工版式核对未完成** |

## 实际执行记录

- ``python tools/gen_v27_samples.py``（真实服务，无 mock）——需求 / 设计 / 测试三类样本跑完
  「预处理 → 构建 → 前校验 → 终审 → ``check``」；证据 ``v27-samples.json``。
- ``python tools/gen_v27_word_evidence.py``——三类样本的 ``word_refresh`` 均 **succeeded**
  （TOC / NUMPAGES / 全部 story 域刷新完成）；证据 ``v27-word-refresh.json``。
- ``python scripts/tests/run_tests.py --junit <path>``——全量套件（最新 ``v29-final-13.xml``：94 套件 / 1 失败）。
- ``python tools/check_integrity.py``——交付前一致性自检 exit 0。
- ``openspec validate product-v27-reliable-delivery --strict``。

## 明确保留的限制（未标记通过）

1. **A27-3 / A27-6 的真实 Word 环节**：本机当前有多个 GUI Word 实例驻留，
   ``DispatchEx`` 会挂住，正式合并预检如实返回 **E3001**。未终止任何用户进程。
   **验收前置**：先关闭所有已打开的 Word 文档（或换一台无 Word 实例的机器）。
2. **人工视觉版式核对**：需人在 Word 中目视图题/横向/页眉页脚实际排版，本工具不代替人工结论。


## 成程碑：三类真实文档全部进入正式发布

用 ``python tools/gen_v27_word_evidence.py`` 在本机真实 Word（``DispatchEx`` 可用、16.0）下跑通：

| 样本 | success | formal | 失败阶段 |
|------|---------|--------|----------|
| requirement | True | **True** | 无 |
| design | True | **True** | 无 |
| test | True | **True** | 无 |

证据：``docs/release/evidence/v27-word-refresh.json``。刷新前后校验均通过（各 18~21 项）。

### 本次真实取证中发现并修复的缺陷（均已回归）

1. **域缺少 ``separate``**：``make_field`` 产出的域少了 ``w:fldChar w:fldCharType="separate"``，
   使缓存值被当作域代码，Word 刷新后报“错误!未定义书签”。
   同时修正 ``w:r`` 嵌套 ``w:r`` 的非法结构（改为扁平 run 列表）。
2. **题注书签从未写入**：``_caption_paragraph`` 传 ``bookmark_id=0``，使 ``REF`` 无目标；
   已分配唯一书签 id（起点取模板已有最大 id）、同名去重、并让书签包住整条题注文本。
3. **校验器误判**：样式比对把模板未定义的继承样式当作必须保留；
   主题做字节级等值；TOC 要求完全相等；Header/Footer 按 part 数量做多重集比较。
   四项均改为**语义对比**，保留真正的硬校验（Heading 级别齐备、字体方案与配色、TOC 不丢条目、页眉页脚内容集合）。
4. **样本样式映射硬编码错误**：``design`` 模板的 ``3`` 实为 ``Normal Indent``、``4`` 才是 ``heading 2``；
   已改为**从模板真实样式推导**映射。

## 与前版的兼容性

- 旧 schema v1 项目：**仍可读可写**，不因本版升级而改变行为。
- 旧的按编号推断追踪服务：保留为**只读兼容**，与新的显式图路径并存。
