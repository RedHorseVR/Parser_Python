"""The Qt renderer of the AI panel: it reads the panel's layout (data/ai_panel.json), builds the parts, sends what the person does to the logic
(ai/panel_logic.py, no Qt) and draws what the logic's view() says. The layout names parts by type (row, column, group, label, choice, text, check, button,
table, output, stretch) and by id; a part of an unknown type raises. The logic works on a thread of its own while a change runs (a model can take minutes to
load); everything the person sees is drawn here, in the window's own thread. `colors` (optional) is the look of the project that holds the panel."""
import functools
import json
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ai.panel_logic import PanelLogic

LAYOUT_FILE = Path(__file__).resolve().parents[1] / 'data' / 'ai_panel.json'
INPUT_IDS = ('target', 'address', 'model', 'prompt', 'recycle')


def load_layout(path=LAYOUT_FILE):
    layout = json.loads(Path(path).read_text(encoding='utf-8'))
    if not (isinstance(layout, dict) and isinstance(layout.get('root'), dict)):
        raise ValueError(f'{path} is not a panel layout: it needs a "root".')
    return layout


class PanelBuilder:
    """Builds the widgets of one layout node (and its children). `window` gets the parts by id in `window.parts` and the buttons' actions in `window.pressed`."""

    def __init__(self, window):
        self.window = window

    def build(self, node):
        kind = node.get('type')
        method = getattr(self, 'make_' + str(kind), None)
        if method is None:
            raise ValueError(f'The panel layout has a part of an unknown type: {kind!r}.')
        return method(node)

    def named(self, node, widget):
        if node.get('id'):
            self.window.parts[node['id']] = widget
        if node.get('tip'):
            widget.setToolTip(node['tip'])
        return widget

    def fill(self, layout, node):
        for child in node.get('children') or []:
            if child.get('type') == 'stretch':
                layout.addStretch(1)
            else:
                layout.addWidget(self.build(child), child.get('stretch', 0))

    def make_column(self, node):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.fill(layout, node)
        return widget

    def make_row(self, node):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.fill(layout, node)
        return widget

    def make_group(self, node):
        widget = QGroupBox(node.get('label', ''))
        self.fill(QVBoxLayout(widget), node)
        return widget

    def make_label(self, node):
        widget = QLabel(node.get('label', ''))
        widget.setWordWrap(bool(node.get('wrap')))
        return self.named(node, widget)

    def make_choice(self, node):
        widget = QComboBox()
        widget.setMinimumWidth(node.get('min_width', 200))
        widget.activated.connect(functools.partial(self.window.changed, node['id']))
        return self.named(node, widget)

    def make_text(self, node):
        widget = QLineEdit()
        widget.setPlaceholderText(node.get('placeholder', ''))
        if node.get('action'):
            widget.returnPressed.connect(functools.partial(self.window.pressed, node['action'], None))
        else:
            widget.editingFinished.connect(functools.partial(self.window.changed, node['id'], 0))
        return self.named(node, widget)

    def make_check(self, node):
        return self.named(node, QCheckBox(node.get('label', '')))

    def make_button(self, node):
        widget = QPushButton(node.get('label', ''))
        widget.clicked.connect(functools.partial(self.window.pressed, node['action'], None))
        return self.named(node, widget)

    def make_output(self, node):
        widget = QPlainTextEdit()
        widget.setReadOnly(True)
        widget.setMinimumHeight(node.get('min_height', 100))
        return self.named(node, widget)

    def make_table(self, node):
        columns = list(node['columns'])
        widget = QTableWidget(0, len(columns) + 1)
        widget.setHorizontalHeaderLabels(columns + [''])
        widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        widget.setSelectionMode(QAbstractItemView.SingleSelection)
        widget.verticalHeader().hide()
        widget.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        widget.horizontalHeader().setSectionResizeMode(min(3, len(columns) - 1), QHeaderView.Stretch)
        widget.row_action = node.get('action')
        return self.named(node, widget)


