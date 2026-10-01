from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel
from doc_tool.application.content.authoring_outline import buffer_summary, COUNT_DEFINITION


class OutlinePanel(QWidget):
    def __init__(self, editor, locate, parent=None):
        super().__init__(parent)
        self.editor, self.locate = editor, locate
        self.summary = None
        layout = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('过滤当前章标题')
        self.items = QListWidget()
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setToolTip(COUNT_DEFINITION)
        layout.addWidget(self.filter)
        layout.addWidget(self.items, 1)
        layout.addWidget(self.stats)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        editor.textChanged.connect(lambda: self.timer.start())
        editor.selectionChanged.connect(self.selection_changed)
        editor.cursorPositionChanged.connect(self.highlight_current)
        self.filter.textChanged.connect(self.populate)
        self.items.itemClicked.connect(lambda item: self.locate(item.data(Qt.UserRole)))
        self.refresh()

    def refresh(self):
        self.summary = buffer_summary(self.editor.toPlainText(), self.editor.textCursor().selectedText())
        self.populate()
        self.selection_changed()

    def populate(self):
        self.items.clear()
        query = self.filter.text().casefold()
        for level, title, line in (self.summary or {}).get('headings', []):
            if query not in title.casefold(): continue
            item = QListWidgetItem('  ' * (level-1) + title)
            item.setData(Qt.UserRole, line)
            item.setToolTip('源行 ' + str(line))
            self.items.addItem(item)
        self.highlight_current()

    def selection_changed(self):
        if self.summary is None: return
        self.summary['selection'] = len(self.editor.textCursor().selectedText())
        s = self.summary
        self.stats.setText(f'原始字符 {s["raw"]} · 选区 {s["selection"]}\n正文 CJK {s["cjk"]} · ASCII token {s["ascii"]}\n标题 {len(s["headings"])} · 表 {s["tables"]} · 图 {s["images"]}\n计数定义见悬停提示')

    def highlight_current(self):
        current = self.editor.textCursor().blockNumber() + 1
        headings = (self.summary or {}).get('headings', [])
        line = max((h[2] for h in headings if h[2] <= current), default=0)
        for n in range(self.items.count()):
            item = self.items.item(n)
            font = item.font()
            font.setBold(item.data(Qt.UserRole) == line)
            item.setFont(font)
