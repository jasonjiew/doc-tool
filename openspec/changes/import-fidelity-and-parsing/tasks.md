## 1. 统一安全 OOXML 解析（服务层，先测）

- [x] 1.1 新增 `doc_tool/domain/ooxml.py`：`PARSE_LIMITS` 常量（条目 20000 / 展开 512MB / 单条目 256MB / XML 部件 64MB / 压缩比 2000）、`OOXMLSecurityError`、`parse_xml_safe(data, part_name)`（DTD/实体声明拒绝 + 禁用实体/网络/DTD/超大树 + doctype 复查）、`read_docx_package(path)`（扩展名 + ZIP 完整性 + CRC + 上限 + 按需读部件）
- [x] 1.2 `scripts/docx_common.py` 增加单次 sys.path 引导并转发 `parse_xml_safe`/`read_docx_package`/`OOXMLSecurityError`（薄适配，不改既有函数）
- [x] 1.3 `scripts/build_docx.py`：`_validate_zip_xml`、模板包读取、复杂表格 `_expected_table_xml` 改走共享入口，行为等价
- [x] 1.4 `scripts/validate_docx.py`：`DocxPackage` 的 ZIP/XML 读取改走共享入口，保留既有错误消息
- [x] 1.5 `doc_tool/adapters/preflight.py`：删除本地 `_parse_xml`/`_check_zip_limits`/`_check_encryption` 重复实现，改调统一入口并映射错误类型，`ImportPreview` 字段不变
- [x] 1.6 `doc_tool/adapters/importer.py`：`generate_template`/`extract_content` 的包读取与 XML 解析改走统一入口
- [x] 1.7 `doc_tool/adapters/kernel.py` `_effective_heading_styles` 与 `import_project._verify_valid_docx` 复用 `read_docx_package`/`parse_xml_safe`

## 2. 保真扫描与往返差异门禁

- [x] 2.1 新增 `doc_tool/adapters/fidelity.py`：`scan_fidelity(parts) -> FidelityReport`，统一树遍历识别超链接(WARN)/书签(WARN)/批注(BLOCK)/修订(BLOCK)/脚注·尾注(BLOCK)/公式(BLOCK)/图表(BLOCK)/文本框(BLOCK)/OLE(BLOCK)/内容控件(WARN)/域(INFO)，输出计数与位置采样
- [x] 2.2 `preflight` 集成 `scan_fidelity`，`ImportPreview` 增加 `fidelity` 报告；向导预检页渲染分级报告
- [x] 2.3 向导：存在 BLOCK 特性且未确认时禁用「下一步」，提供「仍然导入」确认入口
- [x] 2.4 新增 `doc_tool/adapters/roundtrip.py`：`roundtrip_diff(source_docx, rebuilt_docx) -> RoundtripReport`，复用 `validate_docx.body_events`/`compare_baseline_events`，关键损失判定（元素数量不一致/P 段落丢失/H 层级变化/I 图片缺失为 BLOCK，纯表示差异为 WARN）
- [x] 2.5 `import_project` 新增 `STAGE_ROUNDTRIP_CHECK`：`trial_build` 后、`publish` 前执行；BLOCK 差异 → 清理暂存 + 写诊断日志 + 返回失败；仅 WARN → 默认放行
- [x] 2.6 `ImportRequest` 增加 `require_exact_roundtrip: bool = False`；向导「导入确认」页提供开关，开启时非关键差异也阻止
- [x] 2.7 保真报告与往返差异摘要写入成功项目 `logs/`；失败诊断日志含保真扫描摘要

## 3. 导入样式映射向导

- [x] 3.1 `preflight` 新增 `census_paragraph_styles(parts)`：样式→(显示名, 正文使用次数, 疑似标题标记)；`ImportPreview` 携带样式清单
- [x] 3.2 `importer.generate_template`/`extract_content` 新增可选 `heading_style_map: Optional[Dict[str,int]]` 覆盖参数，传入时不自行解析；`_build_heading_tree`/`_validate_heading_hierarchy` 按映射工作
- [x] 3.3 向导新增「样式映射」页（预检页与项目信息页之间）：候选样式表格 + 级别下拉（1~6/忽略）+ 使用次数；映射后即时校验 H1 存在且层级无跳跃，错误定位到样式
- [x] 3.4 `ImportRequest` 携带样式映射；`_build_manifest` 按映射写 `project.yml` 的 `headingStyles`（级别→styleId）
- [x] 3.5 构建/校验经 `config_from_project` 自动使用映射（无需额外接线，回归确认）
- [x] 3.6 映射持久化回读：重新导入/打开项目时以既有 `headingStyles` 为默认映射，可修改

## 4. 自动化测试

- [x] 4.1 `ooxml.py` 单测：DTD/实体拒绝、条目/体积/压缩比超限拒绝、CRC 失败、良构失败、错误映射
- [x] 4.2 回归：`test_docx_common`/`test_validator_negative`/`test_project_build`/`test_import_preflight`/`test_import_project` 全绿（解析结果逐字节等价）
- [x] 4.3 `fidelity.py` 单测：各特性正反例计数与分级（含跨行 `w:ins`、外部链接图片等边界）
- [x] 4.4 `roundtrip.py` 单测：一致通过、段落/标题/图片缺失为 BLOCK、表示性差异为 WARN、试构建失败映射
- [x] 4.5 `import_project` 集成测试：BLOCK 差异阻止发布且暂存清理、仅 WARN 放行、`require_exact_roundtrip` 开关、诊断日志含扫描摘要
- [x] 4.6 样式映射测试：映射驱动导入/构建/校验一致、同一样式单级别、缺 H1/层级跳跃拒绝、持久化回读与修改

## 5. 人工验收与文档

- [ ] 5.1 手工验收：含批注/修订的源文档导入默认被阻断、确认后放行；往返一致与含差异文档的导入结果
- [ ] 5.2 手工验收：非标准 Heading 文档走样式映射向导导入，Word 打开标题层级正确，构建/校验通过
- [ ] 5.3 手工验收：统一入口改造后既有需求/详细设计文档导入→构建→校验→Word 刷新全链路无回归
- [x] 5.4 更新 `docs/roadmap.md` 标注「P0-3 导入保真度门禁」「P0-4 统一安全 OOXML/XML 解析」「P1-N 导入样式映射向导」对应本变更
