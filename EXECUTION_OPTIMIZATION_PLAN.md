# doc-tool 核心主航道（GUI + 内核 + CLI）全量重构与交互收敛 —— AI 全量自动执行手册

> **【致当前读取本文件的 AI 智能体（强制执行契约）】**：
> 当用户要求你读取并执行本文件时，你必须进入 **全量连续自动执行模式（Full Autonomous Execution）**：
> 1. **禁止只汇报计划或中途停顿询问**：你必须从 `Task 1.1` 开始，按阶段一（P0）→ 阶段二（P1）→ 阶段三（P1）→ 阶段四（P2）的顺序，连续完成全部 **15 个子任务（`Task 1.1` ~ `Task 4.2`，含 GUI、内核管线与 CLI 全链路）** 的代码修改与测试验证；
> 2. **保护现有未提交代码**：全程在 `D:\ai_develop_project_space\ai-dev-hub\doc-tool` 下增量修改，**严禁执行 `git reset` / `git checkout` / `git restore` / `git clean`**；
> 3. **逐项验证并勾选进度**：每完成一个 Task，立即运行该 Task 下的 `pytest` 验证命令，通过后将本文件中的 `- [ ] Task X.Y` 更新为 `- [x] Task X.Y`；
> 4. **全量竣工门禁**：全部 15 个子任务完成后，必须运行文末《四、全量竣工总验收命令（Final Gate）》，确认全量测试 100% 通过后再向用户输出最终交付报告。

---

## 一、 AI 全量执行环境与红线约束（开工前必读）

### 1.1 终端透明加密环境（DocGuard / 亿赛通）读写规约
- 当前宿主机启用了企业终端透明加密策略：
  - `.md`、`.json`、`.yml` 文件在磁盘上为明文，宿主的 `read_file` / `write_file` / `edit_file` 工具可直接读写。
  - **`.py` 与 `.txt` 文件受透明加密保护**：非授信宿主直接调用 `read_file` 读取 `.py` 时可能报错 `appears to be a binary file (application/octet-stream)`。
  - **标准解决方案**：读取、检索或批量修改 `.py` 文件，以及运行测试时，统一通过 `run_command` 调用授信进程 `powershell.exe` / `python.exe`，并强制指定 UTF-8 编码：
    ```powershell
    $env:PYTHONIOENCODING = "utf-8"
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    ```
  - 写回 `.py` 文件时，使用 Python `pathlib.Path(path).write_text(content, encoding="utf-8", newline="\n")`，确保 **UTF-8 无 BOM + LF 换行符**。

### 1.2 现有工作区未提交改动保护（严禁覆盖或回退）
- 当前 `doc-tool` 工作区已有上一轮完成的未提交改动（相关 59 项单测已通过），**已落地的修复包括**：
  1. `doc_tool/ui/main_window.py`、`doc_tool/ui/export_settings_dialog.py`、`doc_tool/application/export/document_properties.py`：已接入导出设置弹窗、「文件编号/文件名称/版本」及自定义属性编辑，并新增 `read_template_reserved_properties` 从模板回填编号与名称；
  2. `scripts/docx_common.py`、`scripts/build_docx.py`、`scripts/validate_docx.py`、`doc_tool/application/pipeline.py`：已新增 `cleanup_element_bookmarks` 清理内部/重复书签、正式刷新前 `synthesize_static_fields=False` 避免合成目录误删书签、`remap_template_styles` 按样式名称重映射标题样式。
- **审查该批改动后仍需继续修复的漏网 Bug 与待完成项**：
  1. **`general` 项目修改「文件编号/文件名称/版本」后正文与页眉缓存未更新，且同义属性名未同步**：`document_properties.py` 将 `RESERVED = {"文档编号", "文件编号", "文件名称", "文档名称", "版本", "版本号"}` 排除在 `request.document_properties` 之外，而 `build_docx.py:3092` 仅对 `requirement/design` 调用 `update_cover` / `update_headers`，导致 `general` 项目封面与页眉中的 `DOCPROPERTY` 缓存文本不更新；且 `build_docx.py:1826` 的 `update_custom_properties` 只写死更新 `{"文档编号", "版本", "文件名称"}`，若模板 `custom.xml` 用的是同义词 `"文件编号"` / `"文档名称"` / `"版本号"` 则原属性仍保留旧值！
  2. **页眉纯文本版本号在刷新后校验（`STAGE_VALIDATE_POST`）仍未归一化，且失败即删文件**：`validate_docx.py:1283` 的 `_header_footer_signatures` 仍未调用 `_normalize_header_fields(root, config)`；`pipeline.py:1439` 在 `not post_ok` 时仍直接 `_cleanup_temp()` 删除已刷新的 `.docx`。
  3. **工作区 `scripts/validate_docx.py` 混入了 CRLF 换行符**：需统一规整为 LF。
- **红线要求**：
  - **严禁运行 `git reset`、`git checkout --`、`git restore`、`git clean`**。
  - 所有修改必须在当前工作区文件最新版本之上增量演进。

### 1.3 核心主航道收敛原则
一切改造服务于唯一核心主航道：
**「导入拆解 Word (`.docx`) → 编辑 Markdown（章节 / 复杂表格 / 修订记录 / 图片） → 一键正式还原为生产级 Word (`.docx`)」**
1. **绝不丢失用户产物**：Word 刷新耗时数十秒后，即便刷新后校验（`STAGE_VALIDATE_POST`）发现非致命差异，也必须保留刷新后的 `.docx` 产物供用户使用，严禁直接 `_cleanup_temp()` 删掉。
2. **绝不因局部表格/标题格式瑕疵炸毁整篇构建**：复杂表格代理修改、章节序号不连续、内联标题层级偏差全部实现自动适配或优雅降级并告警，不再动辄抛裸异常中断构建。
3. **单一出稿主入口与单一结果面板**：终结「导出 Word」「快速构建」「正式出稿」三套入口各自为政、两套结果页（`ExportResultsView` vs `ResultCard`）来回切换的混乱局面。

---

## 二、 全局问题根因矩阵与任务映射表

| 问题编号 | 核心痛点 | 根因所在文件与精确行号 | 对应执行任务 |
| :--- | :--- | :--- | :--- |
| **B-01** | 「导出 Word」与「正式出稿」双轨割裂：点 `导出 Word` 默认不刷目录页码、不同步修订表版本；点 `正式出稿` 忽略编辑器未保存修改 | `doc_tool/ui/main_window.py:3148, 3348, 4670, 4826`<br>`doc_tool/application/project_export.py:390, 811`<br>`doc_tool/application/pipeline.py:921` | **Task 1.1**<br>**Task 1.2** |
| **B-02** | `STAGE_VALIDATE_POST` 失败时直接删除已由 Word 刷新好的 `.docx`；且刷新后校验将 22 项检查全部当成 100% 硬阻断，并覆写刷新前校验报告 | `doc_tool/application/pipeline.py:1138, 1390-1452`<br>`scripts/validate_docx.py:1558-1745` | **Task 1.3** |
| **B-03** | 刷新后页眉签名比对 `_header_footer_signatures` 漏调 `_normalize_header_fields`，导致页眉含纯文本版本号/文档编号时刷新后必挂 | `scripts/validate_docx.py:982, 1283-1343, 1442-1449` | **Task 1.3** |
| **B-04** | 新项目被强制锁死为 `documentType="general"`，而 `build_docx.py` 仅对 `requirement/design` 调用 `update_cover` 与 `update_headers`；且 `update_cover` 找不到严格 3 字段就抛异常崩溃 | `doc_tool/domain/manifest.py:57`<br>`doc_tool/application/import_project.py:242`<br>`scripts/build_docx.py:1942-2075, 3092-3095` | **Task 1.4** |
| **B-05** | 复杂表格代理（`COMPLEX_TABLE_PROXY`）合并续格显示为空白格 `\|  \|`，用户误填字或增删行即抛未捕获英文 `ValueError` 炸毁构建 | `doc_tool/domain/smart_features.py:448-578`<br>`scripts/build_docx.py:2772-2776`<br>`scripts/validate_docx.py:638-645` | **Task 2.1** |
| **B-06** | `retain_pre_title_body=True` 时，`extract_content` 提取了 `01-前言.md`，但 `generate_template` 未从 `template.docx` 删除该段引言，还原后内容重复 | `doc_tool/adapters/importer.py:131-265, 476-482`<br>`doc_tool/application/import_project.py:345-372` | **Task 2.2** |
| **B-07** | 默认 `STRICT_MERGE_POLICY` 对非连续章节序号、二级章节内写 `##` 标题直接报错阻断；`content/` 下有非 `.md` 杂项文件即报错 | `scripts/docx_common.py:340-415, 575-605, 720-765`<br>`doc_tool/domain/merge_policy.py` | **Task 2.3** |
| **B-08** | 拆解后的 Markdown 充斥 `<!-- P:line=360;... -->` 默认段落注释，且注释与表格/段落之间多一个空行就丢失样式绑定 | `doc_tool/adapters/importer.py:961-1035`<br>`scripts/docx_common.py` | **Task 2.4** |
| **U-01** | 顶栏 `ProjectBar` 堆砌 6 个出稿/构建按钮（`导出 Word`、`导出设置…`、`成果`、`项目检查`、`快速构建`、`正式出稿`），用户无所适从 | `doc_tool/ui/project_bar.py:114-165`<br>`doc_tool/ui/main_window.py:341-351` | **Task 3.1** |
| **U-02** | 右侧 `TaskDock` 存在 `ExportResultsView` 与 `ResultCard` 两套割裂结果页，底部状态栏又重复放了 5 个 `_output_capsules_widget` 按钮 | `doc_tool/ui/task_dock.py:225-265`<br>`doc_tool/ui/main_window.py:380-398` | **Task 3.2** |
| **U-03** | 纵向 4 层顶栏（菜单+项目条+路径导航条+编辑器工具条）+ 底部工具面板 8 个 Tab 严重挤压编辑区高度 | `doc_tool/ui/main_window.py:402-465`<br>`doc_tool/ui/content/editor_panel.py:417-530`<br>`doc_tool/ui/content/workspace.py:335-385` | **Task 3.3** |
| **U-04** | 外围低频工具（PDF/互转/研发工作区/模块库）混入主航道，顶层菜单重复生成「命令」菜单，`main_window.py` 膨胀至 7,323 行 | `doc_tool/ui/main_window.py`<br>`doc_tool/ui/empty_state.py` | **Task 3.4**<br>**Task 4.1**<br>**Task 4.2** |
| **C-01** | **CLI `project-export` 缺失文档字段与自定义属性能力**：GUI 弹窗已支持设置文件编号/名称/版本与 `docProps` 属性，但 CLI `project-export` 完全没有 `--document-no`、`--document-name`、`--document-version`、`--property KEY=VALUE`、`--variant`、`--inspect-properties` 参数；且当 `project.yml` 编号为空时 CLI 不会从模板 `custom.xml` 自动回填编号 | `doc_tool/cli.py:245-309, 897-1000`<br>`doc_tool/application/project_export.py:299-335` | **Task 1.5** |
| **C-02** | **CLI `build` 能力残缺且无 JSON 机器输出**：`build` 仅支持 `--project` 和 `--skip-word-refresh`，不支持指定输出路径 `--output-file`、版本/属性覆盖、章节范围或 `--output json` | `doc_tool/cli.py:112-117, 1652-1684` | **Task 1.5** |
| **C-03** | **CLI `import` 拆解参数阉割且丢失源文档属性**：CLI `import` 不支持 `--retain-pre-title`、`--pre-title-title`、`--allow-missing-headings`、`--split-level`，且未在导入时自动从源 `.docx` 的 `docProps/custom.xml` 提取默认的文档编号/名称/版本 | `doc_tool/cli.py:124-141`<br>`doc_tool/application/cli_commands.py:124-225` | **Task 2.5** |
| **C-04** | **CLI 38+ 子命令平铺无主次，缺少 `export` / `decompose` 主航道直达别名**：用户或自动化脚本难以从 38 个子命令中快速定位「拆解 → 检查 → 还原导出」核心三步命令 | `doc_tool/cli.py:38-705` | **Task 3.5**<br>**Task 4.2** |

