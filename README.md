# 康尚健康云 Word 文档自动合并

本目录采用“Word 模板管公司格式，目录树管章节结构，Markdown 管业务内容”的方式维护需求说明书和详细设计说明书。开发人员日常只需增加、修改或删除 Markdown（以及 Markdown 引用的截图），然后双击最外层生成入口。

## 1. 最常用操作

在本目录最外层双击：

- `生成需求说明书.cmd`：只生成需求说明书；
- `生成详细设计说明书.cmd`：只生成详细设计说明书；
- `全部生成.cmd`：依次生成两份文档。

入口会自动执行：章节/资源预检 → 构建 DOCX → 严格校验 → Microsoft Word 独立进程刷新 TOC、NUMPAGES 和页码 → 刷新后再次严格校验。任一步失败都会显示 `[FAIL]` 并返回非零退出码，不会假报成功，也不会用失败结果覆盖上一次有效输出。

生成结果位于 `output/`。文件名由配置中的文档编号、名称和版本自动组成，例如：

```text
KF-2090-1-001 康尚健康云软件需求说明书(3.8)-REBUILD.docx
KF-2090-1-006 康尚健康云系统详细设计说明书(2.5)-REBUILD.docx
```

## 2. 章节目录就是 Word 层级

期望结构如下：

```text
content/requirement/
└─ 第3章 功能需求/                 # Word Heading 1
   └─ 3.1 KSHC/                   # Word Heading 2
      ├─ _index.md                # 可选：3.1 自身正文
      ├─ 3.1.1 登录页.md           # Word Heading 3 + 文件正文
      ├─ 3.1.2 首页.md
      └─ 3.1.3 注册.md
```

规则：