class PanelWindow(QWidget):
    finished = Signal()                                      # the worker thread is done (the window draws in its own thread)

    def __init__(self, parent, project, layout=None, colors=None):
        super().__init__(parent, Qt.Window)
        self.layout_data = layout or load_layout()
        self.logic = PanelLogic(project)
        self.parts = {}
        self.worker = None
        self.errors = []
        self.setWindowTitle(f'Zygote — {self.layout_data.get("title", "AI")}')
        self.resize(*self.layout_data.get('size', (900, 600)))
        outer = QVBoxLayout(self)
        outer.addWidget(PanelBuilder(self).build(self.layout_data['root']))
        if colors:
            self.setStyleSheet(self.style_for(colors))
        self.finished.connect(self.draw)
        self.draw()

    @staticmethod
    def style_for(colors):
        """The project's look: only the colours it names ('background', 'text', 'button', 'field'); nothing else is restyled."""
        rules = []
        if 'background' in colors:
            rules.append(f'QWidget {{ background: {colors["background"]}; }}')
        if 'text' in colors:
            rules.append(f'QWidget {{ color: {colors["text"]}; }}')
        if 'button' in colors:
            rules.append(f'QPushButton {{ background: {colors["button"]}; }}')
        if 'field' in colors:
            rules.append(f'QLineEdit, QPlainTextEdit, QTableWidget, QComboBox {{ background: {colors["field"]}; }}')
        return '\n'.join(rules)

    def use_project(self, project):
        self.logic.use_project(project)
        self.draw()

    # ---- what the person did
    def inputs(self):
        found = {}
        for key in INPUT_IDS:
            widget = self.parts.get(key)
            if isinstance(widget, QComboBox):
                found[key] = widget.currentData()
            elif isinstance(widget, QLineEdit):
                found[key] = widget.text()
            elif isinstance(widget, QCheckBox):
                found[key] = widget.isChecked()
        return found

    def changed(self, key, _index=0):
        """A choice or a text was changed: no network, the logic takes it and the window is drawn again."""
        if key == 'target':
            self.logic.quick('target', self.inputs())
        elif key == 'address':
            self.logic.quick('address', self.inputs())
        self.draw()

    def ask(self, question, risky):
        """True = go ahead. A risk answers No unless told otherwise. Tests replace this."""
        box = QMessageBox(QMessageBox.Warning if risky else QMessageBox.Question, 'Zygote — AI', question, QMessageBox.Yes | QMessageBox.No, self)
        if risky:
            box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def show_error(self, text):
        QMessageBox.warning(self, 'Zygote — AI', text)

    def pressed(self, action, arg):
        """A button (or Enter in the question line, or a row's Load / Unload) was pressed."""
        if action == 'clear_answer':
            self.logic.quick('clear_answer', self.inputs())
            self.draw()
            return
        if self.worker is not None:
            return
        inputs = self.inputs()
        plan = self.logic.plan(action, inputs, arg)
        if plan.get('skip'):
            self.draw()
            return
        if 'ask' in plan and not self.ask(plan['ask'], plan['risky']):
            self.logic.declined(plan.get('declined', 'Not done.'))
            self.draw()
            return
        try:
            self.logic.begin(action, inputs, arg)
        except Exception as error:                           # a wrong address: said loudly, nothing started
            self.show_error(str(error))
            return
        self.worker = threading.Thread(target=self.work, daemon=True)
        self.worker.start()
        self.draw()

    def work(self):
        try:
            self.logic.run()
        except Exception as error:                           # nothing is hidden: the text goes to the status line
            self.logic.status = f'FAILED: {error}'
        self.finished.emit()

    # ---- what the logic says
    def draw(self):
        if self.worker is not None and not self.logic.busy:
            self.worker.join()
            self.worker = None
        view = self.logic.view()
        for key, shown in view.items():
            widget = self.parts.get(key)
            if widget is not None:
                self.show_part(widget, shown)

    def show_part(self, widget, shown):
        if isinstance(widget, QComboBox):
            widget.blockSignals(True)
            widget.clear()
            for label, value in shown.get('items', []):
                widget.addItem(label, value)
            widget.setCurrentIndex(max(widget.findData(shown.get('value')), 0))
            widget.blockSignals(False)
        elif isinstance(widget, QTableWidget):
            self.show_table(widget, shown['rows'])
        elif isinstance(widget, QLabel):
            widget.setText(shown['text'])
        elif isinstance(widget, QPlainTextEdit):
            widget.setPlainText(shown['text'])
        elif isinstance(widget, QPushButton) and 'text' in shown:
            widget.setText(shown['text'])
        elif isinstance(widget, QLineEdit) and 'text' in shown and not widget.hasFocus():
            widget.setText(shown['text'])
        if 'enabled' in shown:
            widget.setEnabled(shown['enabled'])

    def show_table(self, table, rows):
        table.setRowCount(len(rows))
        last = table.columnCount() - 1
        for number, row in enumerate(rows):
            for column, text in enumerate(row['cells']):
                table.setItem(number, column, QTableWidgetItem(text))
            button = QPushButton(row['button'])
            button.setEnabled(row['enabled'])
            button.clicked.connect(functools.partial(self.pressed, table.row_action, row['key']))
            table.setCellWidget(number, last, button)
        table.resizeColumnToContents(0)
        table.setColumnWidth(0, table.columnWidth(0) + 16)
