with open('doc_tool/ui/content/web_preview_browser.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = "    def _on_render_process_crashed(self, err_msg: str) -> None:"
replacement = """    def _on_render_process_terminated(self, status, exit_code: int) -> None:
        msg = f"WebEngine 渲染进程异常退出: status={status}, exitCode={exit_code}"
        logger.error(msg)
        self.renderProcessCrashed.emit(msg)

    def _on_render_process_crashed(self, err_msg: str) -> None:"""

if target in code and "def _on_render_process_terminated" not in code:
    code = code.replace(target, replacement, 1)
    with open('doc_tool/ui/content/web_preview_browser.py', 'w', encoding='utf-8', newline='') as f:
        f.write(code)
    print("Added _on_render_process_terminated to web_preview_browser.py")