- 文件夹和 Markdown 文件名必须带完整章节编号，编号决定排序与层级；
- 一级目录使用 `第N章 标题`，二级及以下使用 `N.N 标题`；
- 同一层编号必须从 1 连续递增，不能重复、跳号或使用错误父编号；
- 构建发现 `3.1.99` 之类跳号时会失败，并明确提示当前实际应为 `3.1.14`；
- 文件名中的编号不写入标题正文，显示编号仍由公司 Word 模板的多级编号体系生成；
- Windows 文件名不能使用 `/ : * ? " < > | \`。标题需要这些字符时，在文件名中使用对应全角字符，生成器会在 Word 标题中还原。

### `_index.md` 的含义

当一个文件夹标题本身有正文，而且后面还有子章节时，把父标题正文写在该文件夹的 `_index.md` 中：

```text
6.5 呼吸机接口/
├─ _index.md                      # 6.5 标题之后、6.5.1 之前的概述/表格
├─ 6.5.1 接口说明.md
└─ 6.5.2 参数说明.md
```

`_index.md` 内容会严格插入在父标题之后、第一个子标题之前。不要把父章节概述复制到第一个子章节中。

## 3. 新增、修改、删除章节

### 新增

例如 `3.1 KSHC` 当前最后一个文件是 `3.1.13 出厂管理.md`，新增注册功能时直接创建：

```text
content/requirement/第3章 功能需求/3.1 KSHC/3.1.14 注册.md
```

写完后双击 `生成需求说明书.cmd` 或 `全部生成.cmd`。无需在 YAML 中登记新章节。

### 修改

直接编辑对应 Markdown。重新生成后，正文、普通表格、图片和文件内更深层标题会按原位置更新。

### 删除

删除对应 Markdown 或章节文件夹，然后重新生成。若删除的是中间编号，必须同时把后续同级文件连续重编号；若删除的是最后一个编号则无需调整其他文件。

## 4. Markdown 写法

### 正文与换行

普通文本行生成正文段落。需要同一 Word 段落内换行时写：

```markdown
A<br>B
```

输出使用真正的 Word 换行节点，不会把 `<br>` 字样显示在文档中。

### 文件内更深层标题

`3.1.3 注册.md` 自身已经代表 Heading 3，文件内部只能从 Heading 4 开始：

```markdown
#### 验收说明
```

内部标题层级不深于文件章节层级时，构建会失败。

### 普通表格

```markdown
| 字段 | 说明 |
| --- | --- |
| 状态 | A\|B<br>下一行 |
```

- 单元格中的 `\|` 表示文字竖线，不会被拆成新单元格；
- `\\` 表示一个反斜杠；
- `<br>` 表示单元格内真实 Word 换行。

### 截图和普通图片

日常截图只需放入相应资源目录并使用标准 Markdown 引用：

```markdown
![登录页截图](images/login.png)
```

尺寸不是必填项。未写尺寸时，生成器按图片 DPI 和原始宽高比计算自然尺寸；超出页面可用宽度时只做等比缩小，不拉伸、不放大。

确需固定显示尺寸时可选写：

```markdown
![登录页截图](images/login.png =800x450)
```

图片不存在、损坏、越出资源目录或 relationship/媒体部件不完整时，构建或校验会直接失败。构建器会按图片内容哈希复用媒体，避免同一图片重复打包。

### 复杂表格

原 Word 中无法无损表达为 Markdown 的合并单元格、复杂边框等表格保存在 `assets/<type>/tables/*.xml`，Markdown 中保留 `<!-- TABLE:... -->` 引用。日常可移动或删除完整引用，但不要手工改 XML 内部结构。

如果确实需要修改复杂表格，建议先在 Word 中完成表格修改，再使用 `scripts/migration/` 下的迁移工具重新提取并做基线验收。复杂表格 XML 缺失、损坏或引用无效时会失败，不会静默跳过。

## 5. 配置与版本

配置文件：

- `config/requirement.yml`
- `config/design.yml`

`documentNo`、`documentName`、`documentVersion` 是封面与输出文件名的唯一配置来源。修改版本时只改配置，不要手工改模板封面或输出文件名。构建器会同步封面编号/版本并保留 `NUMPAGES` 字段，Word 刷新后写入实际总页数。

`baseline.file` 只用于首次迁移验收。未来有意修改业务 Markdown 后，日常入口不会要求内容仍与旧版原 Word 相同；发布前可按项目策略选择新的受控基线。

## 6. 环境要求

- Windows；
- Python 3 已加入 `PATH`；
- Python 包：`pyyaml`、`lxml`、`pillow`、`pywin32`；
- 本机安装 Microsoft Word。

安装缺失依赖：

```powershell
python -m pip install pyyaml lxml pillow pywin32
```

Word 刷新使用 `DispatchEx` 启动本次专用隐藏进程，不复用、关闭或杀死用户已经打开的 Word。超时值来自配置 `refresh.timeoutSeconds`；超时只终止本次工作进程并返回失败。刷新完成后还会只读复打开一次，以确认 Word 不需要修复文档。

无 Word 的诊断环境可在命令行显式使用 `--skip-word-refresh`，但这种结果只算构建级验证，不能作为正式 Word 验收通过。

## 7. 校验和测试

日常入口已经自动校验。需要单独运行时：

```powershell
python scripts/build_docx.py all
python scripts/validate_docx.py all
python scripts/refresh_fields.py all
python scripts/validate_docx.py all --require-refreshed
```

首次迁移闭环还可与原 Word 严格比较：

```powershell
python scripts/validate_docx.py all --baseline
```

自动测试：

```powershell
python scripts/tests/run_tests.py
```

覆盖范围包括：`_index` 父正文顺序、连续编号、缺图、普通表格转义、真实 Word 换行、自然尺寸图片、增加/修改/删除迭代，以及空正文、删/换标题、正文篡改、父正文错位、普通/复杂表格损坏、图片关系缺失、非法 OOXML 和重复媒体等负向门禁。

## 8. 模板、迁移和历史文件

```text
templates/                  公司 Word 模板骨架，日常不要改
content/                    日常维护的 Markdown 章节树
assets/                     日常 Markdown 引用的图片和复杂表格资源
config/                     文档配置
scripts/                    日常核心构建/校验/刷新脚本
scripts/migration/          首次导入或重新提取时才使用
scripts/diagnostics/        问题分析脚本，不参与日常生成
migration/legacy/           旧 BAT、旧映射元数据等历史证据
output/                     最终 DOCX
```

`migration/legacy/binary-bat/` 中的旧 `.bat` 含安全软件封装/NUL 字节，只作历史留存，禁止作为入口。日常只使用最外层三个纯文本 `.cmd`。

## 9. 日常边界

可以：

- 增加、修改、删除 Markdown 章节；
- 在 Markdown 中写正文、内部标题、普通表格；
- 放入截图并用标准 Markdown 引用；
- 通过 `_index.md` 维护父章节自身正文；
- 修改配置中的文档版本后重新生成。

不可以：

- 手工编辑 `output/` 后把它当作内容源；
- 跳过报错继续使用失败产物；
- 在同级章节中跳号或重复编号；
- 把父章节正文塞进第一个子章节；
- 删除 Markdown 引用的图片或复杂表格 XML；
- 使用 `migration/legacy` 中的旧 BAT；
- 在未完成 Word 刷新与视觉检查时宣称正式 QMS 文档验收通过。