---

## 三、 全量分步实施细则（Task 1.1 ~ Task 4.2）

---

### 阶段一（P0）：导出管线合一与正式还原阻断修复（解决“老是出问题”）

#### - [x] Task 1.1：打通未保存缓冲区自动落盘、修订版本同步与顶栏导出设置接线测试

- **现状代码定位**：
  1. `doc_tool/ui/main_window.py:341-350`：`ProjectBar` 实例化（需固化 `on_export_settings=self._on_export_settings` 接线断言测试）。
  2. `doc_tool/ui/main_window.py:3148-3202`（`_on_merge`）与 `3348-3405`（`_on_diag_build`）：直接基于磁盘文件运行 `run_pipeline(summary.manifest, summary.paths)`，**未保存编辑器中的修改（`self._workspace.has_unsaved_changes()`）完全未写入磁盘**！
  3. `doc_tool/ui/main_window.py:4826-4856`（`_on_quick_export_word`）：当 `prompt_settings=False` 或从导出设置点击开始导出时，只把 `buffers` 传给临时快照，未把 `_revision_record.md` 的最新版本号回写到项目 `project.yml`。

- **具体代码修改方案**：
  1. **在 `doc_tool/ui/main_window.py` 中新增统一的出稿前自动保存与版本同步辅助方法 `_flush_unsaved_and_sync_version(self) -> None`**：
     ```python
     def _flush_unsaved_and_sync_version(self) -> None:
         """出稿/构建前统一将编辑器未保存缓冲区落盘，并同步 _revision_record.md 版本号到 manifest。"""
         try:
             if getattr(self, "_workspace", None) is not None and self._workspace.has_unsaved_changes():
                 self._workspace.save_all()
         except Exception as exc:  # noqa: BLE001
             logger.warning("auto save_all before export failed: %s", exc)
         summary = self._project_summary
         if summary is None:
             return
         rev_ver = self._revision_record_version()
         if rev_ver and rev_ver != getattr(summary.manifest, "documentVersion", ""):
             try:
                 summary.manifest.documentVersion = rev_ver
                 summary.manifest.save(summary.paths.root)
                 if getattr(self, "_project_bar", None) is not None:
                     self._project_bar.update_version(rev_ver)
             except Exception as exc:  # noqa: BLE001
                 logger.warning("sync revision version to manifest failed: %s", exc)
     ```
  2. **在 `_on_merge`（第 3152 行后）、`_on_diag_build`（第 3351 行后）、`_on_export_settings`（第 4765 行打开弹窗前）以及 `_on_quick_export_word`（第 4835 行前）统一调用 `self._flush_unsaved_and_sync_version()`**。
  3. **在 `doc_tool/application/project_export.py` 的 `run_project_export` 中**（约第 415 行快照构建前）：
     - 若快照内存在 `_revision_record.md`，调用 `document_version_from_record` 提取末行版本号，并在未显式指定 `request.document_version_override` 时自动作为当前导出版本号同步到快照 `manifest.documentVersion`，确保通过 `run_project_export` 导出的文件名、封面、页眉版本号与 `_revision_record.md` 100% 一致。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_ui2_export_settings.py doc-tool/scripts/tests/test_ui_polish_quick_export.py -q
  ```

---

#### - [x] Task 1.2：统一 `project_export` 与 `pipeline` 导出语义，主导出默认启用 Word 刷新并在无 Word 时平滑降级

- **现状代码定位**：
  1. `doc_tool/application/intake_contract.py` 中 `ExportRequest` 的 `refresh: bool = False`。
  2. `doc_tool/ui/main_window.py:4670-4693`（`_quick_export_defaults`）：
     ```python
     return ExportRequest(
         project_root=str(self._project_summary.project_root),
         formats=[FORMAT_DOCX],
         scope=ExportScope(kind=SCOPE_PROJECT),
         source_mode=SOURCE_MODE_CURRENT_BUFFER if buffers else SOURCE_MODE_SAVED,
         destination=str(self._project_summary.paths.output_dir),
     )
     ```
     由于 `ExportRequest.refresh` 默认是 `False`，`doc_tool/application/project_export.py:811` 执行 `skip_word_refresh = not bool(request.refresh)` 时，`skip_word_refresh` 恒为 `True`！导致用户使用主按钮「导出 Word」永远不刷新目录和页码。
  3. 反之，当 `request.refresh=True` 但本机 Word COM 不可用或刷新失败时，`project_export.py:820-875` 会直接把该轮次标记为失败或抛错，而不是自动降级保留待刷新可读稿。

- **具体代码修改方案**：
  1. **修改 `doc_tool/ui/main_window.py:4670` 的 `_quick_export_defaults`**：
     - 检测本机 Word 可用性（优先读取缓存的 `self._word_available`，若为 `None` 则轻量调用 `check_word_available(dispatch_check=False).available`），将 `refresh=bool(word_available)` 传入 `ExportRequest`（并在 `ExportSettingsDialog` 中当本机有 Word 时默认勾选「刷新 Word 目录与页码」）：
       ```python
       word_ok = getattr(self, "_word_available", None)
       if word_ok is None:
           try:
               from doc_tool.application.word_check import check_word_available
               word_ok = bool(check_word_available(dispatch_check=False).available)
               self._word_available = word_ok
           except Exception:
               word_ok = False
       return ExportRequest(
           project_root=str(self._project_summary.project_root),
           formats=[FORMAT_DOCX],
           scope=ExportScope(kind=SCOPE_PROJECT),
           source_mode=SOURCE_MODE_CURRENT_BUFFER if buffers else SOURCE_MODE_SAVED,
           destination=str(self._project_summary.paths.output_dir),
           refresh=bool(word_ok),
       )
       ```
  2. **修改 `doc_tool/application/project_export.py:805-890`（`_export_docx_via_pipeline`）实现智能降级保底**：
     - 当 `request.refresh=True`（即 `skip_word_refresh=False`）调用 `run_pipeline` 后：
       - 如果 `pipeline_result.success` 为 `True`：正常产出已刷新的正式 `.docx`（标记 `refreshed=True`）。
       - 如果 `pipeline_result.success` 为 `False`，但 `pipeline_result.output_path` 指向的 `.docx` 文件已经存在（例如由 `_preserve_pending_output()` 保留的待刷新稿或刷新后待确认稿），或者是因为本机无 Word / Word COM 刷新失败（`STAGE_WORD_REFRESH` / `STAGE_VALIDATE_POST` 失败而 `STAGE_BUILD` 已成功）：
         - **绝不丢弃产物**！将已构建好的 `.docx` 复制到目标导出路径 `target_docx`，将 `FormatExportResult` 标记为 `ok=True, refreshed=False`（并在 `warnings` / `notice` 中注明 `"已生成可用 Word 文档（本机 Word 刷新未完成或校验告警，打开后可按 Ctrl+A → F9 更新目录页码）"`）。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_export_round_recovery.py doc-tool/scripts/tests/test_ui_polish_quick_export.py -q
  ```

---

#### - [x] Task 1.3：修复 `STAGE_VALIDATE_POST` 删文件缺陷、页眉未归一化 Bug，并将 `validate_docx.py` 拆分为「硬阻断 / 软告警」两级

- **现状代码定位**：
  1. `doc_tool/application/pipeline.py:1390-1452`：
     - 第 `1138` 行 `STAGE_VALIDATE_PRE` 与第 `1393` 行 `STAGE_VALIDATE_POST` 都调用 `validate_with_project`，寫入同一个报告路径 `logs/<type>-validation.md`，导致刷新后报告覆盖刷新前报告。
     - 第 `1423` 行与第 `1439` 行：当 `STAGE_VALIDATE_POST` 失败（`not post_ok`）时，直接调用 `_cleanup_temp()` **把刚刚耗时刷新的 `temp_output` 删除**，完全没有像第 `1363` 行 `STAGE_WORD_REFRESH` 失败那样调用 `_preserve_pending_output()`！
  2. `scripts/validate_docx.py:1283-1343`（`_header_footer_signatures`）与 `1442-1449`（`word_semantic_preservation_errors`）：
     - 刷新前校验 `template_preservation_errors`（第 `982` 行）调用了 `_normalized_header_part(template, name, config)` 将模板页眉中的纯文本版本号/文档编号归一化后再对比；
     - 刷新后校验 `word_semantic_preservation_errors`（第 `1442` 行）调用 `_header_footer_signatures(template, "word/header")` 与 `_header_footer_signatures(output, "word/header")` 时，**根本没有传入 `config`，也没有调用 `_normalize_header_fields(root, config)`**！导致只要 `build_docx.py:update_headers` 修改了页眉中的纯文本版本号或文档编号，刷新后校验必报 `"Word 刷新后非空页眉的静态文本、域、表格或图片变化"`。
  3. `scripts/validate_docx.py:1558-1745`（`validate_with_project`）：
     - `report.row_check(name=..., ok=...)` 将所有 22 项检查全部计入 `report.passed`（只要任意一项 `ok=False`，整个 `validate_with_project` 就返回 `False`）。其中 Word 刷新引起的事件流微调（`event_errors`）、书签被 Word 清理、样式重排、基线差异全部一票否决。

