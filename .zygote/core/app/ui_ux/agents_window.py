"""AI > AI agents: a non-modal window that lists the agents Zygote plans to host. Only the Project starter agent runs (double-click it, or Run); the others
are still the catalog. The starter reads a folder's file list and proposes where each file goes in Zygote's layout; the person ticks the moves
to make, presses Go, and can press Undo. Layout: one drag bar lets the lists (agents, explanation) take height from the working area; the meters and
the model strip keep their own height."""
import os

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
                               QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton, QVBoxLayout, QWidget)

from ai import settings, starter
from ai.agents import AGENTS
from ai.http import Http
from ai.ollama import Ollama
from functional import core
from ui_ux.machine_meters import MachineMeters

STARTER = 'Project starter agent'

def microphone_icon():
    """A small microphone, drawn here (no file)."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor('#111111'))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(10, 2, 12, 19), 6, 6)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor('#111111'), 3))
    painter.drawArc(QRectF(7, 8, 18, 15), 180 * 16, 180 * 16)
    painter.drawLine(QPointF(16, 23), QPointF(16, 28))
    painter.drawLine(QPointF(11, 28), QPointF(21, 28))
    painter.end()
    return QIcon(pixmap)


SPLITTER_LOOK = ('QSplitter::handle { background: #4d4d4d; border-radius: 2px; } QSplitter::handle:hover { background: #8ab4d8; } '
                 'QSplitter::handle:vertical { margin: 1px 40%; height: 6px; } QSplitter::handle:horizontal { margin: 40% 1px; width: 6px; }')


class Cylon(QWidget):
    """A busy light: a red spot that sweeps back and forth with a fading tail while the agent works. It moves only while running (its timer is stopped otherwise)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self.position, self.step = 0.0, 0.025
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.advance)

    def set_running(self, running):
        if running:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def advance(self):
        self.position += self.step
        if self.position >= 1.0 or self.position <= 0.0:
            self.position = max(0.0, min(1.0, self.position))
            self.step = -self.step
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#1b1b1b'))
        if not self.timer.isActive():
            return
        width, height = self.width(), self.height()
        centre = self.position * (width - 1)
        direction = 1 if self.step > 0 else -1
        for tail in range(14):                              # the head is the brightest; the tail fades behind it
            x = centre - direction * tail * 9
            if 0 <= x < width:
                painter.fillRect(QRectF(x - 4, 1, 9, height - 2), QColor(220, 30, 30, max(0, 255 - tail * 19)))


