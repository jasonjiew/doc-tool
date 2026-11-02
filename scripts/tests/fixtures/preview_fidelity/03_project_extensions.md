# 项目扩展语法与当前缓冲验收夹具

## 1. 带尺寸后缀的图片

这是一张声明了宽度的项目图片：

![系统架构图](assets/images/architecture.png){width=350}

以及同时声明宽度和对齐/高度的变体：

![流程概览](assets/images/flow.png){width=500px height=300px}

## 2. 代码块内相似语法保护

代码块内部如果出现相似的图片或占位符标记，绝对不能被预处理或消除：

```markdown
![样例图片](sample.png){width=200}
{{project_version}}
> [!NOTE] 代码内的提示块标记
```

## 3. 构建占位符

正文中的构建占位符：项目版本为 {{project_version}}，构建日期为 {{build_date}}。

## 4. 提示块（Callouts / Alerts）

> [!NOTE]
> 这是说明提示块，用于背景说明或普通提醒信息。

> [!IMPORTANT]
> 这是重要提示块，说明关键约束或核心前置条件。

> [!WARNING]
> 这是警告提示块，提示潜在问题或不兼容行为。

## 5. 正文中的活动内容防护

<script>
window.__malicious_exec = true;
alert("evil");
</script>

<img src="x" onerror="window.__xss_triggered=true" />

[可执行协议测试](javascript:alert(1))

合法安全 HTML 标签保留展示：<kbd>Ctrl</kbd> + <kbd>S</kbd>。