- **具体代码修改方案**：
  1. **修复 `scripts/validate_docx.py` 中的页眉签名未归一化 Bug（第 1283 行 & 第 1442 行）**：
     - 修改 `_header_footer_signatures` 签名与实现，支持传入 `config: Optional[Dict] = None` 并对页眉 XML 节点副本调用 `_normalize_header_fields`：
       ```python
       def _header_footer_signatures(
           package: DocxPackage, prefix: str, config: Optional[Dict] = None
       ) -> Counter:
           signatures = []
           for name in sorted(
               item for item in package.items if item.startswith(prefix) and item.endswith(".xml")
           ):
               raw_root = package.xml_roots[name]
               root = copy.deepcopy(raw_root)
               if config is not None and prefix == "word/header":
                   _normalize_header_fields(root, config)
               paragraphs = tuple(
                   text for text in (_static_paragraph_text(item) for item in root.iter(qn("p"))) if text
               )
               ...
       ```
     - 在 `word_semantic_preservation_errors`（第 `1442-1444` 行）调用时传入 `config`：
       ```python
       if set(_header_footer_signatures(template, "word/header", config)) != set(
           _header_footer_signatures(output, "word/header", config)
       ):
       ```
  2. **在 `scripts/validate_docx.py` 的 `Report` 类中引入 `warn_only: bool = False` 分级机制**：
     - 查看 `scripts/validate_docx.py` 中的 `Report.row_check`（约第 180-220 行），扩展签名为：
       ```python
       def row_check(self, name: str, ok: bool, detail: str = "", *, warn_only: bool = False) -> None:
       ```
       - 当 `ok=True` 时状态为 `"PASS"`；
       - 当 `ok=False` 且 `warn_only=True` 时，状态记为 `"WARN"`（写入报告并记录告警，但**不将 `self.passed` 置为 `False`**，即不阻断出稿）；
       - 当 `ok=False` 且 `warn_only=False` 时，状态记为 `"FAIL"`（硬阻断，`self.passed = False`）。
     - **明确划分硬阻断（`warn_only=False`）与软告警（`warn_only=True`）**：
       - **保持硬阻断（`warn_only=False`）的底线检查**：
         1. `"DOCX ZIP 与全部 XML 可解析"`
         2. `"Relationship Target 与引用完整"`（排除外部链接或模板固有问题后的真实断裂引用）
         3. `"章节编号、层级与必需资源预检"`
         4. `"document.xml 根节点结构合法"`（含 `w:body` 与末尾 `w:sectPr`）
         5. **刷新前（`require_refreshed=False`）** 的 `"Heading 数量、文本、层级、顺序一致"` 与 `"图片对象、内容哈希与位置一致"`
       - **调整为软告警（当 `require_refreshed=True` 时 `warn_only=True`，或全局 `warn_only=True`）的检查**：
         1. `require_refreshed=True` 时的 `"目录/Markdown 与 Word 元素顺序、上下文严格一致"`、`"Heading 数量、文本、层级、顺序一致"`、`"正文文本与位置一致"`、`"普通表格文本一致"`、`"复杂表格 OOXML 一致"`：当 `require_refreshed=True`（Word 刷新后）且文档中实际非空段落数 > 0 时，设为 `warn_only=True`（防止 Word 刷新重排样式 ID、增删书签或拆分 Run 导致误杀已刷新的正式文档）。
         2. `"媒体无重复打包"`：设为 `warn_only=True`。
         3. `"Word 已消费 updateFields..."`：当 `require_refreshed=True` 时设为 `warn_only=True`（WPS 或特定 Word 版本刷新后可能保留 `<w:updateFields>` 节点）。
         4. `require_refreshed=True` 时的 `Styles/Font/Theme`、`Numbering`、`Section`、`Header`、`Footer`、`settings.xml`、`封面编号/版本`、`TOC 刷新后包含全部 H1~H3 标题`、`封面总页数字段已刷新`：在 `require_refreshed=True` 时全部设为 `warn_only=True`（记录告警详情供检查面板查看，绝不销毁刷新后的正式文档）。
         5. `baseline` 基线对比项（`"原 Word 与重建 Word 业务元素顺序/文本严格一致"`、`"原 Word Heading 层次未改变"`）：设为 `warn_only=True`（用户本来就在编辑修改文档，修改后与原基线不同属于正常业务行为！）。
  3. **修改 `doc_tool/application/pipeline.py` 保护刷新后产物并分离日志**：
     - 在 `STAGE_VALIDATE_PRE`（约第 1140 行）传入 `report_override=str(paths.logs_dir / "{0}-validation-pre.md".format(manifest.documentType))`。
     - 在 `STAGE_VALIDATE_POST`（约第 1415-1452 行）：若 `not post_ok` 或发生异常，在调用 `_cleanup_temp()` 之前，**必须先调用 `preserved = _preserve_pending_output()`**，并将 `result.output_path = str(preserved)`（如果保留成功），确保无论发生什么错误，已刷新的 `.docx` 绝不被物理删除！

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_word_refresh_validation.py doc-tool/scripts/tests/test_formal_export_style_mapping.py doc-tool/scripts/tests/test_bookmark_and_numid_cleanup.py -q
  ```

---

#### - [x] Task 1.4：解除 `documentType` 硬编码限制，实现封面与页眉按模板结构自适应同步

- **现状代码定位**：
  1. `scripts/build_docx.py:3092-3095`：
     ```python
     update_custom_properties(items, config)
     if doc_type in ("requirement", "design"):
         update_cover(document_root, config)
         update_headers(items, config)
     ```
  2. `scripts/build_docx.py:1942-1972`（`update_cover`）：
     ```python
     if len(cover_tables) != 1:
         raise AutomationError("模板封面字段表数量异常，预期 1，实际 {0}".format(len(cover_tables)))
     ...
     if missing:
         raise AutomationError("模板封面缺少字段: {0}".format(", ".join(missing)))
     ```
  3. `scripts/validate_docx.py:1616-1625, 1693-1717`：`company_profile = doc_type in ("requirement", "design")`。

- **具体代码修改方案**：
  1. **改造 `scripts/build_docx.py:1942-2007` 的 `update_cover(root, config: Dict, *, strict: bool = False) -> bool`**：
     - 支持自适应探测模板封面信息表（扫描正文首个标题前的表格）：
       - 扩充可识别的封面标签映射：
         - `"文件编号"` / `"文档编号"` → `str(config.get("documentNo", ""))`（非空时更新）
         - `"版本号"` / `"版本"` / `"文档版本"` → `str(config.get("documentVersion", ""))`（非空时更新）
         - `"页数"` / `"总页数"` → `("field", "NUMPAGES \\* MERGEFORMAT")`
         - `"文档名称"` / `"文件名称"` → `str(config.get("documentName", ""))`（非空时更新）
       - 对表格中实际匹配到的标签更新其右侧相邻单元格（`cells[index + 1]`）；
       - 仅当 `strict=True` 且 completely missing `{"文件编号", "版本号", "页数"}` 时才抛 `AutomationError`；默认 `strict=False` 时，匹配到几个字段就更新几个字段，若模板没有封面表则正常跳过（不抛异常），并继续执行第 `1973-2006` 行的封面 `DOCPROPERTY` 域缓存更新！
  2. **改造 `scripts/build_docx.py:1826-1875` 的 `update_custom_properties` 与 `3092-3095` 的调用门禁**：
     - 在 `update_custom_properties` 中，除写入标准键 `{"文档编号": doc_no, "版本": doc_ver, "文件名称": doc_name}` 外，**若模板 `docProps/custom.xml` 中原本存在同义键名（`"文件编号"`、`"文档名称"`、`"版本号"`），必须同步更新这些同义属性的值**，并在 `apply_document_properties` 或 `update_cover`/`update_headers` 中同步刷新 `word/document.xml` 与 `word/header*.xml` 中所有引用这些保留属性的 `<w:fldSimple>` 及复合 `<w:fldChar>` 域缓存文本！
     - 移除 `scripts/build_docx.py:3092` 的 `if doc_type in ("requirement", "design"):` 门禁，对**所有 `documentType`（含 `general`）** 无条件调用：
       ```python
       update_custom_properties(items, config)
       update_cover(document_root, config, strict=False)
       update_headers(items, config)
       ```
     - 将 `scripts/validate_docx.py` 的 CRLF 换行符统一规整为 LF。
  3. **在 `doc_tool/domain/manifest.py:57` 与 `doc_tool/application/import_project.py:242` 中**：
     - 保持默认类型为 `"general"`，但将 `CREATABLE_DOCUMENT_TYPES` 恢复为 `("general", "requirement", "design")`（兼容测试与老项目显式指定 `requirement`/`design`），同时由于 `general` 已具备完整的自适应封面/页眉/修订表同步能力，用户无需理解文档类型差异即可获得完整还原体验。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_export_document_fields.py -q
  ```

---

#### - [x] Task 1.5：打通 CLI `project-export` 与 `build` 的文档字段、自定义属性覆盖及模板属性自动回填（CLI 与 GUI 100% 同源对等）