class AgentsWindow(QWidget):
    def __init__(self, main):
        super().__init__(main, Qt.Window)
        self.main = main
        self.http = Http(self)
        self.run = None                                     # the StarterRun in progress
        self.folder = None                                  # the folder the starter reads (the project's own until changed)
        self.plan = None                                    # the proposal on the table
        self.checks = {}                                    # old path -> ticked (kept while the table is refilled)
        self.auto_loaded = False                            # the model is loaded once when the window first shows it (the Load button does it again)
        self.setWindowTitle('Zygote — AI agents')
        self.resize(1000, 900)
        layout = QVBoxLayout(self)
        note = QLabel('Only the Project starter agent is built (double-click it). The grey ones are planned. They all use the model of AI > AI settings.')
        note.setObjectName('dim')
        note.setWordWrap(True)
        layout.addWidget(note)
        # The drag bars: list|explanation (sideways); explanation above the Model section; the working area above the problems box.
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.setStyleSheet(SPLITTER_LOOK)
        layout.addWidget(self.splitter, 1)
        self.top_splitter = QSplitter(Qt.Horizontal)
        self.top_splitter.setChildrenCollapsible(False)
        self.top_splitter.setHandleWidth(8)
        self.top_splitter.setStyleSheet(SPLITTER_LOOK)
        self.agent_list = QListWidget()
        for agent in AGENTS:
            self.agent_list.addItem(agent['name'])
            if not agent.get('built'):                      # planned, not built: shown grey and cannot be chosen
                item = self.agent_list.item(self.agent_list.count() - 1)
                item.setFlags(Qt.NoItemFlags)
                item.setToolTip('Not built yet')
        self.detail = QTextBrowser()
        self.top_splitter.addWidget(self.agent_list)
        self.top_splitter.addWidget(self.detail)
        self.top_splitter.setStretchFactor(1, 1)
        self.top_splitter.setSizes([260, 700])
        self.splitter.addWidget(self.top_splitter)
        self.model_group = QGroupBox('Model')               # a small AI panel: which model, whether it is in the GPU, how busy the computer is
        group_layout = QVBoxLayout(self.model_group)
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.setToolTip('The model that does the work. It is loaded into the GPU when this window opens and again when Run is pressed.')
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.setToolTip('Ask Ollama again which models it has and which one is in the GPU')
        self.load_button = QPushButton('Load')
        self.load_button.setToolTip('Put the chosen model into the GPU (it stays there until it is unloaded in AI > AI settings)')
        self.loaded_label = QLabel('')
        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.addWidget(self.model_box, 1)
        model_layout.addWidget(self.refresh_button)
        model_layout.addWidget(self.load_button)
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(model_row)
        top_layout.addWidget(self.loaded_label)
        self.meters = MachineMeters(top=top)                # the meters keep their own height: only the text areas grow
        group_layout.addWidget(self.meters)
        self.model_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.splitter.addWidget(self.model_group)
        self.starter_box = QWidget()                        # the starter's controls and result, shown only while the starter is chosen
        box = QVBoxLayout(self.starter_box)
        box.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.folder_label = QLabel('')
        self.folder_label.setToolTip('The folder whose files are read (only the list of names)')
        self.browse_button = QPushButton('Folder…')
        self.run_button = QPushButton('Run')
        self.run_button.setToolTip('Load the model, then ask it where each file belongs. Nothing is moved by this: it only makes a proposal.')
        self.stop_button = QPushButton('Stop')
        self.stop_button.setEnabled(False)
        controls.addWidget(self.folder_label, 1)
        for widget in (self.browse_button, self.run_button, self.stop_button):
            controls.addWidget(widget)
        box.addLayout(controls)
        goal_row = QHBoxLayout()
        self.goal = QLineEdit()
        self.goal.setPlaceholderText('Optional: say in a sentence what this project is (it helps the model)')
        self.mic_button = QToolButton()
        self.mic_button.setIcon(microphone_icon())
        self.mic_button.setToolTip('Dictate into this box: starts Windows voice typing (Win+H) with the cursor in the box')
        goal_row.addWidget(self.goal, 1)
        goal_row.addWidget(self.mic_button)
        box.addLayout(goal_row)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.busy = Cylon()                                 # moves only while the agent works
        box.addWidget(self.busy)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['From', 'To', 'Result'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setColumnWidth(0, 380)
        self.table.setColumnWidth(1, 330)
        box.addWidget(self.table, 1)
        picks = QHBoxLayout()
        self.check_all_button = QPushButton('Check all')
        self.uncheck_all_button = QPushButton('Uncheck all')
        self.check_selected_button = QPushButton('Check selected')
        self.check_selected_button.setToolTip('Tick every row you have highlighted (drag or Shift-click to highlight many)')
        self.uncheck_selected_button = QPushButton('Uncheck selected')
        self.count_label = QLabel('')
        self.go_button = QPushButton('Go')
        self.go_button.setToolTip('Make the ticked moves (asks first; never overwrites a file)')
        self.undo_button = QPushButton('Undo')
        self.undo_button.setToolTip('Put back what the last Go moved')
        for widget in (self.check_all_button, self.uncheck_all_button, self.check_selected_button, self.uncheck_selected_button):
            picks.addWidget(widget)
        picks.addWidget(self.count_label, 1)
        picks.addWidget(self.go_button)
        picks.addWidget(self.undo_button)
        box.addLayout(picks)
        self.splitter.addWidget(self.starter_box)
        self.problems = QPlainTextEdit()
        self.problems.setReadOnly(True)
        self.problems.setMinimumHeight(50)
        self.problems.setPlaceholderText('Lines the model got wrong and files it did not place are listed here.')
        self.splitter.addWidget(self.problems)
        for index, stretch in enumerate((1, 0, 3, 1)):
            self.splitter.setStretchFactor(index, stretch)
        self.splitter.setSizes([260, 190, 430, 110])
        self.starter_box.setVisible(False)
        self.problems.setVisible(False)
        self.agent_list.currentRowChanged.connect(self.show_agent)
        self.agent_list.itemDoubleClicked.connect(lambda item: self.main.guarded(self.run_starter) if item.text() == STARTER else None)
        self.run_button.clicked.connect(lambda: self.main.guarded(self.run_starter))
        self.stop_button.clicked.connect(self.stop_starter)
        self.browse_button.clicked.connect(lambda: self.main.guarded(self.choose_folder))
        self.mic_button.clicked.connect(self.start_dictation)
        self.refresh_button.clicked.connect(lambda: self.main.guarded(self.ask_models))
        self.load_button.clicked.connect(lambda: self.main.guarded(self.load_model))
        self.check_all_button.clicked.connect(lambda: self.set_checks(range(self.table.rowCount()), True))
        self.uncheck_all_button.clicked.connect(lambda: self.set_checks(range(self.table.rowCount()), False))
        self.check_selected_button.clicked.connect(lambda: self.set_checks(self.selected_rows(), True))
        self.uncheck_selected_button.clicked.connect(lambda: self.set_checks(self.selected_rows(), False))
        self.go_button.clicked.connect(lambda: self.main.guarded(self.go))
        self.undo_button.clicked.connect(lambda: self.main.guarded(self.undo))
        self.table.itemChanged.connect(self.item_changed)
        self.agent_list.setCurrentRow(0)
        self.update_buttons()

    def is_starter(self, row):
        return 0 <= row < len(AGENTS) and AGENTS[row]['name'] == STARTER

    def show_agent(self, row):
        self.starter_box.setVisible(self.is_starter(row))
        self.problems.setVisible(self.is_starter(row))
        if row < 0:
            self.detail.clear()
            return
        agent = AGENTS[row]
        built = '' if agent['name'] != STARTER else ' — runs now (double-click, or Run)'
        steps = ''.join(f'<li>{step}</li>' for step in agent['works'])
        self.detail.setHtml(f'<h2>{agent["name"]}</h2><p><b>Status:</b> {agent["status"]}{built if built else " (not built)"}</p><p>{agent["purpose"]}</p>'
                            f'<p><b>What it would do</b></p><ul>{steps}</ul><p><b>Needs:</b> {agent["needs"]}</p>')
        if self.is_starter(row):
            self.show_starter()

    # ---- the Project starter agent
    def show_starter(self):
        if self.folder is None and self.main.project is not None:
            self.folder = self.main.project
        self.folder_label.setText(str(self.folder or '(no folder chosen)'))
        self.ask_models()
        self.update_buttons()

    def ollama(self):
        saved = settings.read(self.main.need_project())
        target = saved['target']
        return Ollama(self.http, saved[f'{target}_url'], worker=target == 'worker')

    def ask_models(self):
        """Fill the model box with what Ollama has on its disk (the coder model first). If Ollama does not answer, say so; the box stays editable."""
        self.ollama().get('/api/tags', self.got_models)
        self.ollama().get('/api/ps', self.got_resident)

    def got_resident(self, ok, data):
        """Which model is in the GPU now (Ollama's /api/ps)."""
        if not ok:
            self.loaded_label.setText('')
            return
        models = (data or {}).get('models') or []
        self.loaded_label.setText('In the GPU now: ' + ', '.join(f'{entry.get("name") or entry.get("model")} ({(entry.get("size_vram") or 0) / 1024 ** 3:.1f} GB)'
                                                                  for entry in models) if models else 'No model is in the GPU yet. Press Load (Run loads it too).')

    def load_model(self):
        """Put the chosen model into the GPU and keep it there. An HTTP call to the Ollama that is already running."""
        model = self.model_box.currentText().strip()
        if not model:
            self.say('Choose or type the model first.', bad=True)
            return
        self.loaded_label.setText(f'Loading {model}…')
        self.ollama().load(model, self.model_loaded)

    def model_loaded(self, ok, data):
        if not ok:
            self.loaded_label.setText(f'The model could not be loaded: {data}')
            return
        self.ollama().get('/api/ps', self.got_resident)

    def got_models(self, ok, data):
        if not ok:
            self.say(f'Ollama did not answer ({data}). Start it and load the model in AI > AI settings, then press Run.', bad=True)
            return
        names = [entry.get('name') or entry.get('model') for entry in (data or {}).get('models') or []]
        keep = self.model_box.currentText()
        self.model_box.clear()
        self.model_box.addItems(sorted(names, key=lambda name: ('coder' not in name, name)))
        if keep:
            self.model_box.setCurrentText(keep)
        if not self.auto_loaded and self.model_box.currentText():       # the first time the window shows the model, it is loaded: "it is just there"
            self.auto_loaded = True
            self.load_model()

    def say(self, text, bad=False):
        self.status.setText(f'<b style="color:#c0392b">{text}</b>' if bad else text)

    def start_dictation(self):
        """The microphone: put the cursor in the box and start Windows voice typing (Win+H). The person presses the button; nothing else starts it."""
        self.goal.setFocus()
        if not self.press_dictation_keys():
            self.say('Voice typing: press your system\'s dictation key with the cursor in the box (Windows: Win+H).')

    def press_dictation_keys(self):
        """Send Win+H to Windows. Returns False where there is no Windows. Tests replace this."""
        if os.name != 'nt':
            return False
        import ctypes
        user32 = ctypes.windll.user32
        for key, up in ((0x5B, False), (0x48, False), (0x48, True), (0x5B, True)):       # Win down, H down, H up, Win up
            user32.keybd_event(key, 0, 2 if up else 0, 0)
        return True

    def ask_folder(self):
        """Pick the folder to read. Tests replace this."""
        return QFileDialog.getExistingDirectory(self, 'Folder to place', str(self.folder or ''))

    def choose_folder(self):
        chosen = self.ask_folder()
        if chosen:
            self.folder = chosen
            self.folder_label.setText(str(chosen))
            self.update_buttons()

    def run_starter(self):
        if self.run is not None:
            self.say('The agent is already running.')
            return
        self.agent_list.setCurrentRow(next(row for row, agent in enumerate(AGENTS) if agent['name'] == STARTER))
        model = self.model_box.currentText().strip()
        if not model:
            self.say('Choose or type the model first (pull one in AI > AI settings if the list is empty).', bad=True)
            return
        if self.folder is None:
            self.say('Choose the folder to read first.', bad=True)
            return
        files, cut = starter.scan(self.folder)
        self.plan, self.checks = None, {}
        self.table.setRowCount(0)
        self.problems.clear()
        self.say(f'{len(files)} files found' + (f' (the list was cut at {starter.SCAN_LIMIT})' if cut else '') + f'. Loading {model} into the GPU first…')
        ollama = self.ollama()
        self.run = starter.StarterRun(ollama, model, files, self.progressed, self.finished, self.goal.text())
        self.set_running(True)
        ollama.load(model, self.loaded)                     # an HTTP call (Ollama must already be running; Zygote never starts it)

    def loaded(self, ok, data):
        if self.run is None:
            return
        if not ok:
            run, self.run = self.run, None
            self.set_running(False)
            self.say(f'The model could not be loaded: {data}. Is Ollama running? (AI > AI settings)', bad=True)
            return
        self.run.start()

    def stop_starter(self):
        if self.run is not None:
            self.run.stop()
            self.say('Stopping after the answer that is coming…')

    def set_running(self, running):
        self.run_button.setEnabled(not running)
        self.busy.set_running(running)
        self.stop_button.setEnabled(running)
        self.browse_button.setEnabled(not running)
        self.update_buttons()

    def progressed(self, done, total, text):
        self.say(f'{text} (group {min(done + 1, total)} of {total})')
        self.fill_table(self.run.plan)

    def finished(self, plan, error):
        self.run = None
        self.plan = plan
        self.set_running(False)
        self.fill_table(plan)
        lines = list(plan.problems)
        missing = plan.unplaced()
        if missing:
            lines.append(f'NOT PLACED ({len(missing)}): ' + ', '.join(missing[:40]) + (' …' if len(missing) > 40 else ''))
        self.problems.setPlainText('\n'.join(lines))
        result = f'{len(plan.moves)} of {len(plan.files)} files placed; {len(plan.problems)} refused lines; {len(missing)} not placed. Tick what to move, then press Go.'
        self.say(f'{error} {result}' if error else result, bad=bool(error and error != 'Stopped.'))

    # ---- the table: a tick on each row says whether that move is made
    def fill_table(self, plan):
        moves = sorted(plan.moves.items())
        self.table.blockSignals(True)
        self.table.setRowCount(len(moves))
        for row, (old, new) in enumerate(moves):
            first = QTableWidgetItem(old)
            first.setFlags(first.flags() | Qt.ItemIsUserCheckable)
            first.setCheckState(Qt.Checked if self.checks.setdefault(old, True) else Qt.Unchecked)
            self.table.setItem(row, 0, first)
            self.table.setItem(row, 1, QTableWidgetItem(new))
            self.table.setItem(row, 2, QTableWidgetItem(''))
        self.table.blockSignals(False)
        self.update_buttons()

    def item_changed(self, item):
        if item.column() == 0:
            self.checks[item.text()] = item.checkState() == Qt.Checked
            self.update_buttons()

    def selected_rows(self):
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def set_checks(self, rows, on):
        for row in rows:
            self.table.item(row, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def checked_moves(self):
        return [(self.table.item(row, 0).text(), self.table.item(row, 1).text()) for row in range(self.table.rowCount())
                if self.table.item(row, 0).checkState() == Qt.Checked]

    def update_buttons(self):
        busy = self.run is not None
        rows = self.table.rowCount()
        ticked = len(self.checked_moves())
        self.count_label.setText(f'{ticked} of {rows} ticked' if rows else '')
        self.go_button.setEnabled(not busy and ticked > 0 and self.folder is not None)
        self.undo_button.setEnabled(not busy and self.journal() is not None)
        if getattr(self.main, 'ai_window', None) is not None:
            self.main.ai_window.show_agent_undo()
        for button in (self.check_all_button, self.uncheck_all_button, self.check_selected_button, self.uncheck_selected_button):
            button.setEnabled(rows > 0 and not busy)

    # ---- Go and Undo
    def journal(self):
        project = self.main.project
        return starter.read_journal(project) if project is not None else None

    def ask(self, title, text):
        """The guard before moving files. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def go(self):
        moves = self.checked_moves()
        if not moves or self.folder is None:
            return
        if os.path.normcase(os.path.realpath(self.folder)) == os.path.normcase(os.path.realpath(core.ZYGOTE_ROOT)):
            raise core.ZygoteError('This is the folder Zygote itself runs from. Moving its files would break it, so the agent will not do it.')
        if self.journal() is not None and not self.ask('Go', 'The last Go can still be undone, and a new Go replaces that undo. Continue?'):
            return
        if not self.ask('Go', f'Move {len(moves)} files inside\n{self.folder}\n\nNothing is overwritten. Undo puts them back.'):
            self.say('Go: cancelled, nothing was moved.')
            return
        result = starter.apply(self.folder, moves)
        entries = starter.move_entries(self.main.project, self.folder, result['done']) if result['done'] else {}
        starter.write_journal(self.main.project, {'folder': str(self.folder), 'done': result['done'], 'dirs': result['dirs'], 'entries': entries} if result['done'] else None)
        moved = {old for old, _ in result['done']}
        skipped = dict(result['skipped'])
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            old = self.table.item(row, 0).text()
            if old in moved:
                self.table.item(row, 2).setText('Moved')
                self.table.item(row, 0).setCheckState(Qt.Unchecked)
                self.checks[old] = False
            elif old in skipped:
                self.table.item(row, 2).setText(f'Skipped: {skipped[old]}')
        self.table.blockSignals(False)
        story = starter.summarize(result['done'])
        for mode, parts in entries.items():
            if 'entry' in parts:
                story.append(f'Entry point ({mode}) is now {parts["entry"][1]}')
            if 'args' in parts:
                story.append(f'Command line arguments ({mode}) are now: {parts["args"][1]}')
        if result['tidied']:
            story.append(f'{len(result["tidied"])} emptied folders removed.')
        story.append(f'{len(result["skipped"])} skipped.' if result['skipped'] else 'Nothing skipped.')
        self.say(f'<b>{len(result["done"])} files moved.</b> Undo puts them back.<br>' + '<br>'.join(story))
        self.update_buttons()

    def undo(self):
        journal = self.journal()
        if journal is None:
            return
        if not self.ask('Undo', f'Put back the {len(journal["done"])} files the last Go moved in\n{journal["folder"]}?'):
            self.say('Undo: cancelled.')
            return
        result = starter.undo_last(self.main.project)
        self.journal_changed(result)

    def journal_changed(self, result=None):
        """The last Go was undone (here or from the AI panel): show it in the table and the buttons."""
        restored = set((result or {}).get('restored', []))
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            old = self.table.item(row, 0).text()
            if old in restored:
                self.table.item(row, 2).setText('Restored')
                self.table.item(row, 0).setCheckState(Qt.Checked)
                self.checks[old] = True
        self.table.blockSignals(False)
        if result is not None:
            skipped = result['skipped']
            self.say(f'{len(restored)} files put back, entry point restored.' if not skipped else f'{len(restored)} files put back, {len(skipped)} could not be: '
                     + '; '.join(f'{old}: {why}' for old, why in skipped[:3]))
        self.update_buttons()
