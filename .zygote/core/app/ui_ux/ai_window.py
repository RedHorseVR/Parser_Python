"""The AI panel: a window of its own (not modal: it stays open as long as it is wanted) that shows the language models of one place and lets
them be loaded into the GPU or taken out, and tried with one prompt. The place is this computer's Ollama or a LAN GPU worker.

Every question is asked at once and answered later (ai\\http.py): the panel never waits. Only one change (load, unload, test) runs at a time:
the buttons that would start another one are off until the answer is in. The table refreshes only when asked (Refresh, and after every change).
The one exception (DOCTRINE, 2026-11-10): while the panel is shown, a one-second timer reads the memory and the processor and GPU load for the
live meters; it stops when the panel is closed."""
import functools

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ai import gpu, install, settings, starter, system
from ai.download import Download
from ai.http import Http
from ai.ollama import Ollama, PullProgress, Refresh, human_bytes, inventory_rows, load_risks, recommend_model, worker_gpu
from functional import core
from ui_ux.image_drop import ImageDrop
from ui_ux.meters import OTHER, LoadMeter, SegmentBar

TARGET_NAMES = {'local': 'This computer (Ollama)', 'worker': 'LAN GPU worker'}
COLUMNS = ('Model', 'Params', 'Disk', 'Capabilities', 'GPU memory', 'Text', 'Image', 'Analysis', '')
USE_COLUMNS = {5: 'text', 6: 'image', 7: 'analysis'}        # the boxes: what the model is meant for (kept per project)
BUTTON_COLUMN = 8
MIB = 2 ** 20
TICK_MS = 1000                                              # the live meters; the timer runs only while the panel is shown