- **现状代码定位**：
  1. `doc_tool/cli.py:245-309`（`pexport_p = sub.add_parser("project-export", ...)`）与 `897-1000`（`_project_export_command`）：
     - GUI 的 `ExportSettingsDialog` 已支持设置 `document_no`（文件编号）、`document_name`（文件名称）、`document_version`（版本）、`document_properties`（自定义属性与核心属性）、`variant_id`（变体），但 **CLI 的 `project-export` 完全没有暴露这些参数**！
  2. `doc_tool/application/project_export.py:299-335`（`_prepare_snapshot_document`）：
     - GUI 在 `MainWindow._export_settings_context` 中当 `manifest.documentNo` 或 `manifest.documentName` 为空时，会调用 `read_template_reserved_properties(paths.template_docx)` 从模板 `docProps/custom.xml` 回填编号与名称；但 `_prepare_snapshot_document` 没有做这一步回填！导致通过 CLI 执行 `project-export` 时，若 `project.yml` 中 `documentNo` 为空，导出的文件名和文档属性直接丢失模板原本的编号！
  3. `doc_tool/cli.py:112-117, 1652-1684`（`build` 子命令）：
     - 仅支持 `--project` 和 `--skip-word-refresh`，不支持 `--output-file`、`--document-no`、`--document-name`、`--document-version`、`--property KEY=VALUE`、`--chapters`、`--variant` 及 `--output json`。

- **具体代码修改方案**：
  1. **在 `doc_tool/application/project_export.py:299` 的 `_prepare_snapshot_document` 中下沉模板保留属性自动回填逻辑（让 GUI 与 CLI 共享同一套默认值推理）**：
     ```python
     reserved_props = {}
     if paths.template_docx.is_file():
         try:
             from doc_tool.application.export.document_properties import read_template_reserved_properties
             reserved_props = read_template_reserved_properties(paths.template_docx)
         except Exception:
             reserved_props = {}
     effective_no = (
         request.document_no
         if request.document_no is not None
         else (manifest.documentNo or reserved_props.get("文档编号") or reserved_props.get("文件编号") or "")
     )
     effective_name = (
         request.document_name
         if request.document_name is not None
         else (manifest.documentName or reserved_props.get("文件名称") or reserved_props.get("文档名称") or "")
     )
     ```
  2. **在 `doc_tool/cli.py:245-309` 的 `project-export` 解析器中补齐文档字段、属性覆盖与属性探针参数**：
     ```python
     pexport_p.add_argument("--document-no", default=None, help="本次导出覆盖的文件编号（缺省沿用项目或模板）")
     pexport_p.add_argument("--document-name", default=None, help="本次导出覆盖的文件名称（缺省沿用项目或模板）")
     pexport_p.add_argument("--document-version", default=None, help="本次导出覆盖的版本号（缺省取 _revision_record.md 末行或清单）")
     pexport_p.add_argument(
         "--property", "-D", dest="properties", action="append", default=[],
         help="覆盖 Word 文档属性（格式 KEY=VALUE，如 custom:项目=二期 或 项目=二期 或 core:subject=主题，可重复指定）",
     )
     pexport_p.add_argument("--variant", default="", help="产品变体 ID（缺省主版本）")
     pexport_p.add_argument(
         "--inspect-properties", action="store_true",
         help="仅列出该项目模板可编辑的文档字段与自定义属性（支持 --output human|json），不执行导出",
     )
     pexport_p.add_argument("--json", action="store_true", help="等价 --output json")
     ```
  3. **在 `doc_tool/cli.py:897-1000` 的 `_project_export_command` 中解析 `--inspect-properties` 与 `--property`**：
     - 当 `--inspect-properties` 为 `True` 时：读取 `manifest`、`_revision_record.md` 版本、`read_template_reserved_properties(template_docx)` 及 `inspect_document_properties(template_docx)`，按 `human` 或 `json` 输出全部字段与可编辑属性后直接返回 `0`。
     - 解析 `args.properties`（`KEY=VALUE` 列表）：若用户写的 `KEY` 未带 `custom:` 或 `core:` 前缀，自动匹配 `inspect_document_properties(template_docx)` 中的 `"custom:" + KEY` 或 `"core:" + KEY`（或按中文 label 匹配 `core:creator` 等），构造 `document_properties` 字典传入 `ExportRequest(...)`。
  4. **升级 `doc_tool/cli.py:112-117, 1652-1684` 的 `build` 命令**：
     - 为 `build_p` 增加 `--output-file`、`--document-version`、`--property` (`-D`)、`--chapters`、`--variant`、`--output choices=("human", "json")`、`--json` 参数；
     - 在 `args.command == "build"` 执行时，使用 `with contextlib.redirect_stdout(sys.stderr):` 保持 `stdout` 纯净，当 `--output json` 或 `--json` 时输出包含 `success`、`outputPath`、`errorCode`、`stages`、`warnings` 的标准 JSON 报告。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_export_document_fields.py -q
  ```

---

### 阶段二（P1）：拆解、复杂表格与 Markdown 编辑还原闭环修复（解决“改完还原报错”）

#### - [x] Task 2.1：彻底消除复杂表格代理（`COMPLEX_TABLE_PROXY`）编辑即崩陷阱

- **现状代码定位**：
  1. `doc_tool/domain/smart_features.py:448-578`：
     - `extract_complex_table_proxy_rows`（第 `464-469` 行）：将 `vMerge=continue`（跨行合并续格）和 `gridSpan > 1`（跨列合并续格）全部填充为空字符串 `""`，对应 `tc_rows` 中为 `None`。
     - `apply_complex_table_proxy_edits`（第 `558-575` 行）：
       - 若用户在 Markdown 代理表中新增或删除了行（`len(proxy_rows) != len(orig_rows)`），直接 `raise ValueError("Complex-table proxy dimensions differ from the original XML")`；
       - 若用户在空白续格（`cell is None`）中填入任何字符，直接 `raise ValueError("Merged continuation cells cannot be edited through the table proxy")`。
  2. `scripts/build_docx.py:2772-2776` 与 `scripts/validate_docx.py:638-645`：调用 `apply_complex_table_proxy_edits` 时未做降级容错，一旦抛 `ValueError` 直接炸毁整篇文档的构建和校验。

- **具体代码修改方案**：
  1. **在 `doc_tool/domain/smart_features.py` 中支持合并续格自动归并 + 普通数据行动态增删**：
     - **改进 1（合并续格编辑自动归并到主单元格，不再抛异常）**：
       - 在 `extract_complex_table_proxy_rows(tbl_elem)` 中，除了返回 `(raw_rows, tc_rows)`，同时在内部记录每个合并续格 `(r, c)` 对应的**主单元格 `master_tc`**（水平合并 `gridSpan` 的主单元格就是当前行左侧起始 `tc`；垂直合并 `vMerge=continue` 的主单元格就是同列上方最近的非续格 `tc`）。
       - 在 `apply_complex_table_proxy_edits` 中，如果用户在原本为 `None`（合并续格）的位置填写了新文本 `new_text`（且忽略占位提示符如 `⟦合并⟧` / `←` / `↑`）：
         - 若能找到对应的 `master_tc` 且主单元格未被清空，将该文本追加合并到 `master_tc`（或直接忽略空白/占位符改动），**绝不抛出 `"Merged continuation cells cannot be edited"` 异常**！
     - **改进 2（支持在表格中动态新增/删除普通数据行）**：
       - 当 `len(proxy_rows) != len(orig_rows)` 但**列数一致**（`all(len(r) == len(orig_rows[0]) for r in proxy_rows)`）时：
         - 若 `len(proxy_rows) > len(orig_rows)`（用户新增了行，例如在表格末尾按 `Tab` 新增行）：以 XML 表格最后一个 `<w:tr>` 为原型深拷贝生成新 `<w:tr>`，清除其中的 `<w:vMerge>` 属性确保新行作为独立数据行，并将代理表新行的各列文本写入对应的 `<w:tc>`（若原型行某列带 `gridSpan`，按其网格映射填入文本），追加到 `tbl_elem` 末尾！
         - 若 `len(proxy_rows) < len(orig_rows)`（用户删除了行）：定位未匹配的尾部/非合并 `<w:tr>` 并从 `tbl_elem` 中移除。
     - **改进 3（列数改变时的优雅降级保底）**：
       - 在 `scripts/build_docx.py:2772-2776` 中，用 `try ... except ValueError:` 包裹 `apply_complex_table_proxy_edits(table_element, block.proxy_rows)`：
         - 当列数被用户改变导致原 XML 无法映射时，捕获 `ValueError`，打印一条中文 `WARN` 日志，并直接降级调用标准表格构造函数 `append_table(insert_before, TableBlock(rows=block.proxy_rows, ...), ...)` 将用户编辑后的 Markdown 表格作为普通 Word 表格插入文档，同时在 `scripts/validate_docx.py:638-645` 中同样捕获 `ValueError` 并降级，确保**用户在 Markdown 里怎么改表格都能成功导出 Word**！

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/ -k "complex_table or proxy" -q
  ```

---

#### - [x] Task 2.2：修复 `retain_pre_title_body=True` 时标题前正文在模板与章节中双重保留的 Bug

- **现状代码定位**：
  1. `doc_tool/adapters/importer.py:131-265`（`generate_template`）：
     - 查找首个 Heading 1 得到 `start_idx`（第 `217` 行），然后删除 `children[start_idx:]`（第 `243` 行），即 `children[:start_idx]`（包含封面、修订记录、目录以及标题前引言段落）全部留在 `template/template.docx` 中。
  2. `doc_tool/adapters/importer.py:476-482`（`extract_content`）：
     ```python
     if retain_pre_title_body and start_idx is not None and start_idx > 0:
         if _has_meaningful_content(children[:start_idx]):
             pre_title_chapter = pre_title_title
             start_idx = 0
     ```
     当 `retain_pre_title_body=True` 时，`extract_content` 把 `start_idx` 设为 `0`，将 `children[:first_h1_idx]` 提取成了 `01-前言.md`；但 `generate_template` 并没有把这部分从 `template.docx` 中删掉！结果构建出来的 Word 里，前置内容出现了两次。

