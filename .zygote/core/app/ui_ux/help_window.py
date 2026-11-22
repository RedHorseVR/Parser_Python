"""The help window: shows a help page inside Zygote (no browser, no process). Zygote help is an HTML page that
ships with Zygote; project help is the open project's app_tree\\help\\README.md, drawn as formatted text.

The project help can be edited in the same window (Edit): split view, the raw Markdown on the left and the drawn page on the right,
Save / Cancel. Save keeps what was there in zip\\edits first (the same snapshot as Contents). No process starts; the close guard is the
same question Contents asks."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

import crashlog
from functional import core
from ui_ux.theme import Theme


class HelpWindow(QDialog):
    def __init__(self, title, parent=None, editable=None):
        """`editable` = (project, path) of a help file that may be edited here; None for a page that cannot be."""
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.resize(780, 660)
        self.editable = editable
        self.info = None                                         # {'text', 'bom', 'newline'} of the file while it is edited
        self.saved_snapshots = []
        self.browser = self.make_browser()
        self.editor = QPlainTextEdit()                           # edit mode: the raw Markdown
        font = self.editor.font()
        font.setFamily('Consolas')
        self.editor.setFont(font)
        self.preview = self.make_browser()                       # edit mode: the same page drawn, following every key
        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(self.editor)
        self.split.addWidget(self.preview)
        self.split.setSizes([390, 390])
        self.pages = QStackedWidget()
        self.pages.addWidget(self.browser)
        self.pages.addWidget(self.split)
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages, 1)
        self.view_row = QWidget()                                # buttons of view mode
        view = QHBoxLayout(self.view_row)
        view.setContentsMargins(0, 0, 0, 0)
        view.addStretch(1)
        self.edit_button = None
        if editable is not None:                                  # only the project help has an Edit button
            self.edit_button = QPushButton('Edit')
            self.edit_button.setToolTip('Edit this page here: raw text on the left, the page on the right')
            self.edit_button.clicked.connect(self.start_editing)
            view.addWidget(self.edit_button)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        view.addWidget(close)
        self.edit_row = QWidget()                                # buttons of edit mode
        edit = QHBoxLayout(self.edit_row)
        edit.setContentsMargins(0, 0, 0, 0)
        edit.addStretch(1)
        self.save_button = QPushButton('Save')
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.setToolTip('Leave the editor (asks first when there are unsaved changes)')
        self.cancel_button.clicked.connect(self.stop_editing)
        edit.addWidget(self.save_button)
        edit.addWidget(self.cancel_button)
        layout.addWidget(self.view_row)
        layout.addWidget(self.edit_row)
        self.edit_row.hide()
        self.editor.textChanged.connect(self.redraw)
        self.editor.document().modificationChanged.connect(self.save_button.setEnabled)

    def make_browser(self):
        browser = QTextBrowser()
        browser.setOpenLinks(False)                              # no link starts anything; a #link scrolls inside the page
        browser.anchorClicked.connect(lambda url, b=browser: self.follow(url, b))
        colors = Theme.colors()
        browser.document().setDefaultStyleSheet(
            f"a {{ color: {colors['sacred']}; }} h1, h2, h3 {{ color: {colors['bright']}; }} "
            f"code, pre {{ background-color: {colors['title_bg']}; }} td, th {{ padding: 3px 8px; }}")
        return browser

    def follow(self, url, browser=None):
        if url.hasFragment() and not url.path():
            (browser or self.browser).scrollToAnchor(url.fragment())

    # ---- edit mode ------------------------------------------------------------------------------------------------------
    def is_editing(self):
        return self.pages.currentWidget() is self.split

    def start_editing(self):
        """Edit: read the file again (it may have changed) and switch this window into the split editor."""
        project, path = self.editable
        try:
            if not core.editable_in(project, path):
                raise core.ZygoteError(f'{path.name} is read-only here (outside the project, or in a folder that belongs to this computer).')
            self.info = core.read_text_file(path)
        except core.ZygoteError as error:
            QMessageBox.critical(self, crashlog.error_title(), str(error))
            return
        self.editor.setPlainText(self.info['text'])
        self.editor.document().setModified(False)
        self.save_button.setEnabled(False)
        self.pages.setCurrentWidget(self.split)
        self.view_row.hide()
        self.edit_row.show()
        self.redraw()
        self.editor.setFocus()

    def redraw(self):
        self.preview.setMarkdown(self.editor.toPlainText())

    def ask_discard(self):
        """Leaving the editor (or closing) with unsaved changes. True means throw them away. Tests replace this."""
        return QMessageBox.question(self, 'Zygote', 'Close without saving the changes?') == QMessageBox.Yes

    def save(self):
        project, path = self.editable
        try:
            name = core.save_text_file(project, path, self.editor.toPlainText(), self.info['bom'], self.info['newline'])
        except core.ZygoteError as error:
            QMessageBox.critical(self, crashlog.error_title(), str(error))
            return
        self.saved_snapshots.append(name)
        self.editor.document().setModified(False)
        self.browser.setMarkdown(self.editor.toPlainText())      # view mode shows what was saved

    def stop_editing(self):
        """Cancel: back to the drawn page. Unsaved changes are asked about first."""
        if self.editor.document().isModified() and not self.ask_discard():
            return
        self.pages.setCurrentWidget(self.browser)
        self.edit_row.hide()
        self.view_row.show()

    def reject(self):
        if self.is_editing() and self.editor.document().isModified() and not self.ask_discard():
            return
        super().reject()

    def closeEvent(self, event):
        if self.is_editing() and self.editor.document().isModified() and not self.ask_discard():
            event.ignore()
            return
        super().closeEvent(event)

    @classmethod
    def html_page(cls, title, html, parent=None):
        window = cls(title, parent)
        window.browser.setHtml(html)
        return window

    @classmethod
    def markdown_page(cls, title, markdown, parent=None, editable=None):
        window = cls(title, parent, editable)
        window.browser.setMarkdown(markdown)
        return window

    @classmethod
    def text_page(cls, title, text, parent=None):
        window = cls(title, parent)
        window.browser.setPlainText(text)
        return window