class AIWindow(QWidget):
    def __init__(self, main, project):
        super().__init__(main, Qt.Window)
        self.main = main
        self.setWindowTitle('Zygote — AI')
        self.resize(980, 800)
        self.project = project
        self.http = Http(self)
        self.busy = False                                   # one change at a time
        self.rows = []
        self.uses = {}                                      # model name -> {text, image, analysis}
        self.load_order = []                                # the loaded models, first loaded first
        self.model_colors = {}                              # model name -> index of its colour pair (the table cell and the bar segment match)
        self.gpu_state = None                               # {'names', 'total', 'used', 'load'} (MiB, percent); None = not known
        self.cpu = system.CpuMeter()
        self.health_pending = False
        self.console_view = None
        self.last_answer = ''                               # the newest answer (what Recycle sends)
        self.timer = QTimer(self)                           # runs only while the panel is shown (showEvent / hideEvent)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)
        self.build()
        self.use_project(project)

    # ---- the parts of the window
    def build(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.target_box = QComboBox()
        for key, name in TARGET_NAMES.items():
            self.target_box.addItem(name, key)
        self.target_box.setToolTip('Where the models are: this computer, or another computer that runs the LAN GPU worker')
        self.address = QLineEdit()
        self.address.setToolTip('Local: Ollama at http://127.0.0.1:11434. Worker: its address, like http://192.168.1.20:11435')
        self.refresh_button = QPushButton('Load')
        self.refresh_button.setToolTip('Ask the chosen place what models it has and what is in the GPU (after that this button says Refresh)')
        self.reset_button = QPushButton('Unload all')
        self.reset_button.setToolTip('Take every model out of the GPU (asks first). Use it when something will not load or the GPU is jammed.')
        self.console_button = QPushButton('Ollama console')
        self.console_button.setToolTip('Open a command prompt here to type Ollama commands (one shell; it ends when this panel is closed)')
        top.addWidget(self.target_box)
        top.addWidget(self.address, 1)
        top.addWidget(self.refresh_button)
        top.addWidget(self.reset_button)
        top.addWidget(self.console_button)
        self.undo_agent_button = QPushButton('Undo agent')
        self.undo_agent_button.setToolTip('Put back what the last AI agent run changed in this project (asks first)')
        top.addWidget(self.undo_agent_button)
        layout.addLayout(top)
        get = QHBoxLayout()                                 # getting Ollama and a model: each step is a button, nothing starts by itself
        self.install_button = QPushButton('Install Ollama')
        self.install_button.setToolTip('Download Ollama\'s installer from ollama.com and run it (asks first; Windows). Zygote never starts Ollama itself.')
        self.model_edit = QLineEdit(recommend_model(None)[0])
        self.model_edit.setToolTip('The model to pull (download to the disk). It is NOT loaded into memory: load it from the table.')
        self.pull_button = QPushButton('Pull model')
        self.pull_button.setToolTip('Download this model with Ollama (asks first). A model of several GB; it is not loaded into memory.')
        self.recommend_label = QLabel('')
        self.recommend_label.setWordWrap(True)
        for widget, stretch in ((self.install_button, 0), (self.model_edit, 1), (self.pull_button, 0)):
            get.addWidget(widget, stretch)
        layout.addLayout(get)
        layout.addWidget(self.recommend_label)
        self.pull_output = QPlainTextEdit()                 # what the pull says as it goes (percent, size, speed, time left); shown during and after a pull
        self.pull_output.setReadOnly(True)
        self.pull_output.setMaximumHeight(70)
        self.pull_output.setVisible(False)
        layout.addWidget(self.pull_output)
        self.install_button.setVisible(install.can_install())
        self.show_install_state()
        self.show_agent_undo()
        self.show_recommendation(None)
        monitor = QHBoxLayout()
        bars = QVBoxLayout()
        self.status_line = QLabel()
        self.status_line.setWordWrap(True)
        bars.addWidget(self.status_line)
        self.cpu_label = QLabel('CPU memory')
        self.cpu_bar = SegmentBar()
        self.gpu_names = QLabel()
        self.memory = SegmentBar()                          # the GPU memory: one colour per loaded model, grey for the rest
        for widget in (self.cpu_label, self.cpu_bar, self.gpu_names, self.memory):
            bars.addWidget(widget)
        monitor.addLayout(bars, 1)
        self.gpu_meter = LoadMeter('GPU')
        self.cpu_meter = LoadMeter('CPU')
        monitor.addWidget(self.gpu_meter)
        monitor.addWidget(self.cpu_meter)
        layout.addLayout(monitor)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)            # every column can be dragged wider (the model names are long)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        test = QGroupBox('Try a model')
        test_layout = QVBoxLayout(test)
        test_row = QHBoxLayout()
        self.test_model = QComboBox()
        self.test_model.setMinimumWidth(260)
        self.test_model.setToolTip('● marks the models that are loaded now (they are first). Another one is loaded first, after asking.')
        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText('One question for the chosen model…')
        self.recycle_box = QCheckBox('Recycle')
        self.recycle_box.setToolTip('Ticked: the last answer is sent along with the question, and the new answer is added under it')
        self.clear_prompt_button = QPushButton('Clear')
        self.clear_prompt_button.setToolTip('Empty the question line')
        self.send_button = QPushButton('Send')
        for widget, stretch in ((self.test_model, 0), (self.prompt, 1), (self.recycle_box, 0), (self.clear_prompt_button, 0), (self.send_button, 0)):
            test_row.addWidget(widget, stretch)
        test_layout.addLayout(test_row)
        answer_row = QHBoxLayout()
        self.picture = ImageDrop()                          # a picture for a vision model; grey when the chosen model cannot see
        answer_row.addWidget(self.picture, 0, Qt.AlignTop)
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setMinimumHeight(170)
        answer_row.addWidget(self.answer, 1)
        test_layout.addLayout(answer_row)
        clear_row = QHBoxLayout()
        self.clear_answer_button = QPushButton('Clear answer')
        self.clear_answer_button.setToolTip('Empty the answer box (and what Recycle would send)')
        clear_row.addStretch(1)
        clear_row.addWidget(self.clear_answer_button)
        test_layout.addLayout(clear_row)
        layout.addWidget(test)
        self.console_box = QGroupBox('Ollama console')
        self.console_box.setVisible(False)
        self.console_layout = QVBoxLayout(self.console_box)
        layout.addWidget(self.console_box)
        cloud = QGroupBox('Cloud models')
        cloud_layout = QVBoxLayout(cloud)
        cloud_layout.addWidget(QLabel('Not connected yet. Your keys and the frontier models will be set here; the keys will stay in this '
                                      "project's private .zygote\\user folder."))
        layout.addWidget(cloud)
        self.target_box.currentIndexChanged.connect(self.target_changed)
        self.address.editingFinished.connect(self.address_changed)
        self.refresh_button.clicked.connect(self.refresh)
        self.reset_button.clicked.connect(self.unload_all)
        self.console_button.clicked.connect(self.toggle_console)
        self.install_button.clicked.connect(lambda: self.main.guarded(self.install_ollama))
        self.undo_agent_button.clicked.connect(lambda: self.main.guarded(self.undo_agent))
        self.pull_button.clicked.connect(lambda: self.main.guarded(self.pull_model))
        self.send_button.clicked.connect(self.send)
        self.prompt.returnPressed.connect(self.send)
        self.clear_prompt_button.clicked.connect(self.prompt.clear)
        self.clear_answer_button.clicked.connect(self.clear_answer)
        self.test_model.currentIndexChanged.connect(self.show_picture_state)
        self.table.itemChanged.connect(self.use_changed)

    # ---- the settings
    def use_project(self, project):
        """Show this project's remembered target, addresses and model uses (the panel stays open when another project is opened)."""
        self.project = project
        saved = settings.read(project)
        self.uses = settings.read_uses(project)
        self.urls = {'local': saved['local_url'], 'worker': saved['worker_url']}
        self.target_box.blockSignals(True)
        self.target_box.setCurrentIndex(self.target_box.findData(saved['target']))
        self.target_box.blockSignals(False)
        self.address.setText(self.urls[saved['target']])
        self.refresh_button.setText('Load')                # a project not looked at yet: the button starts the look
        self.clear_view('Press Load to look.')

    def target(self):
        return self.target_box.currentData()

    def target_changed(self):
        self.address.setText(self.urls[self.target()])
        self.clear_view('Press Refresh to look.')

    def address_changed(self):
        self.urls[self.target()] = self.address.text().strip()

    def keep_settings(self):
        """Remember the target and addresses (raises, loudly, when the chosen address is not an address)."""
        self.urls[self.target()] = self.address.text().strip()
        settings.write(self.project, self.target(), self.urls['local'], self.urls['worker'])

    def ollama(self):
        return Ollama(self.http, self.urls[self.target()], worker=self.target() == 'worker')

    # ---- the live meters (only while the panel is shown)
    def showEvent(self, event):
        super().showEvent(event)
        self.cpu.before = None
        self.timer.start()
        self.tick()

    def hideEvent(self, event):
        super().hideEvent(event)
        if not event.spontaneous():                         # closed (a minimized window keeps its meters)
            self.timer.stop()
            self.stop_console()

    def tick(self):
        """Once a second: this computer's memory and processor load, the GPU's memory and load. Library calls only (a worker is asked its report)."""
        if self.target() == 'worker':
            self.tick_worker()
            return
        try:
            cards = gpu.local_gpus()
        except core.ZygoteError as error:
            self.gpu_state = None
            self.gpu_names.setText(f'GPU: {error}')
            self.gpu_meter.set_percent(None)
        else:
            self.set_gpu(', '.join(card['name'] for card in cards) or 'no GPU found', sum(card['total_mib'] for card in cards),
                         sum(card['used_mib'] for card in cards), max((card['load'] for card in cards), default=None))
        try:
            total, used = system.memory_mib()
            self.cpu_label.setText('CPU memory')
            self.cpu_bar.set_parts([(used, '#3a7bd5')], total, f'CPU memory: {used / 1024:.1f} of {total / 1024:.1f} GB used ({used * 100 // total}%)')
            self.cpu_meter.set_percent(self.cpu.percent())
        except core.ZygoteError as error:
            self.cpu_label.setText(f'CPU memory: {error}')
            self.cpu_bar.set_parts([], 0, '')
            self.cpu_meter.set_percent(None)

    def tick_worker(self):
        self.cpu_label.setText('CPU memory: the worker does not report it')
        self.cpu_bar.set_parts([], 0, '')
        self.cpu_meter.set_percent(None)
        if self.health_pending:
            return
        try:
            ollama = self.ollama()
        except core.ZygoteError:
            return                                          # no address yet: Refresh says so
        self.health_pending = True
        ollama.get('/worker/health', self.health_in)

    def health_in(self, ok, data):
        self.health_pending = False
        if ok and self.target() == 'worker':
            names, total, used = worker_gpu(data)
            self.set_gpu(', '.join(names) or 'no GPU reported', total, used, None)

    def set_gpu(self, names, total, used, load):
        self.gpu_state = {'names': names, 'total': total, 'used': used, 'load': load}
        self.gpu_names.setText(f'GPU: {names}')
        self.show_recommendation(total)
        self.gpu_meter.set_percent(load)
        self.draw_gpu()

    def draw_gpu(self):
        """The GPU memory strip: a colour for each loaded model (the same colour as in the table), grey for what else uses the memory."""
        state = self.gpu_state
        if state is None or not state['total'] or state['used'] is None:
            self.memory.set_parts([], 0, 'memory unknown')
            return
        parts, taken = [], 0
        for name in self.load_order:
            row = self.row_named(name)
            if row is not None and row['vram']:
                parts.append((row['vram'] / MIB, core.TAB_COLORS[self.model_colors[name]][0]))
                taken += row['vram'] / MIB
        parts.append((max(state['used'] - taken, 0), OTHER))
        self.memory.set_parts(parts, state['total'], f'GPU memory: {state["used"] / 1024:.1f} of {state["total"] / 1024:.1f} GB used '
                                                       f'({state["used"] * 100 // state["total"]}%)')

    # ---- what is shown
    def say(self, text):
        self.status_line.setText(text)

    def clear_view(self, text):
        self.rows = []
        self.load_order, self.model_colors, self.gpu_state = [], {}, None
        self.table.setRowCount(0)
        self.test_model.clear()
        self.gpu_names.setText('')
        self.memory.set_parts([], 0, '')
        self.say(text)

    def row_named(self, name):
        return next((row for row in self.rows if row['name'] == name), None)

    def set_busy(self, busy):
        self.busy = busy
        self.refresh_button.setEnabled(not busy)
        self.reset_button.setEnabled(not busy)
        self.pull_button.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        for row in range(self.table.rowCount()):
            self.table.cellWidget(row, BUTTON_COLUMN).setEnabled(not busy)

    def refresh(self):
        """Ask the chosen place what it has. Raises (shown by the window's error box) when the address is wrong."""
        self.keep_settings()
        self.set_busy(True)
        self.say('Asking…')
        Refresh(self.ollama(), self.refreshed).start()

    def refreshed(self, snapshot):
        self.set_busy(False)
        self.show_install_state()
        self.refresh_button.setText('Refresh')              # after the first look the button asks again rather than starts
        if snapshot['tags'] is None:                        # nothing answered: say why, plainly
            self.clear_view(f'NOT REACHED: {"; ".join(snapshot["errors"])}')
            self.show_gpu(snapshot)
            return
        self.rows = inventory_rows(snapshot['tags'], snapshot['ps'], snapshot['shown'])
        self.update_load_order([entry.get('name') or entry.get('model') for entry in (snapshot['ps'] or {}).get('models') or []])
        self.show_rows()
        self.show_gpu(snapshot)
        parts = [f'{TARGET_NAMES[self.target()]}: READY', f'Ollama {snapshot["version"] or "?"}', f'{len(self.rows)} models']
        spilled = [row for row in self.rows if row['spill']]
        for row in spilled:
            parts.append(f'WARNING: {row["name"]} has {human_bytes(row["spill"])} in CPU memory (it did not fit the GPU): this slows and can freeze the computer')
        if snapshot['errors']:
            parts.append('PROBLEM: ' + '; '.join(snapshot['errors']))
        self.say(' · '.join(parts))

    def update_load_order(self, resident):
        """Keep the order the models were loaded in (first loaded first), and give each its colour pair until it is unloaded."""
        resident = [name for name in resident if name]
        self.load_order = [name for name in self.load_order if name in resident] + [name for name in resident if name not in self.load_order]
        self.model_colors = {name: color for name, color in self.model_colors.items() if name in self.load_order}
        for name in self.load_order:
            if name not in self.model_colors:
                self.model_colors[name] = core.next_tab_color(list(self.model_colors.values()))

    def use_allowed(self, row, kind):
        """Which uses a model can have: text needs completion, image needs vision, analysis needs thinking (unknown capabilities: text only)."""
        caps = row['capabilities']
        if kind == 'text':
            return caps is None or 'completion' in caps
        return bool(caps) and ('vision' if kind == 'image' else 'thinking') in caps

    def use_state(self, row, kind):
        """True when the box is ticked for this model: what the project kept, else the default (text ticked where it is possible)."""
        if not self.use_allowed(row, kind):
            return False
        saved = self.uses.get(row['name'])
        return saved[kind] if saved else kind == 'text'

    def show_rows(self):
        chosen = self.test_model.currentData()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        self.test_model.clear()
        for number, row in enumerate(self.rows):
            capabilities = '?' if row['capabilities'] is None else ', '.join(row['capabilities'])
            cells = (row['name'], row['params'] or '?', human_bytes(row['disk']), capabilities, self.memory_text(row))
            for column, text in enumerate(cells):
                self.table.setItem(number, column, QTableWidgetItem(text))
            self.color_memory_cell(number, row)
            for column, kind in USE_COLUMNS.items():
                self.table.setItem(number, column, self.use_item(row, kind))
            button = QPushButton('Unload' if row['resident'] else 'Load')
            button.setToolTip('Take the model out of the GPU' if row['resident'] else 'Put the model into the GPU and keep it there')
            button.clicked.connect(functools.partial(self.guarded_change, row['name'], row['resident']))
            self.table.setCellWidget(number, BUTTON_COLUMN, button)
        for row in sorted(self.rows, key=lambda r: (not r['resident'], self.load_order.index(r['name']) if r['resident'] else 0, r['name'].lower())):
            self.test_model.addItem(('● ' if row['resident'] else '') + row['name'], row['name'])
        if chosen:
            self.test_model.setCurrentIndex(max(self.test_model.findData(chosen), 0))
        self.table.resizeColumnToContents(0)                # the whole model name shows; drag the column to change it
        self.table.setColumnWidth(0, self.table.columnWidth(0) + 16)
        self.table.blockSignals(False)
        self.show_picture_state()

    def memory_text(self, row):
        if not row['resident']:
            return '—'
        text = f'{human_bytes(row["vram"])} · #{self.load_order.index(row["name"]) + 1}'
        return text + (f' · ⚠ {human_bytes(row["spill"])} in CPU memory' if row['spill'] else '')

    def color_memory_cell(self, number, row):
        item = self.table.item(number, 4)
        if not row['resident']:
            return
        back, text = core.TAB_COLORS[self.model_colors[row['name']]]
        item.setBackground(QBrush(QColor(back)))
        item.setForeground(QBrush(QColor(text)))
        if row['spill']:
            item.setToolTip('Part of this model did not fit the GPU and sits in CPU memory: everything slows and the computer can freeze.')

    def use_item(self, row, kind):
        item = QTableWidgetItem()
        if self.use_allowed(row, kind):
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked if self.use_state(row, kind) else Qt.Unchecked)
        else:
            item.setFlags(Qt.NoItemFlags)                   # greyed out: this model cannot do it
            item.setBackground(QBrush(QColor('#333333')))
            item.setCheckState(Qt.Unchecked)
        return item

    def use_changed(self, item):
        """A Text / Image / Analysis box was ticked or cleared: kept for the project, with the other two boxes of that model."""
        if item.column() not in USE_COLUMNS:
            return
        row = self.rows[item.row()]
        self.uses[row['name']] = {kind: self.table.item(item.row(), column).checkState() == Qt.Checked for column, kind in USE_COLUMNS.items()}
        settings.write_uses(self.project, self.uses)

    def show_gpu(self, snapshot):
        """The cards: this computer's through the NVIDIA library, a worker's from its own report."""
        if self.target() == 'worker':
            if snapshot['health'] is None:
                self.gpu_names.setText('GPU: the worker gave no report.')
                return
            names, total, used = worker_gpu(snapshot['health'])
            self.set_gpu(', '.join(names) or 'no GPU reported', total, used, None)
            return
        self.tick()

    # ---- the changes
    def guarded_change(self, model, loaded):
        """A Load / Unload button was pressed. Errors are raised to the window's error box like every other button's."""
        self.change(model, loaded)

    def ask_load(self, model, reasons):
        """True = load the model. Always asks; with reasons it is a warning that says what can go wrong and answers No unless told otherwise."""
        if not reasons:
            return QMessageBox.question(self, 'Zygote — AI', f'{model} is not loaded.\nLoad it into the GPU first?') == QMessageBox.Yes
        box = QMessageBox(QMessageBox.Warning, 'Zygote — AI', f'RISK: loading {model}:\n  - ' + '\n  - '.join(reasons) +
                          '\n\nUnload a model first, or load anyway and risk jamming the GPU?', QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def confirm_load(self, row):
        state = self.gpu_state or {}
        return self.ask_load(row['name'], load_risks(row, state.get('total'), state.get('used')))

    def change(self, model, loaded):
        if self.busy:
            return
        row = self.row_named(model)
        if not loaded and row is not None and not self.confirm_load(row):
            self.say(f'Not loaded: {model}.')
            return
        self.set_busy(True)
        self.say(f'{"Unloading" if loaded else "Loading"} {model}… (a big model can take a minute or more)')
        action = self.ollama().unload if loaded else self.ollama().load
        action(model, lambda ok, data: self.changed(model, loaded, ok, data))

    def changed(self, model, loaded, ok, data):
        if not ok:
            self.set_busy(False)
            self.say(f'{"Unload" if loaded else "Load"} {model} FAILED: {data}')
            return
        self.refresh()                                      # the card and the table are read again: they show what really happened

    def ask_unload_all(self, count):
        return QMessageBox.question(self, 'Zygote — AI', f'Take all {count} loaded model(s) out of the GPU?') == QMessageBox.Yes

    def unload_all(self):
        """Unload all: every loaded model leaves the GPU, one after the other (after asking)."""
        loaded = [row['name'] for row in self.rows if row['resident']]
        if self.busy:
            return
        if not loaded:
            self.say('Nothing is loaded.')
            return
        if not self.ask_unload_all(len(loaded)):
            return
        self.set_busy(True)
        self.unload_next(loaded)

    def unload_next(self, queue):
        if not queue:
            self.refresh()
            return
        model = queue[0]
        self.say(f'Unloading {model}… ({len(queue)} to go)')
        self.ollama().unload(model, functools.partial(self.unloaded_next, queue))

    def unloaded_next(self, queue, ok, data):
        if not ok:
            self.set_busy(False)
            self.say(f'Unload {queue[0]} FAILED: {data}')
            return
        self.unload_next(queue[1:])

    def model_sees(self, name):
        row = self.row_named(name)
        return bool(row and row['capabilities'] and 'vision' in row['capabilities'])

    def show_picture_state(self):
        """The picture's frame is green for a model that can see and grey for one that cannot (the picture stays either way)."""
        self.picture.set_active(self.model_sees(self.test_model.currentData()))

    def clear_answer(self):
        self.answer.clear()
        self.last_answer = ''

    def send(self):
        """Try the chosen model with the question in the box. A model that is not loaded is loaded first, after asking. A model that can see
        gets the picture too. With Recycle ticked the last answer goes along with the question."""
        model, prompt = self.test_model.currentData(), self.prompt.text().strip()
        if self.busy or not model or not prompt:
            return
        row = self.row_named(model)
        if row is not None and not row['resident'] and not self.confirm_load(row):
            self.say(f'Not asked: {model} is not loaded.')
            return
        recycled = self.recycle_box.isChecked() and bool(self.last_answer)
        sent = f'{prompt}\n\n{self.last_answer}' if recycled else prompt
        pictures = [self.picture.png_base64()] if self.model_sees(model) and self.picture.image is not None else None
        self.set_busy(True)
        self.asking = (model, prompt, recycled)
        if not recycled:
            self.answer.setPlainText('…')
        self.say(f'Asking {model}…' + (' (with the picture)' if pictures else '') + (' (with the last answer)' if recycled else ''))
        self.ollama().generate(model, sent, self.answered, pictures)

    def answered(self, ok, data):
        self.set_busy(False)
        model, prompt, recycled = self.asking
        if not ok:
            if not recycled:
                self.answer.setPlainText('')
            self.say(f'The model did not answer: {data}')
            return
        text = str(data.get('response', ''))
        if recycled:                                        # the new answer goes under the old one, with a banner in another colour
            self.answer.appendHtml(f'<p style="color:#5aa9ff"><b>── {model}, answering "{prompt}" about the text above ──</b></p>')
            self.answer.appendPlainText(text)
        else:
            self.answer.setPlainText(text)
        self.last_answer = text
        self.say('Answered.')

    # ---- getting Ollama and a model (buttons; the installer is the one process, the pull is an HTTP call)
    def show_recommendation(self, total_mib):
        """The model Zygote recommends for this card. The box follows it until the person types their own."""
        tag, why = recommend_model(total_mib)
        if self.model_edit.text() in ('', getattr(self, 'recommended', None), recommend_model(None)[0]):
            self.model_edit.setText(tag)
        self.recommended = tag
        self.recommend_label.setText(f'Recommended: {tag}. {why}')

    def ask_install(self):
        """The guard before the download: where from, and what runs. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Install Ollama',
                          f'Download Ollama\'s installer from {install.OLLAMA_URL} (a large file) and run it?\n\n'
                          'The installer opens its own window. Zygote starts nothing else; Ollama starts itself after it is installed.',
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def show_agent_undo(self):
        """The Undo agent button is lit while the last agent run can still be put back."""
        self.undo_agent_button.setEnabled(starter.read_journal(self.project) is not None)

    def ask_undo_agent(self, count):
        """The guard before putting back what an agent did. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Undo agent', f'Put back the {count} files the last agent run moved?', QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def undo_agent(self):
        journal = starter.read_journal(self.project)
        if journal is None or not self.ask_undo_agent(len(journal['done'])):
            return
        result = starter.undo_last(self.project)
        self.say(f'Undo agent: {len(result["restored"])} files put back' + (f', {len(result["skipped"])} could not be' if result['skipped'] else '') + '.')
        self.show_agent_undo()
        if self.main.agents_window is not None:
            self.main.agents_window.journal_changed(result)

    def show_install_state(self):
        """The Install button is grey once Ollama is on this computer (looked for again after each Load and after the installer ends)."""
        installed = install.is_installed()
        self.install_button.setEnabled(not installed)
        self.install_button.setText('Ollama installed' if installed else 'Install Ollama')

    def install_ollama(self):
        if not install.can_install():
            raise core.ZygoteError('Ollama\'s installer runs on Windows only. Use the command on https://ollama.com/download in the Ollama console.')
        if not self.ask_install():
            self.say('Install Ollama: cancelled, nothing was downloaded.')
            return
        install.remove_old_installer()
        self.install_button.setEnabled(False)
        self.download = Download(self)
        self.download.progress.connect(self.install_progress)
        self.download.finished.connect(self.install_downloaded)
        self.say('Downloading Ollama\'s installer…')
        self.download.start(install.OLLAMA_URL, install.installer_path())

    def install_progress(self, received, expected):
        self.say(f'Downloading Ollama\'s installer: {human_bytes(received)}' + (f' of {human_bytes(expected)}' if expected else ''))

    def install_downloaded(self, ok, what):
        self.show_install_state()
        if not ok:
            self.say(f'Install Ollama: the download failed ({what}). Nothing was started.')
            return
        try:
            install.start_installer(what)
        except (OSError, core.ZygoteError) as error:
            self.say(f'Install Ollama: the installer could not start ({error}).')
            return
        self.say('Ollama\'s installer is open. When it is finished, press Load here.')

    def ask_pull(self, name):
        """The guard before a pull: it is a large download. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Pull model', f'Download {name} with Ollama now?\n\nIt is several GB and takes a while. It is only put on the disk; '
                          'it is not loaded into memory.', QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def pull_model(self):
        name = self.model_edit.text().strip()
        if not name:
            self.say('Pull model: type the name of a model first.')
            return
        if not self.ask_pull(name):
            self.say(f'Pull model: cancelled, {name} was not downloaded.')
            return
        self.keep_settings()
        self.set_busy(True)
        self.say(f'Pulling {name}… (this takes a while; the model is not loaded into memory)')
        self.progress = PullProgress(name)
        self.pull_output.clear()
        self.pull_output.setVisible(True)
        self.last_pull_line = None
        self.ollama().pull(name, self.pull_event, functools.partial(self.pulled, name))

    def pull_event(self, event):
        """One progress line from Ollama: show it in the pull box (a line that only changes its numbers replaces the one before) and in the status line."""
        text = self.progress.feed(event)
        if self.progress.percent is None:                   # a step without numbers (pulling manifest, verifying…): it gets its own line
            self.pull_output.appendPlainText(text)
            self.last_pull_line = None
        else:
            if self.last_pull_line is not None:
                self.pull_output.setPlainText(self.pull_output.toPlainText().rsplit('\n', 1)[0] if '\n' in self.pull_output.toPlainText() else '')
            self.pull_output.appendPlainText(text)
            self.last_pull_line = text
        self.say(text)

    def pulled(self, name, ok, reason):
        self.set_busy(False)
        if not ok or self.progress.error:
            self.say(f'Pull model: {name} failed: {self.progress.error or reason}')
            return
        self.pull_output.appendPlainText(f'{name} is on the disk.')
        self.say(f'{name} is on the disk. Load it from the table when you want it in memory.')
        self.refresh()

    # ---- the Ollama console (a command prompt, started by its button, ended with the panel)
    def toggle_console(self):
        if self.console_view is not None:
            self.stop_console()
            return
        view = self.main.terminal_factory(parent=self.console_box)
        view.setMinimumHeight(170)
        self.console_layout.addWidget(view)
        self.console_view = view
        self.console_box.setVisible(True)
        try:
            view.start(core.shell_command(), self.project)
        except Exception:
            self.stop_console()                             # nothing stays half open; the error is shown in full
            raise
        self.console_button.setText('Close console')
        view.setFocus()

    def stop_console(self):
        """The console's shell ends (at once) and its box goes. Nothing stays running after the panel closes: when the shell does not end in
        time the box stays, and the status line says so."""
        view = self.console_view
        if view is None:
            return
        if view.is_running():
            view.stop(force=True)
            self.main.wait_until_ended(view)
            if view.is_running():
                self.say('The Ollama console did not end yet. Press Close console again.')
                return
        self.console_view = None
        view.setParent(None)
        view.deleteLater()
        self.console_box.setVisible(False)
        self.console_button.setText('Ollama console')