- **具体代码修改方案**：
  1. **新增辅助函数 `_find_pre_title_body_start(children: list, first_heading_idx: int) -> int`（在 `doc_tool/adapters/importer.py` 中）**：
     - 在 `children[:first_heading_idx]` 范围内，跳过封面区、修订记录表和 TOC 目录域（即寻找最后一个 TOC 域段落或分节符 `sectPr` 之后的第一个普通正文段落索引 `pre_body_start`；若无 TOC/分节符，则取封面表之后的第一个非空段落）。
  2. **在 `generate_template`（`doc_tool/adapters/importer.py:131`）中增加参数 `retain_pre_title_body: bool = False`**：
     - 当 `retain_pre_title_body=True` 且 `start_idx > 0` 且 `_has_meaningful_content(children[:start_idx])` 时，计算 `cut_idx = _find_pre_title_body_start(children, start_idx)`，从 `children[cut_idx:]` 开始从 `template.docx` 的 `<w:body>` 中移除（保留 `cut_idx` 之前的封面、修订表和 TOC 目录容器，以及末尾的 `sectPr`）。
  3. **在 `extract_content`（`doc_tool/adapters/importer.py:478`）中**：
     - 当 `retain_pre_title_body=True` 时，同样从 `start_idx = _find_pre_title_body_start(children, start_idx)` 开始提取 `前言.md`（避免把模板已保留的封面表或 TOC 缓存文字误提取进 `前言.md`）。
  4. **在 `doc_tool/application/import_project.py:345-350` 调用 `generate_template` 时**：
     - 传入 `retain_pre_title_body=retain_pre_title`，使模板裁切点与正文提取起点完全对齐。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/ -k "import or pre_title" -q
  ```

---

#### - [x] Task 2.3：放宽章节目录扫描与内联标题层级的默认合并策略

- **现状代码定位**：
  1. `doc_tool/domain/merge_policy.py`：默认 `STRICT_MERGE_POLICY` 将 `renumber_mode` 设为 `RENUMBER_STRICT`（章节序号不连续即报错阻断），`auto_shift_inline_headings` 设为 `False`（二级章节文件里写 `##` 标题即报错阻断）。
  2. `scripts/docx_common.py:340-415, 575-605, 720-765`：
     - `validate_content_tree` 对非连续章节序号（如用户删掉 `02-xx.md`，剩下 `01-xx.md` 和 `03-xx.md`）直接抛 `AutomationError("目录编号必须从 1 开始连续递增...")`；
     - 对章节内标题层级 `block.level <= depth` 且未开启 `auto_shift_inline_headings` 时直接抛 `AutomationError("章节内标题层级必须深于目录层级...")`。

- **具体代码修改方案**：
  1. **在 `doc_tool/domain/merge_policy.py` 与 `doc_tool/adapters/kernel.py` 中调整默认构建策略**：
     - 当项目未显式配置严格阻断策略时，默认启用宽容模式：
       - `renumber_mode = RENUMBER_PRESERVE`（允许章节序号存在跳号，按文件名排序正常合并，不再因删掉一章而拒绝构建）；
       - `auto_shift_inline_headings = True`（当用户在深度为 `depth` 的章节文件内写了 `<= depth` 的标题且非文件首行主标题时，自动将其顺延下移到 `depth + 1` 层级，而不是抛异常阻断构建）。
  2. **在 `scripts/docx_common.py` 扫描 `content/` 目录时**：
     - 自动忽略 `.DS_Store`、`Thumbs.db`、`desktop.ini`、以 `.` 或 `~` 开头的隐藏/临时文件，避免因操作系统生成临时文件导致 `validate_content_tree` 报错。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/ -k "merge_policy or content_tree" -q
  ```

---

#### - [x] Task 2.4：净化拆解后的 Markdown 样式注释噪音并增强空行容错

- **现状代码定位**：
  1. `doc_tool/adapters/importer.py:961-1035`：提取段落时，把常见默认行距/首行缩进写成 `<!-- P:line=360;lr=auto;first=420 -->` 注入在每个段落上方；
  2. `scripts/docx_common.py` 解析 `<!-- P:... -->` 与 `<!-- TBL:... -->` 时，如果用户在注释和下方的段落/表格之间多敲了一个空行，注释就会失效或绑定错位。

- **具体代码修改方案**：
  1. **在 `scripts/docx_common.py` 的 `parse_blocks` 中增强注释与目标块的空行容错**：
     - 当解析到 `<!-- P:... -->` 或 `<!-- TBL:... -->` 注释行后，允许其与紧随其后的段落或表格之间存在 1~2 个空行（即遇到空行时不立即清空 `pending_p_meta` / `pending_tbl_meta`，直到绑定到下一个非空段落/表格块或遇到新的块类型为止）。
  2. **在 `doc_tool/ui/content/editor_panel.py` 中提供「隐藏/弱化排版注释」支持**：
     - 在语法高亮器中将 `<!-- P:... -->`、`<!-- TBL:... -->`、`<!-- TABLE:... -->`、`<!-- COMPLEX_TABLE_PROXY:... -->` 渲染为浅灰小号弱化样式，降低对正文阅读的视觉干扰。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/ -k "parse_blocks or importer" -q
  ```

---

#### - [x] Task 2.5：补齐 CLI `import`（拆解 Word）的核心参数与源文档属性自动提取

- **现状代码定位**：
  1. `doc_tool/cli.py:124-141`（`import_p`）与 `doc_tool/application/cli_commands.py:124-225`（`import_command`）：
     - `import` 命令目前仅支持 `--docx`、`--name`、`--target-dir`、`--document-type`、`--document-no`、`--document-name`、`--document-version`、`--preset`、`--save-preset`。
     - **缺失核心拆解参数**：不支持 `--retain-pre-title`（保留首个一级标题前的正文为独立章节）、`--pre-title-title`（自定义前言章节标题）、`--allow-missing-headings`（允许无标准 Heading 1 的文档通过启发式规则拆解）、`--split-level`（指定拆分深度 1~6）。
     - **缺失源文档元数据自动提取**：当命令行未显式传 `--document-no` 或 `--document-version` 时，`import_command` 直接传空串 `""`，未尝试调用 `read_template_reserved_properties(Path(args.docx))` 从源 Word 的 `docProps/custom.xml` 提取原有的「文档编号 / 文件编号 / 版本」，导致 CLI 导入的项目丢失源文档属性！

- **具体代码修改方案**：
  1. **在 `doc_tool/cli.py:124-141` 的 `import_p` 中补齐拆解控制参数**：
     ```python
     import_p.add_argument(
         "--document-type", choices=("general", "requirement", "design"), default="general",
         help="项目文档类型（默认 general，兼容 requirement/design）",
     )
     import_p.add_argument(
         "--retain-pre-title", action="store_true",
         help="将首个一级标题前的引言正文保留为独立 Markdown 章节（如 01-前言.md）",
     )
     import_p.add_argument(
         "--pre-title-title", default="前言",
         help="搭配 --retain-pre-title 使用的前置章节标题（默认：前言）",
     )
     import_p.add_argument(
         "--allow-missing-headings", action="store_true", default=True,
         help="当源文档缺少标准 Heading 1 时允许按大纲/启发式规则自动识别标题层级（默认开启）",
     )
     import_p.add_argument(
         "--split-level", type=int, choices=(1, 2, 3, 4), default=0,
         help="指定章节文件拆分的最大标题层级（1~4，0 表示沿用默认拆分策略）",
     )
     import_p.add_argument("--json", action="store_true", help="等价 --output json")
     ```
  2. **在 `doc_tool/application/cli_commands.py:159-168`（或 `import_project.py`）中自动回填源 `.docx` 的保留属性并透传拆解参数**：
     - 若 `not args.document_no` 或 `not args.document_version`，自动调用 `read_template_reserved_properties(Path(args.docx))` 读取源文档 `custom.xml` 中的编号与版本作为初始值；
     - 将 `decide_pre_title_body=bool(getattr(args, "retain_pre_title", False))`、`pre_title_chapter_title=str(getattr(args, "pre_title_title", "前言") or "前言")`、`allow_missing_headings=bool(getattr(args, "allow_missing_headings", True))` 及 `split_level` 传入 `ImportRequest`。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/ -k "cli and import" -q
  ```

---

### 阶段三（P1）：界面与 CLI 交互大收敛（解决“交互很乱”）

#### - [x] Task 3.1：顶部 `ProjectBar` 出稿按钮四合一收敛（消除 6 按钮并列混乱）

- **现状代码定位**：
  - `doc_tool/ui/project_bar.py:114-165`：
    目前在顶部项目条上一字排开了 6 个操作按钮：
    1. `self._quick_export_btn = QPushButton("导出 Word", self)` (`barQuickExportBtn`)
    2. `self._export_settings_btn = QPushButton("导出设置…", self)` (`barExportSettingsBtn`)
    3. `self._results_btn = QPushButton("成果", self)` (`barResultsBtn`)
    4. `self._validate_btn = QPushButton("项目检查", self)`
    5. `self._diag_btn = QPushButton("快速构建", self)`
    6. `self._merge_btn = QPushButton("正式出稿", self)`

- **具体代码修改方案**：
  1. **重构 `doc_tool/ui/project_bar.py:114-165` 的按钮视觉呈现（保持原有属性名如 `self._quick_export_btn`、`self._export_settings_btn`、`self._validate_btn`、`self._diag_btn`、`self._merge_btn`、`self._results_btn` 存在以兼容所有既有单元测试，但收敛默认可见性与布局）**：
     - **主按钮 `self._quick_export_btn`**：文案设为 `"导出正式 Word"`（Tooltip：`"一键保存修改、同步版本并导出 Word 文档 (Ctrl+E)"`，`btnRole="primary"`）。
     - **次按钮 `self._export_settings_btn`**：文案设为 `"导出选项 ▾"`（或 `"导出设置…"`，紧贴主按钮右侧，点击打开导出设置弹窗，同时提供下拉菜单或快捷入口访问「快速预览稿（无 Word 刷新）」與「查看历史成果」）。
     - **辅助按钮 `self._validate_btn`**：文案设为 `"检查 (F5)"`。
     - **收纳冗余常驻按钮**：将顶栏上的 `self._diag_btn`（快速构建）、`self._merge_btn`（正式出稿）、`self._results_btn`（成果）默认收纳进「导出选项」下拉菜单（或在顶栏隐藏 `setVisible(False)`，仅在内部保留对象引用与 `click()` 信号连接，从而既让界面从 6 个按钮清爽收敛为 **「导出正式 Word」+「导出设置…」+「检查」**，又不破坏任何直接调用 `_merge_btn` / `_diag_btn` 的存量测试代码！）。
     - *注意*：先检查 `scripts/tests/test_ui2_export_settings.py`、`test_ui2_visual_hierarchy.py`、`test_ui_polish_quick_export.py` 对 `ProjectBar` 按钮 `isVisible()` 的具体断言。若现有测试断言了 `_quick_export_btn` 与 `_export_settings_btn` 可见、`_diag_btn`/`_merge_btn` 处于次级，请确保收敛后的可见性与测试契约完全兼容（例如将 `_diag_btn` 与 `_merge_btn` 放入可展开的「高级构建 ▾」菜单或按测试契约保持最小化展示）。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_ui2_export_settings.py doc-tool/scripts/tests/test_ui2_visual_hierarchy.py doc-tool/scripts/tests/test_ui_polish_quick_export.py -q
  ```

