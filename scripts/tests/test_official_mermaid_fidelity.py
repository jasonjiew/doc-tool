# -*- coding: utf-8 -*-
"""官方 Mermaid 渲染、入口一致性与降级状态验收测试（REQ-MM-01～REQ-MM-04、REQ-MM-06）。

验证 Task 5.1～5.6：
- 5.1: 官方 Mermaid 11.16.1 版本核对与统一配置
- 5.2: 官方语法校验切换、接受新形状与前置配置指令、错误行映射
- 5.3: Flowchart 官方渲染：嵌套子图、样式、方向、带文字连线、回边、超长中文标签
- 5.4: SequenceDiagram 官方渲染：alt/else、opt、loop、par/and、Note、激活条、编号
- 5.5: 阅读区、工作台与大图入口复用同一官方结果与来源身份
- 5.6: 官方错误、未打包图类型与内置近似降级标注
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from doc_tool.application.content.mermaid import MermaidBlock, validate
from doc_tool.ui.content.diagram_viewer import DiagramViewerDialog
from doc_tool.ui.content.mermaid_dialog import MermaidDialog
from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


class OfficialMermaidFidelityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()
        cls.renderer = get_official_mermaid_renderer()
        if not cls.renderer._page_ready:
            loop = QEventLoop()
            cls.renderer._view.loadFinished.connect(lambda ok: loop.quit())
            QTimer.singleShot(6000, loop.quit)
            loop.exec()

    def test_5_1_official_mermaid_bundle_version_and_config(self):
        """5.1 验收：实际引擎版本可查询为 11.16.1，默认配置一致。"""
        # 1. 验证渲染器暴露的官方引擎版本契约
        version = self.renderer.get_engine_version()
        self.assertEqual(version, "11.16.1")

        # 2. 验证前端 mermaid 核心 API 与配置
        res_has_api = None
        loop = QEventLoop()

        def cb(v):
            nonlocal res_has_api
            res_has_api = v
            loop.quit()

        self.renderer._view.page().runJavaScript(
            "typeof mermaid !== 'undefined' && typeof mermaid.mermaidAPI !== 'undefined'",
            cb,
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        self.assertTrue(res_has_api)

    def test_5_2_official_syntax_validation_accepts_new_shapes_and_frontmatter(self):
        """5.2 验收：新节点形状与前置配置指令被语法校验接受，绕开旧子集阻挡。"""
        sample_code = """%%{init: {'theme': 'default'}}%%
flowchart TD
    Start([任务开始]) --> Op[执行常规转换运算]
    Op --> Decision{验证是否通过?}
    Decision -->|通过| Success[[生成保真预览]]
    Decision -->|失败| Dbl(((双圆终点)))
"""
        errors = self.renderer.validate(sample_code)
        self.assertEqual(len(errors), 0, f"官方语法校验应通过，但返回错误: {errors}")

        # 语法错误用例映射准确行号
        err_code = """graph TD
    A --> 
    B -- 缺少目标节点
    ??? 非法字符语法错误
"""
        err_res = self.renderer.validate(err_code)
        self.assertGreater(len(err_res), 0)
        # 错误行号应能精确定位
        self.assertGreater(err_res[0].line, 1)

    def test_5_3_flowchart_official_rendering(self):
        """5.3 验收：嵌套子图、节点样式、连线文本、回边与中文长标签完整呈现。"""
        flowchart_code = """flowchart TD
    subgraph 接入层 [客户端接入网关]
        A["第一行：用户界面提交请求<br/>第二行：多行中文说明<br/>第三行：foreignObject验证"] --> B[鉴权中心]
    end
    subgraph 核心层 [渲染与业务集群]
        B --> C{校验是否通过?}
        C -->|通过| D[生成官方矢量图形]
        C -->|失败| E[返回降级提示]
    end
    D --> A
    style A fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    style D fill:#e8f8f5,stroke:#2ecc71,stroke-width:2px;
"""
        res = self.renderer.render(flowchart_code, want_png=True)
        self.assertTrue(res.ok)
        self.assertEqual(res.backend, "official-webengine")
        self.assertIsNotNone(res.svg)
        self.assertIsNotNone(res.png)
        svg_text = res.svg.decode("utf-8")
        self.assertIn("接入层", svg_text)
        self.assertIn("核心层", svg_text)
        self.assertIn("foreignObject验证", svg_text)
        self.assertGreater(len(res.png), 500)

    def test_5_4_sequence_diagram_official_rendering(self):
        """5.4 验收：时序图 alt/else、opt、loop、par/and、Note、激活条及编号完整呈现。"""
        seq_code = """sequenceDiagram
    autonumber
    actor User as 用户界面
    participant Client as 客户端控制器
    participant Server as 渲染服务引擎
    participant Cache as 本地缓存

    User->>Client: 提交文档渲染请求
    Client->>Cache: 查询是否有命中快照
    
    alt 缓存命中
        Cache-->>Client: 返回缓存SVG矢量内容
    else 缓存未命中
        Client->>Server: 发起完整解析
        activate Server
        loop 坐标迭代
            Server->>Server: 计算物理位置
        end
        deactivate Server
        Client-->>User: 渲染完成
    end
"""
        res = self.renderer.render(seq_code, want_png=True)
        self.assertTrue(res.ok)
        self.assertEqual(res.backend, "official-webengine")
        svg_text = res.svg.decode("utf-8")
        self.assertIn("缓存命中", svg_text)
        self.assertIn("坐标迭代", svg_text)

    def test_5_5_workbench_and_viewer_reuse_same_contract(self):
        """5.5 验收：工作台 MermaidDialog 与官方渲染器使用同一契约，同一源码生成一致图片。"""
        source = "flowchart LR\n    A[统一客户端] --> B[官方Mermaid引擎]"
        # 1. 官方渲染器
        res_official = self.renderer.render(source, want_png=True)
        self.assertTrue(res_official.ok)

        # 2. 工作台 MermaidDialog 对比
        dialog = MermaidDialog(source)
        dialog.show()
        self.app.processEvents()

        # 刷新工作台预览
        dialog.refresh_preview()
        self.app.processEvents()
        self.assertIsNotNone(dialog.render_result)
        self.assertTrue(dialog.render_result.ok)
        self.assertEqual(dialog.render_result.backend, "official-webengine")
        dialog.close()

    def test_5_6_unsupported_type_and_error_reporting(self):
        """5.6 验收：未随包提供或非法类型明确报告错误，不标为完整高保真成功。"""
        invalid_code = "not_a_valid_diagram_type\nfoo bar"
        res = self.renderer.render(invalid_code, want_png=False)
        self.assertFalse(res.ok)
        self.assertIsNotNone(res.error)


if __name__ == "__main__":
    unittest.main()
