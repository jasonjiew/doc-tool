# -*- coding: utf-8 -*-
"""一次性真机探针：A 组新方向的 Word COM 入参与 SaveAs/导出格式常量。

按仓库既定工作方式，任何 Word 侧新方向落地前先在本机验证：
1. RTF/ODT/MHT 能被 Word 静默打开并 SaveAs2 成 DOCX（wdFormatXMLDocument=12）；
2. HTML 打开后应用 A4 版式再 ExportAsFixedFormat，页范围参数
   （Range=wdExportFromTo=3 + From/To 关键字）能否工作；
3. DOCX 同套页范围导出参数复验。

产物只校验「存在且非零」——亿赛通 DocGuard 环境下 Word 写出的 PDF 对 Python
是密文，这是本仓库的硬约束。运行：python scripts/probes/probe_group_a.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"

RTF_TEXT = (
    "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 SimSun;}}"
    "\\f0\\fs24 \\u25506\\u25506\\u26631\\u39064\\par"
    " probe body \\par}"
)

ODT_CONTENT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-content '
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'office:version="1.2">'
    "<office:body><office:text>"
    '<text:h text:outline-level="1">Probe Heading</text:h>'
    "<text:p>probe body paragraph</text:p>"
    "</office:text></office:body></office:document-content>"
)

ODT_MANIFEST = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<manifest:manifest "
    'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
    'manifest:version="1.2">'
    '<manifest:file-entry manifest:full-path="/" '
    'manifest:media-type="application/vnd.oasis.opendocument.text"/>'
    '<manifest:file-entry manifest:full-path="content.xml" '
    'manifest:media-type="text/xml"/>'
    "</manifest:manifest>"
)

def make_mht_variants(dir_path: Path) -> dict:
    """Word 的 MHT 解析器对 MIME 头比较挑剔，一次给三种合成变体。"""
    html_body = (
        "<html><body><h1>Probe Heading</h1><p>probe body paragraph</p></body></html>"
    )
    out = {}

    # 变体 A：multipart/related + type="text/html" + quoted-printable
    qp_body = "".join(
        ("={0:02X}".format(byte) if byte in b"=<>\r\n" else chr(byte))
        for byte in html_body.encode("utf-8")
    )
    out["a"] = (
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/related; type="text/html"; '
        'boundary="----=_NextPart_probe"\r\n\r\n'
        "------=_NextPart_probe\r\n"
        'Content-Type: text/html; charset="utf-8"\r\n'
        "Content-Transfer-Encoding: quoted-printable\r\n"
        "Content-Location: file:///C:/probe/doc.html\r\n\r\n"
        + qp_body + "\r\n"
        "------=_NextPart_probe--\r\n"
    )

    # 变体 B：单部分 text/html（无 multipart 信封）
    out["b"] = (
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/html; charset="utf-8"\r\n'
        "Content-Transfer-Encoding: 8bit\r\n\r\n" + html_body + "\r\n"
    )

    # 变体 C：multipart + base64 正文
    import base64

    out["c"] = (
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/related; type="text/html"; '
        'boundary="----=_NextPart_probe"\r\n\r\n'
        "------=_NextPart_probe\r\n"
        'Content-Type: text/html; charset="utf-8"\r\n'
        "Content-Transfer-Encoding: base64\r\n"
        "Content-Location: file:///C:/probe/doc.html\r\n\r\n"
        + base64.b64encode(html_body.encode("utf-8")).decode("ascii") + "\r\n"
        "------=_NextPart_probe--\r\n"
    )
    paths = {}
    for key, text in out.items():
        path = dir_path / ("probe_mht_" + key + ".mht")
        path.write_text(text, encoding="ascii")
        paths["mht_" + key] = path
    return paths


def make_odt(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as package:
        # mimetype 必须是首个条目且不压缩（ODF 规范）。
        package.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/vnd.oasis.opendocument.text",
            zipfile.ZIP_STORED,
        )
        package.writestr("META-INF/manifest.xml", ODT_MANIFEST, zipfile.ZIP_DEFLATED)
        package.writestr("content.xml", ODT_CONTENT, zipfile.ZIP_DEFLATED)


def main() -> int:
    from doc_tool.application.word_check import check_word_available

    if not check_word_available(dispatch_check=True).available:
        print("[SKIP] 本机 Word COM 不可用（非交互会话或未装 Word）")
        return 0

    import os

    import pythoncom
    import win32com.client

    workspace = Path(tempfile.mkdtemp(prefix="probe-group-a-"))
    results: list = []
    word = None
    try:
        sources = {}
        (workspace / "probe.rtf").write_text(RTF_TEXT, encoding="ascii")
        sources["rtf"] = workspace / "probe.rtf"
        make_odt(workspace / "probe.odt")
        sources["odt"] = workspace / "probe.odt"
        sources.update(make_mht_variants(workspace))
        html = workspace / "probe.html"
        html.write_text(
            "<html><head><meta charset='utf-8'><style>h1{font-size:16pt}</style>"
            "</head><body><h1>Probe Heading</h1><p>page one</p>"
            '<p style="page-break-before:always">page two</p>'
            '<p style="page-break-before:always">page three</p></body></html>',
            encoding="utf-8",
        )
        sources["html"] = html
        docx = workspace / "probe.docx"
        shutil.copy(TEMPLATE, docx)
        sources["docx"] = docx

        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            word.AutomationSecurity = 3
        except Exception:
            pass

        def open_doc(path: Path):
            return word.Documents.Open(
                FileName=os.path.abspath(str(path)),
                ConfirmConversions=False,
                ReadOnly=False,
                AddToRecentFiles=False,
                Visible=False,
            )

        # --- 1. RTF/ODT 打开 + SaveAs2 DOCX；MHT 逐变体尝试 ---
        for name in ("rtf", "odt", "mht_a", "mht_b", "mht_c"):
            target = workspace / ("out_" + name + ".docx")
            try:
                doc = open_doc(sources[name])
                doc.SaveAs2(str(target), FileFormat=12)  # wdFormatXMLDocument
                doc.Close(SaveChanges=False)
                ok = target.is_file() and target.stat().st_size > 0
                results.append((name + " -> SaveAs2 docx", ok, str(target.name)))
            except Exception as exc:
                results.append((name + " -> SaveAs2 docx", False, repr(exc)[:160]))

        # --- 2. HTML 打开 → A4 版式 → 页范围导出 PDF ---
        try:
            doc = open_doc(sources["html"])
            setup = doc.PageSetup
            setup.PaperSize = 7  # wdPaperA4
            setup.Orientation = 0
            pages = int(doc.ComputeStatistics(2))  # wdStatisticPages
            target = workspace / "out_html_p1.pdf"
            doc.ExportAsFixedFormat(
                str(target), 17, Range=3, From=1, To=1
            )  # wdExportFormatPDF, wdExportFromTo
            doc.Close(SaveChanges=False)
            ok = target.is_file() and target.stat().st_size > 0
            results.append(
                ("html -> PDF 页范围(1-1)", ok, "pages={0}".format(pages))
            )
        except Exception as exc:
            results.append(("html -> PDF 页范围(1-1)", False, repr(exc)[:160]))

        # --- 3. DOCX 打开 → 页范围导出（复验同套关键字） ---
        try:
            doc = open_doc(sources["docx"])
            pages = int(doc.ComputeStatistics(2))
            target = workspace / "out_docx_p1.pdf"
            doc.ExportAsFixedFormat(str(target), 17, Range=3, From=1, To=1)
            doc.Close(SaveChanges=False)
            ok = target.is_file() and target.stat().st_size > 0
            results.append(("docx -> PDF 页范围(1-1)", ok, "pages={0}".format(pages)))
        except Exception as exc:
            results.append(("docx -> PDF 页范围(1-1)", False, repr(exc)[:160]))
    finally:
        if word is not None:
            try:
                word.Quit(SaveChanges=False)
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

    print("--- 探针结论 ---")
    failed = 0
    for name, ok, detail in results:
        print("[{0}] {1}  {2}".format("PASS" if ok else "FAIL", name, detail))
        failed += 0 if ok else 1
    shutil.rmtree(workspace, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