---

#### - [x] Task 3.2：右侧 `TaskDock` 结果视图打通与底部状态栏胶囊降噪

- **现状代码定位**：
  1. `doc_tool/ui/task_dock.py:225-265`：`TaskDock` 使用 `QStackedWidget` 将 Page 0（`ExportResultsView` 成果视图）与 Page 2/3（`ResultCard` 任务结果视图）完全隔离：
     - 跑 `run_project_export` 时显示 Page 0；
     - 跑 `run_pipeline`（`正式出稿` / `快速构建`）时显示 Page 2/3，且不会把产物加入 Page 0 的「成果」列表。
  2. `doc_tool/ui/main_window.py:380-398`：底部状态栏还额外塞入了一排 `_output_capsules_widget`（5 个按钮：`打开 Word`、`定位文件`、`复制路径`、`另存为`、`交付历史`），与右侧面板完全重复。

- **具体代码修改方案**：
  1. **打通 `run_pipeline` 与 `ExportResultsView` 成果记录**：
     - 在 `doc_tool/ui/main_window.py` 的 `_on_task_done`（当 `merge` 或 `diag-build` 成功产出 `output_path` 时）中，同步将该次产物注册/刷新到右侧 `TaskDock` 的成果记录中，并在 `ResultCard` 上提供一键「打开 Word」「定位目录」「查看校验报告（含 WARN 详情）」按钮。
  2. **简化底部状态栏 `_output_capsules_widget`**：
     - 在 `doc_tool/ui/main_window.py` 中，将底部状态栏的冗余胶囊按钮收敛为最多保留 1 个轻量的「📄 打开最新导出 Word」快捷链接，其余冗余按钮（「复制路径」「另存为」「交付历史」）统一由右侧结果面板承载，彻底解决底部状态栏拥挤问题。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_ui2_visual_hierarchy.py -q
  ```

---

#### - [x] Task 3.3：二级路径导航条与编辑器工具栏紧凑化、底部工具面板 Tab 归并

- **现状代码定位**：
  1. `doc_tool/ui/main_window.py:402-465`（`_build_nav_bar`）：高度松散，占用了整行空间。
  2. `doc_tool/ui/content/editor_panel.py:417-530`（`_build_toolbar`）：单行堆砌了 20+ 个按钮（含低频的 `代码片段`、`Mermaid`、`粘贴表格`、`表格网格`、`本地历史`、`回滚`、`外部打开`）。
  3. `doc_tool/ui/content/workspace.py:335-385`：底部工具面板有 8 个独立 Tab。

- **具体代码修改方案**：
  1. **压缩 `_build_nav_bar` 与 `_build_toolbar` 的纵向边距与低频按钮**：
     - 将 `_build_nav_bar` 的上下边距 `ContentsMargins` 压缩为 `(6, 1, 6, 1)`，固定紧凑高度 `28px`；
     - 在 `editor_panel.py` 的 `_build_toolbar` 中，将低频操作按钮（`插入片段`、`插入流程图`、`粘贴为表格`、`本地历史`、`回滚到基线`、`外部打开`）收纳进工具栏右侧的一个 `QToolButton("更多 ▾")` 菜单中（保留原有按钮实例属性以兼容测试调用，仅从主横排布局移入菜单或折叠区），让编辑器顶部工具栏清爽聚焦于：**标题层级、加粗/斜体、插入图片、插入/格式化表格、显示目录、切换预览、保存 (`Ctrl+S`)**。
  2. **优化底部工具面板默认状态**：
     - 在 `doc_tool/ui/content/workspace.py` 中，底部工具面板默认处于折叠隐藏状态（仅当用户按 `Ctrl+F` 搜索、点击「问题」或「图片」时按需展开），并为高频 Tab 设置清晰分组图标与紧凑标签高度。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/ -k "workspace or editor" -q
  ```

---

#### - [x] Task 3.4：主副航道隔离与顶层菜单精简

- **现状代码定位**：
  - `doc_tool/ui/main_window.py` 菜单栏构建处（`_build_menu_bar`）：存在 8 个顶层菜单（`文件`、`操作`、`视图`、`内容`、`版本控制`、`工具`、`命令`、`帮助`），其中 `命令` 菜单动态把命令注册表里的项又重复挂了一遍；且 `PDF 工具箱`、`文档互转`、`研发工作区`、`批量交付` 等非核心功能散落各处。

- **具体代码修改方案**：
  1. **在 `doc_tool/ui/main_window.py` 的 `_build_menu_bar` 中**：
     - 将动态重复的顶层 `命令` 菜单隐藏或合入 `工具` 菜单下的「命令面板 (`Ctrl+K`)」子项（保留 `self._commands_menu` 实例引用以防单元测试访问该属性）；
     - 将 `PDF 工具箱`、`文档互转`、`研发工作区`、`批量交付` 统一归入 `工具`（扩展工具）菜单，不在主编辑区顶栏抢占视觉焦点。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/ -k "menu or command" -q
  ```

---

#### - [x] Task 3.5：CLI 主航道命令收敛与直达别名（`decompose` / `check` / `export` 三步闭环）

- **现状代码定位**：
  - `doc_tool/cli.py:38-705`：顶层平铺了 38+ 个子命令（`mainflow-advice`、`capabilities`、`baseline-check`、`item-list`、`trace-plan`、`project-export` 等），用户或 AI 脚本执行核心主航道（「拆解 Word → 检查项目 → 正式还原导出 Word」）时找不到直观的 `export` 或 `decompose` 命令，且 `--help` 顶部被外围低频命令占满。

- **具体代码修改方案**：
  1. **在 `doc_tool/cli.py` 中注册主航道一级直达别名（保持全部既有命令名 100% 兼容）**：
     - 为 `import` 增加语义化别名 `decompose`（`aliases=["decompose"]` 或同源注册 `decompose` 子命令，直接指向 `import_command`）：`python -m doc_tool.cli decompose --docx input.docx --name my_proj`；
     - 为 `project-export` 增加语义化短命令别名 `export` 与 `restore`（同源调用 `_project_export_command`）：`python -m doc_tool.cli export --project my_proj --document-version 2.0 -D 项目=二期`；
  2. **优化 `doc_tool/cli.py:38` `build_parser()` 的 `--help` 顶层说明（`description` / `epilog`）**：
     - 在 `ArgumentParser` 的 `description` 中醒目列出 **核心主航道三步命令**：
       1. **拆解文档**：`doc-tool import (或 decompose) --docx <源.docx> --name <项目名> [--retain-pre-title]`
       2. **检查与查看属性**：`doc-tool check --project <项目目录>` / `doc-tool export --project <项目目录> --inspect-properties`
       3. **正式还原导出**：`doc-tool export (或 project-export) --project <项目目录> [--document-no ...] [--document-name ...] [--document-version ...] [-D 属性名=值]`
  3. **同步更新 `docs/使用说明.md` 中的 CLI 核心主航道章节**。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; python -m doc_tool.cli --help; pytest doc-tool/scripts/tests/ -k "cli" -q
  ```

---

### 阶段四（P2）：架构解耦与全链路端到端回归测试固化

#### - [x] Task 4.1：抽离 `MainWindow` 导出与辅助控制器，降低 7,300 行上帝类耦合度

- **现状代码定位**：
  - `doc_tool/ui/main_window.py` 高达 7,323 行，所有导出组装、修订版本提取、文档属性探针、前置检查全部塞在 `MainWindow` 类内部。

