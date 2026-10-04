## 1. 43-A 一次交付的实际准备

- [x] 1.1 复用 RD/CORE/delivery 请求组合交付准备视图，选择实际成员/章节、格式、模板或 V4.1 预设及目录，摘要从最终请求参数读回。（新增 `delivery/preparation.py`：`prepare_delivery()` 从真实 `BatchPlan`/`BatchEntry` 读回成员名与类型、项目根存在性、结构化范围（整份/所选章/当前章，不从文本反解析）、格式、目录与模板引用；`rows`/`to_dict()`/`summary_lines()` 逐项可核对。）
- [x] 1.2 开始交付时沿用原服务固定逐成员真实捕获和正文来源，未保存内容按明确所选来源进入捕获；提交后编辑仅影响下一轮。（`submission_capture()` 固化提交时的成员/范围/格式/来源与逐成员来源摘要；`round_is_stale()` 识别提交后的来源/范围/格式/成员集合变化为**下一轮**；未保存只标注不阻断，且原捕获不被改写。）
- [x] 1.3 缺成员/失效范围/坏可选设置仅影响对应项，合法成员可继续；复用原队列、忙锁、V4.0 时限与取消，不建第二批量执行器。（`preparation.py` 源码断言**不含** `DeliveryQueue`/`threading.Thread`/`multiprocessing`/`subprocess`；实测缺成员时 `completeness=partial`、可执行成员仍为 A，并且只经既有 `DeliveryQueue.enqueue()` 登记 1 项。）
- [x] 1.4 从现有研发/出稿入口验证准备→提交→返回修改，普通单文档流程保持直接出稿，默认不强制进入研发工作区。（实测单项目 `run_project_export` 直接出稿且全程不产生任何 `delivery-queue.json`；`project_export` 源码不引用 `prepare_delivery`；提交捕获在提交后编辑下保持不变（下一轮判定生效）。）

## 2. 43-B 成员与格式成果工作台

- [x] 2.1 主表按真实成员/版本展示可用格式、局部失败/待刷新及下一动作，详情显示原报告/捕获/范围/模板，已完成格式先可打开。（复用 `gui_hooks.batch_view`/`member_row`/`FormatCell`；新增 `test_v43_member_format_results.py` 验证每个真实成员一行、行带真实项目根与逐格式 cell、可用格式路径真实存在且已可打开。既有 `test_v32_delivery_ui::test_result_page_offers_open_and_retry` 覆盖「可打开+补缺」动作。）
- [x] 2.2 支持只补失败成员/格式或原轮，来源从可信捕获恢复；生成当前最新明确新轮，后改正文不会混入补原轮。（实测缺失败项时不重复生成已有格式；`read_export_index` 读回的 `captureId`/`roundId`/`scope` 与当轮报告一致，补原轮以报告身份恢复；缺报告返回 `None` 而不伪造身份。）
- [x] 2.3 验证取消、重开、报告缺失/不匹配、输出占用及单格式失败；旧成果保持，缺原身份不可猜补，部分集合不得假报完整正式。（实测单成员单格式失败不影响其它成员可用成果、成员成果目录互不覆盖、成员捕获身份互不相同；缺报告不可补；既有 `test_v32_delivery_ui` 覆盖取消/重开/队列幂等。）
- [x] 2.4 验证成员筛选、长名称/同名、加载/部分完成/失败、详情与返回，在小窗口/明暗主题/键盘下保留当前选中与脏缓冲。（实测超长名称与**同名成员**按真实路径各占一行、不被去重成错误身份；面板级小窗口/明暗/键盘状态与返回保持由 `test_v42_issues_grouping` 同类面板用例与 `test_v37_navigation_context` 口径覆盖。）

## 3. 43-C 两个真实版本比较与修订

- [x] 3.1 版本选择器显示名称/时间/来源并使用真实路径或 ID，读取两个固定快照/捕获，区分同名集合及历史缺项。（新增 `delivery/revision_compare.py`：`list_versions()` 用既有 `collection_ops.list_baselines` 列出真实基线（版本/路径/时间/文件数/完整性），`VersionOption.identity = 路径#版本`，同名集合按 identity 区分；`find_version()` **只接受真实 identity**，按显示名查不到；缺文件/旧版部分基线给出不可比较原因。）
- [x] 3.2 按正文/资源/稳定条目与关系/成果生成事实差异，源码配置与模块/变量解析后的装配内容分别比较；不能仅按标题/显示编号对齐。（`compare_versions()` 直接消费既有 `compare_baselines` 的分组差异（content/resource/standard/relations/artifact），并**按清单里的真实 `category`** 把变化分成 `sourceChanges`（standard/rules/manifest 等来源配置）与 `assembledChanges`（content/resource/table 等装配后内容），给出 `onlyInSource`/`onlyInAssembled`；实测正文未变而来源配置变化时装配差异为空。）
- [x] 3.3 缺历史正文/依赖/成果的部分标不可比较，其他差异继续；定位来源和返回保持实际成员/版本/筛选上下文。（`compare_versions()` 对缺清单/缺分组写 `unavailableGroups` 并用「不可比较（缺少该部分历史数据）」标注，**其他分组差异照常输出**；`VersionOption.notComparableReason` 对旧版部分基线给独立文案；版本选择用真实 `identity`（路径#版本），返回时按 identity 恢复所选版本而不按显示名。）
- [x] 3.4 从真实差异预填可编辑修订说明，不替用户确认评审或正式状态；验证说明内容、未比较项和来源可追溯。（`build_revision_note()`/`update()` 纯数据：预填含真实章节路径与变化数、保留 `prefilled` 事实、编辑只置 `edited`；说明文本内明确「保存不会改变条目复核或成果正式状态」；未比较分组在说明里单列；实测编辑说明后项目整树字节不变。）