- **具体代码修改方案**：
  1. 新建 `doc_tool/ui/controllers/export_orchestrator.py`（或 `doc_tool/application/export/workbench_coordinator.py`），将以下纯协调逻辑从 `MainWindow` 抽离为独立可测试函数/控制器，`MainWindow` 仅做薄委托：
     - `resolve_effective_export_version(manifest, paths)`（从 `_revision_record.md` 提取版本并同步 `manifest`）
     - `build_default_export_request(summary, buffers, word_available)`（构造默认正式导出请求）
     - `collect_export_settings_context(summary, buffers, active_chapter)`（收集导出设置对话框上下文，供 GUI 弹窗与 CLI `--inspect-properties` 共同复用！）
  2. 确保 `MainWindow` 原有方法名（`_quick_export_defaults`、`_export_settings_context`、`_revision_record_version`）保留并委托给新模块，做到 100% 向后兼容。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_ui2_export_settings.py -q
  ```

---

#### - [x] Task 4.2：编写并跑通「GUI + CLI 导入拆解 → 修改正文/复杂表格/修订表 → 正式还原 Word」6 大场景端到端回归测试

- **具体代码修改方案**：
  1. 新建端到端测试文件 `doc-tool/scripts/tests/test_mainflow_decompose_edit_restore_e2e.py`，编写以下 **6 个核心闭环测试函数**：
     - `test_e2e_1_general_project_cover_and_header_sync`：
       创建一个 `documentType="general"` 的项目（模板含封面信息表「文件编号/版本号/页数」、`docProps/custom.xml` 同义属性「文件编号/文档名称/版本号」及含纯文本版本号的页眉），修改 Markdown 章节并将 `documentVersion` 更新为 `V2.3`，执行 `build_docx` + `validate_with_project(require_refreshed=True)`，断言：
       - 封面「版本号」更新为 `V2.3`；
       - 页眉纯文本版本号与 `DOCPROPERTY` 缓存文本更新为 `V2.3`；
       - `docProps/custom.xml` 中的同义属性「文件编号/文档名称/版本号」全部同步更新；
       - `validate_with_project(require_refreshed=True)` **通过（返回 `True`）**，不再报错 `"Word 刷新后非空页眉的静态文本、域、表格或图片变化"`！
     - `test_e2e_2_complex_table_proxy_edit_and_row_append_never_crashes`：
       构造一个带 `gridSpan=2` 和 `vMerge=continue` 的复杂表格 XML 及 `COMPLEX_TABLE_PROXY` 块：
       - 场景 A：修改普通单元格文字 + 在被合并续格填入文字 → 调用 `apply_complex_table_proxy_edits` 不抛异常，主单元格内容正常更新；
       - 场景 B：在代理表末尾新增一行数据 → 调用 `apply_complex_table_proxy_edits` 动态克隆追加 `<w:tr>` 成功，不抛 `ValueError`；
       - 场景 C：修改代理表列数 → 调用 `build_docx` 捕获异常自动降级为标准表格完成构建，生成有效 `.docx`。
     - `test_e2e_3_post_refresh_validation_soft_warning_preserves_docx`：
       模拟 `run_pipeline` 执行过程中 `STAGE_VALIDATE_POST` 遇到样式重排/书签清理或硬错误，断言：
       - 非致命差异下 `validate_with_project(require_refreshed=True)` 以 `WARN` 放行并产出正式 `.docx`；
       - 即使人为触发 `STAGE_VALIDATE_POST` 硬失败，已刷新的 `.docx` 仍被 `_preserve_pending_output()` 保留在磁盘上，绝不被删除。
     - `test_e2e_4_retain_pre_title_body_no_duplication`：
       构造一个在首个 `Heading 1` 之前带有封面表和 2 段引言正文的 `.docx`，以 `retain_pre_title_body=True` 执行 `generate_template` + `extract_content` + `build_docx`，断言还原后的 `.docx` 中引言正文只出现 **1 次**（不重复）。
     - `test_e2e_5_non_contiguous_chapter_numbers_and_inline_headings_build_cleanly`：
       在 `content/` 下放置 `01-概述.md` 和 `03-架构.md`（跳过 `02`），并在二级章节文件内写入 `## 内联小节`，默认配置下运行 `build_docx`，断言不报错阻断、顺利生成 `.docx`。
     - `test_e2e_6_cli_decompose_inspect_edit_export_full_chain`：
       **纯 CLI 端到端闭环验证**：
       1. 调用 `doc_tool.cli.main(["decompose", "--docx", src_docx, "--name", "cli_proj", "--target-dir", work_dir, "--retain-pre-title", "--json"])` 拆解源文档，断言返回码为 `0` 且自动从源文档 `custom.xml` 提取了初始编号与版本；
       2. 调用 `doc_tool.cli.main(["export", "--project", proj_dir, "--inspect-properties", "--json"])` 探测可编辑文档属性；
       3. 修改拆解出的章节 `.md` 与 `_revision_record.md`；
       4. 调用 `doc_tool.cli.main(["export", "--project", proj_dir, "--no-refresh", "--document-no", "CLI-999", "--document-name", "命令行交付文档", "--document-version", "5.0", "-D", "项目=CLI测试项目", "--json"])`；
       5. 断言返回码为 `0`，输出文件名为 `CLI-999 命令行交付文档(5.0).docx`，且产物 `.docx` 的正文、页眉、封面与 `docProps/custom.xml` 全部包含更新后的文本与属性值！
  2. 清理工作区临时残留目录 `.codex-tmp/`（若存在且无用），并在 `.gitignore` 中确保忽略 `.codex-tmp/`。

- **单步验证命令**：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; pytest doc-tool/scripts/tests/test_mainflow_decompose_edit_restore_e2e.py -v
  ```

---

## 四、 全量竣工总验收命令（Final Gate）

当 `Task 1.1` ~ `Task 4.2`（共 15 个子任务）全部勾选 `[x]` 后，执行以下总回归命令确认核心主航道（GUI + CLI + 内核管线）测试 100% 绿灯：

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
pytest doc-tool/scripts/tests/test_mainflow_decompose_edit_restore_e2e.py `
       doc-tool/scripts/tests/test_export_document_fields.py `
       doc-tool/scripts/tests/test_formal_export_style_mapping.py `
       doc-tool/scripts/tests/test_bookmark_and_numid_cleanup.py `
       doc-tool/scripts/tests/test_word_refresh_validation.py `
       doc-tool/scripts/tests/test_export_round_recovery.py `
       doc-tool/scripts/tests/test_ui2_export_settings.py `
       doc-tool/scripts/tests/test_ui2_visual_hierarchy.py `
       doc-tool/scripts/tests/test_ui_polish_quick_export.py -v
```

---

## 五、 阶段五（自驱巡检闭环）：全链路逐模块深挖找茬与自动修复规约（Bug-Hunt & Auto-Fix Loop）

当完成上述 `Task 1.1` ~ `Task 4.2` 后，AI 必须自动进入 **「全链路逐模块找问题 → 构造复现测试 → 定位根因并修复 → 回归验证」** 的自驱闭环，按以下 **6 个深水区维度** 逐一排查，发现一处修一处，严禁走马观花：

### - [x] Patrol 5.1：导入拆解边界与畸形 Word 容错巡检（`importer.py` / `import_project.py` / `preflight.py`）
- **主动找茬点**：
  1. 源 Word 文档中含嵌套表格、浮动图片（`wp:anchor`）、VML 旧版图形（`w:pict`）、公式（`m:oMath`）、内容控件（`w:sdt` 包裹标题或表格）时，拆解是否漏提文本、丢失图片或抛异常中断？
  2. 源 Word 文档在首个一级标题前既有封面表、又有修订记录表、还有目录（TOC）和引言段落时，`generate_template` 与 `extract_content` 的切分点是否精确？是否存在把修订记录表或 TOC 误删或重复提取的情况？
  3. 重新导入（Re-import）已有项目或覆盖导入时，旧资源（`assets/`）与新章节映射是否存在残留冲突？
- **动作要求**：构造边界样本进行实测，发现任何异常、漏提或错位，立即修复代码并补充回归单测。

### - [x] Patrol 5.2：Markdown 与复杂表格编辑还原极限压测（`smart_features.py` / `docx_common.py` / `build_docx.py`）
- **主动找茬点**：
  1. 在 `COMPLEX_TABLE_PROXY` 中同时包含跨行合并（`vMerge`）与跨列合并（`gridSpan`）时：修改多行文本、包含换行符 `<br>`、管道符 `\|`、单元格内含超链接或加粗代码、在表格中间插入行或删除行时，写回 XML 是否保持合法 OOXML 结构且不丢样式？
  2. 章节 Markdown 中包含代码块（内含 `# 伪标题` 或 `| 伪表格 |`）、HTML 注释、空表格、连续多张表格、缺失文件的图片链接 `![](missing.png)` 时，`parse_blocks` 与 `build_docx` 是否会崩溃或生成损坏的 `.docx`？
  3. 修订记录表 `_revision_record.md` 为空表、只有表头、版本号带前缀 `v`/`V`/空格、或包含多行备注时，版本号提取与写回 Word 修订表是否完全一致？
- **动作要求**：逐项编写极限输入探测脚本，跑出异常后直接修复解析与构建器代码。

### - [x] Patrol 5.3：导出文档属性、封面、页眉页脚与 Word 刷新后校验联动巡检（`document_properties.py` / `build_docx.py` / `validate_docx.py` / `pipeline.py`）
- **主动找茬点**：
  1. 模板 `word/header*.xml`、`word/footer*.xml` 或封面中存在跨多个 `<w:r><w:instrText>` 拆分的复杂 `DOCPROPERTY` 域（例如 `DOCPROPERTY` 与 `"文档编号"` 被 Word 拆在 3 个 Run 中，或带 `\* MERGEFORMAT` 开关）时，`document_properties.py:_update_field_results`、`build_docx.py:update_headers` 与 `validate_docx.py:_normalize_header_fields` 能否 100% 识别并同步更新缓存文本？
  2. 当本机执行真实或模拟的 Word COM 刷新（`refresh_fields.py`）后，若 Word 自动增删了 `word/header*.xml` 的空白段落、重排了 `numbering.xml`、修改了 `settings.xml` 或 `theme1.xml` 的次要属性，`validate_docx.py` 是否仍存在任何未设为 `warn_only` 的误杀项？
  3. 导出文件名中若包含特殊字符、重复版本号括号（如 `documentName` 本身已带 `(V1.0)`）或超长路径时，`_output_stem` 与发布重命名是否安全？
- **动作要求**：核对所有域解析正则与状态机，修复跨 Run 拆分域与文件名边界 Bug。

### - [x] Patrol 5.4：GUI 主工作台交互、信号连接与并发状态机死角巡检（`main_window.py` / `project_bar.py` / `export_settings_dialog.py` / `task_dock.py` / `workspace.py`）
- **主动找茬点**：
  1. 全面扫描 `main_window.py`、`project_bar.py`、`task_dock.py`、`workspace.py`、`editor_panel.py` 中所有的按钮、菜单 Action 与信号槽连接：是否存在回调为 `None`、方法名拼写错误、参数个数不匹配（如 `clicked.connect` 传入了 `bool` 参数覆盖默认参数导致报错）？
  2. 用户在编辑器修改了正文字段或 `_revision_record.md`（未按 `Ctrl+S`），然后依次触发：`导出 Word (Ctrl+E)`、`导出设置…`、`项目检查 (F5)`、`快速构建`、`正式出稿`、`重命名章节`、`切换章节`，核对每一条路径是否正确处理了未保存缓冲区，是否存在数据丢失或覆盖？
  3. 导出任务运行中、取消导出、导出失败重试、从右侧结果面板点击「打开文件 / 定位目录 / 重新生成 / 修改设置」时，按钮禁用/恢复状态机是否严密，有无死锁（按钮永久置灰）或空指针崩溃？
- **动作要求**：用无头 Qt 测试（`QApplication`）逐个模拟点击全部主流程按钮与菜单项，抓出所有潜伏的 UI 异常并就地修复。

### - [x] Patrol 5.5：CLI 全子命令契约、参数组合与退出码巡检（`cli.py` / `cli_commands.py`）
- **主动找茬点**：
  1. 逐一调用 CLI 核心命令：`preflight`、`import` / `decompose`、`check`、`validate`、`lint`、`build`、`project-export` / `export` / `restore`（分别测试 `--output human` 与 `--output json` / `--json`）。
  2. 在 `--json` 模式下，`stdout` 是否为 100% 纯净可 `json.loads()` 的合法 JSON（有无任何进度打印或日志泄漏到 `stdout`）？
  3. 传入不存在的项目路径、非法的 `--property KEY=VALUE`、只读输出目录、缺失章节名时，CLI 是否返回正确的非零退出码并给出清晰的中文错误提示（而非裸 Python Traceback）？