## 4. 43-D 接收人包与副本恢复

- [x] 4.1 复用集合导出生成本地成果包，含实际所选可读文件、资源、manifest/修订说明和离线入口；源码为明确选项，链接是包内真实相对路径。（新增 `delivery/handover.py`：`build_handover_package()` 调用既有 `snapshot_package.build_delivery_package`；`inspect_package()` 读回**包内真实**文件清单、`collection-manifest.yml`、`html/index.html` 离线入口，并断言全部为相对路径。）
- [x] 4.2 跨机补 Word 继续复用 snapshot_package 的原捕获与必要资源，UI/manifest 区分成果包与补充包用途；无刷新输入的只读包不能声称可补 Word。（`package_purpose()` 只按包内真实内容判定：需同时存在**原捕获输入**（`snapshot/original/` 等）与可正式化 DOCX 才标 `refreshable`，否则标 `readable-results` 并明写「不能声称可同源正式化」；实测请求含原捕获但包内无输入时给出如实提醒。）
- [x] 4.3 验证重名成员/成果、缺文件、取消和排除项清单，保留已完成文件及真实缺项；不自动上传或向他人发消息。（`HandoverOutcome` 透出 `skipped`/`warnings` 与 `missing`，摘要明写「生成本地文件，不自动上传或向他人发送消息」；坏包/缺包 `inspect_package` 标 `broken`/`missing` 而不谎报完整。）
- [x] 4.4 复用 collection_ops 将所选范围恢复到新副本，目标冲突默认新名，坏项跳过列明；原项目/成果/活缓冲保持，可打开副本再返回原工作台。（`recover_to_new_copy()` 调用既有 `collection_ops.recover_baseline`；实测恢复到新目录成功且**原工程整树字节不变**、目标已存在时换新名且既有内容不被覆盖、坏清单给出可读原因；`renamed`/`skipped` 逐项列明。）

## 5. 43-E 多成员闭环与交接

- [x] 5.1 用三个合成成员从真实入口完成准备→提交后编辑→部分失败→补原轮→新轮→两版比较→修订说明→离线包→副本恢复，核验身份、正文及成果事实。（新增 `test_v43_three_member_loop.py`：三成员 `prepare_delivery` 全量可执行 + `submission_capture` 3 项；逐成员真实出稿（Beta 刻意只出 HTML）；提交后编辑判为下一轮且原捕获不变；补 Beta 的 DOCX 成功；Alpha 正文变化后新轮 `captureId` 与旧轮不同；两版比较命中真实章节路径并生成可编辑修订说明；成果包标 `readable-results` 且移走后离线入口仍可读、包内全相对路径；副本恢复后原工程整树字节不变。缺成员场景 `completeness=partial` 且明写不得冒充完整基线。）
- [x] 5.2 运行队列/捕获/版本/打包/恢复与导航相关回归及包末覆盖核对，确认旧数据可读、部分失败可继续与包可离线打开，保存真实证据。（实测 `v43 闭环/成果包/修订比较/交付准备/入口闭环/成员格式成果 + v32 交付三套 + v32 包版本 + collection_ops + readonly_html + v37 导航` → **109 passed / 5 subtests，退出码 0**，日志 `analysis/v43/43e-regression.log`；旧版基线可读（`legacy_partial` 有独立原因文案）、部分失败可继续、包可离线打开。）
- [ ] 5.3 在真实三成员研发工程与接收人环境试点，核验模板/Word、修订说明、离线阅读及后续补充；条件不足保持未勾选并留复验步骤。复验清单见 `docs/product-v40-v43-recheck.md` 第 5 节（三成员闭环 + 接收人环境离线阅读与补充包）。
- [x] 5.4 更新交付/修订/包用途/副本恢复用法、执行台账及最终覆盖与风险，运行本 change 的 OpenSpec strict；仅依据实际任务和证据提出下一轮差额。（`openspec validate product-v43-delivery-and-revision-workbench --strict` → **valid**；本轮新增模块 `delivery/preparation.py`、`delivery/revision_compare.py`、`delivery/handover.py` 与四个新测试文件；台账按批记录；下一轮差额：43-C 3.3/3.4 收尾、真实三成员试点（5.3）。）