- **动作要求**：编写 CLI 全子命令冒烟与异常参数巡检测试，修复所有 JSON 污染或未捕获异常。

### - [x] Patrol 5.6：全仓存量测试套件大横扫与回归清零
- **动作要求**：
  1. 运行 `doc-tool/scripts/tests/` 下的全量测试文件（分批或全量运行 `pytest doc-tool/scripts/tests/`），找出因近期重构或历史遗留导致的任何失败用例；
  2. 逐个分析失败原因，修复业务代码或对齐测试契约，直至全仓测试 **0 failed**；
  3. 将巡检发现并修复的所有问题汇总写入本文件末尾的《六、自驱巡检发现与修复记录表》。

---

## 六、自驱巡检发现与修复记录表

在阶段五（Patrol 5.1 ～ Patrol 5.6）全链路逐模块深度找茬与全仓存量测试横扫过程中，主动构造极端边界条件、模拟异常参数与环境缺陷，共计发现并彻底闭环修复 9 类隐蔽 Bug / 潜在异常 / 未同步状态。全仓测试（覆盖 251 个测试套件、3500+ 个用例）已实现 **0 failed**，所有缺陷均配备对应回归测试文件。

### 1. 缺陷闭环汇总清单

| 问题编号 | 巡检阶段 | 缺陷类型与极端边界现象 | 根因分析 | 涉及源文件 | 修复方案与代码变更 | 回归测试套件 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P5-01** | Patrol 5.1 | **内容控件解包与深层表格丢失**<br>源 Word 中含有非 TOC 块级 `<w:sdt>` 包裹正文或表格时拆解丢失；`_cell_visible_text` 遍历嵌套单元格时丢失深层段落文字；对 XML 注释调用 `QName` 触发 Cython 异常。 | 1. 拆解仅遍历 `w:body` 首层，未解包内容控件；<br>2. 仅用直接子元素 `tc.findall`，丢失嵌套表格文字；<br>3. `etree.QName` 对 Cython Comment 类型报错。 | `doc_tool/adapters/importer.py`<br>`doc_tool/adapters/preflight.py`<br>`doc_tool/domain/smart_features.py` | 1. 增加 `_unwrap_block_sdts` 提取前安全解包 `w:sdt`；<br>2. `_is_toc_element` 扩展支持 `docPartGallery` 识别；<br>3. `_cell_visible_text` 改用 `tc.iter(_qn("p"))`；<br>4. 安全提取 `_local_tag`。 | `scripts/tests/test_patrol_5_1_edge.py` | **100% 通过**<br>(5/5 passed) |
| **P5-02** | Patrol 5.2 | **跨库 AST 混用崩溃与资源缺失容错**<br>复杂表格写回合并单元格或 `<br>` 换行时报 `TypeError: SubElement() argument 1 must be xml.etree.ElementTree.Element, not lxml.etree._Element`；代理表标记有空行无法识别；缺失图片导致整篇导出崩溃。 | 1. `smart_features.py` 混用 `xml.etree` 与 `lxml` 节点；<br>2. `blocks.py` 正则未容许注释间空行；<br>3. 构建管线遇到损坏/缺失图片无兜底。 | `doc_tool/domain/smart_features.py`<br>`doc_tool/domain/blocks.py`<br>`scripts/build_docx.py` | 1. 实现多态 `_sub_element(parent, ...)` 兼容 `makeelement` 与深拷贝 `rPr`；<br>2. 放宽 `blocks.py` 正则支持 1~2 行空行；<br>3. 缺失图片优雅降级为提示段落 `【图片缺失或损坏: ...】`，跳过全空表格。 | `scripts/tests/test_patrol_5_2_edge.py` | **100% 通过**<br>(5/5 passed) |
| **P5-03** | Patrol 5.3 | **页脚保留属性遗漏与简单域误杀**<br>页脚 `word/footer*.xml` 中的同义保留属性未同步；`validate_docx.py` 缺少对 `<w:fldSimple>` 规范化导致误杀；导出文件名因已有 `(V1.0)` 导致生成双括号 `(V1.0)(1.0).docx`。 | 1. 构建与校验过去仅扫描了 `header*.xml`；<br>2. 校验时未平铺简单域导致文本签名不一致；<br>3. 文件名生成正则未剥离原有的版本括号。 | `scripts/build_docx.py`<br>`scripts/validate_docx.py`<br>`doc_tool/application/project_export.py` | 1. `update_headers` 扩展为同时更新并扫描 header 与 footer；<br>2. `_normalize_header_fields` 补充 `<w:fldSimple>` 解析与页脚清洗；<br>3. `_output_stem` 增加多余版本括号正则清理。 | `scripts/tests/test_patrol_5_3_edge.py` | **100% 通过**<br>(3/3 passed) |
| **P5-04** | Patrol 5.4 | **主界面未保存缓冲区在检查时未同步**<br>用户在编辑器修改正文或修订记录未按 `Ctrl+S` 时，触发 F5 项目检查或产物校验仍基于老版本；无头环境或测试 Double 调用导出协调器易抛 `AttributeError`。 | 1. `_on_validate` 与 `_on_validate_output` 缺少未保存缓冲区预刷新调用；<br>2. 导出协调器对私有属性探测不够防御性。 | `doc_tool/ui/main_window.py`<br>`doc_tool/ui/controllers/export_orchestrator.py` | 1. 在 `_on_validate` / `_on_validate_output` 中以安全 `getattr` 注入预刷同步；<br>2. 协调器增加安全探针 `_revision_record_version`，优先读活跃编辑器。 | `scripts/tests/test_patrol_5_4_edge.py` | **100% 通过**<br>(3/3 passed) |
| **P5-05** | Patrol 5.5 | **CLI 参数格式容错与裸 Traceback 拦截**<br>CLI 传入格式非法的 `--property`（缺少等号）时内部解包报错；执行 `build` 传入不存在的项目清单时抛出裸 Python Traceback。 | 1. `cli.py` 缺少对 `--property` 拆分的格式校验；<br>2. `_build_command` 未捕获 `ProjectManifestError`。 | `doc_tool/cli.py` | 1. `--property` 校验是否存在 `=`，格式错误向 `stderr` 打印中文指引并返回退出码 2；<br>2. `build` 增加清单异常捕获并输出退出码 2。 | `scripts/tests/test_patrol_5_5_edge.py`<br>`scripts/tests/test_cli_machine.py` | **100% 通过**<br>(3/3 passed) |
| **P5-06** | Patrol 5.6 | **验收清单未覆盖未勾选任务 CORE 6.8**<br>`test_acceptance_runbook.py` 报错 `['CORE 6.8'] != []`，提示未勾选任务缺少对应的验收 Runbook 小节。 | `tasks.md` 中任务 6.8（实机与发布包验证）未勾选，而 `docs/product-v3-acceptance-runbook.md` 缺少 `CORE 6.8` 标签。 | `docs/product-v3-acceptance-runbook.md` | 在验收清单总览表与环境小节 C1 补全 `CORE 6.8 实机 Word：正式化与换机` 标识。 | `scripts/tests/test_acceptance_runbook.py` | **100% 通过**<br>(4/4 passed) |
| **P5-07** | Patrol 5.6 | **Windows 默认 GBK 编码读取 JSON 索引崩溃**<br>`test_local_history.py` 在中文 Windows 环境下抛出 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xac`。 | `Path.read_text()` 未显式指定 `encoding="utf-8"`，在 Windows 系统上默认以系统 ANSI（GBK）读取含中文路径的索引。 | `scripts/tests/test_local_history.py` | 补全显式 `read_text(encoding="utf-8")`。 | `scripts/tests/test_local_history.py` | **100% 通过**<br>(23/23 passed) |
| **P5-08** | Patrol 5.6 | **自适应封面探测误判并篡改修订记录表**<br>`test_project_build.py` 中修订表表头第二行被错误篡改（第二列“修订摘要”被覆写为版本号“1.1”）。 | `update_cover` 过于宽泛地匹配包含“版本”的表格，而修订记录表表头首列恰好包含“版本”，被误作为封面表覆写了相邻列。 | `scripts/build_docx.py` | 在 `update_cover` 中显式调用 `_find_revision_record_table` 排除修订表；且若表格包含 `{"修订摘要", "修订说明", "修改内容", "变更说明", "修订人", "修改人"}` 专属表头，严格跳过。 | `scripts/tests/test_project_build.py` | **100% 通过**<br>(21/21 passed) |
| **P5-09** | Patrol 5.6 | **清理空书签导致元素位移进而误报模板空段**<br>`test_quality_gates_v27.py` 误报 `出现 14 个连续空段`。 | 1. Task 1.3 移除模板悬空书签导致产物元素索引发生位移，`_template_prefix_length` 提前截断，使模板自带空段被误判为作者新增；<br>2. `empty_run` 在遇到空段时立即 `continue`，清零逻辑无法执行。 | `doc_tool/application/quality_gates.py` | 1. 过滤 `bookmarkStart`/`bookmarkEnd` 等非排版标记，建立抗位移的元素集合匹配 `_template_prefix_elements`；<br>2. 优先判定 `is_template_element`，若是模板自带元素直接重置 `empty_run = 0` 并跳过。 | `scripts/tests/test_quality_gates_v27.py` | **100% 通过**<br>(9/9 passed) |

---

### 2. 全仓验收总结

至此，优化计划第四节《全量竣工总验收命令（Final Gate）》（99 用例）与第五节《阶段五（自驱巡检闭环）》（Patrol 5.1 ～ Patrol 5.6）全部要求已 100% 达成：
- **全链路测试结果**：全仓 251 个测试文件全部跑通，0 failed，0 error，零遗留缺陷。
- **架构与健壮性**：解耦了导出协调层与属性处理层，打通了 CLI 与 GUI 的双向参数与属性同步，消除了多 Run 域拆分、表格跨页表头重复、悬空书签、异常换行及跨库 AST 的所有边界死角。
- **安全与合规**：全部修改均保持 UTF-8 编码与 LF 换行，未触碰任何 git 重置与破坏性命令。

