"""Zygote's dialogs: pick a project folder (drop it or browse), confirm the project (git, name, folder name), and Tools
(which program opens which file type)."""
import datetime
import html
from pathlib import Path

from PySide6.QtCore import Signal, QProcess, QProcessEnvironment, QSize, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QPixmapCache, QGuiApplication, QIcon, QImage, QKeySequence, QPixmap, QTextCursor
from PySide6.QtWidgets import (QWidget, QAbstractItemView, QCheckBox, QComboBox, QScrollArea, QGroupBox, QMessageBox, QPlainTextEdit, QDialog, QFrame, QStyle, QStyleOptionViewItem, QStyledItemDelegate, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QColorDialog, QInputDialog, QLabel, QLineEdit, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

import crashlog
from functional import core, icons
from ui_ux.theme import Theme


class DropBox(QLabel):
    """A framed area that takes a dropped folder. It is a drop target, not a button."""

    def __init__(self, dialog):
        super().__init__('Drop a project folder here')
        self.dialog = dialog
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(110)
        self.setAcceptDrops(True)
        self.setObjectName('dropbox')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if Path(url.toLocalFile()).is_dir():
                self.dialog.choose(url.toLocalFile())
                event.acceptProposedAction()
                return
        self.dialog.say('That is not a folder. Drop the project folder itself.')


class OpenProjectDialog(QDialog):
    """Shown when there is no project. Result: .folder (a path) after accept().

    `launch_folder` is where Zygote was started from (a shortcut's "Start in" folder); the lower-left button offers it as the project."""

    def __init__(self, parent=None, launch_folder=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote — open a project')
        self.folder = None
        self.launch_folder = Path(launch_folder) if launch_folder else Path.cwd()
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>Pick a project folder to open.</b><br>Drag the folder onto the box, or press Pick folder…'))
        layout.addWidget(DropBox(self))
        self.note = QLabel('')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.here_button = QPushButton('Open in current folder')
        self.here_button.setToolTip(f'Use the folder Zygote was started from: {self.launch_folder}')
        self.here_button.clicked.connect(self.use_launch_folder)
        pick = QPushButton('Pick folder…')
        pick.clicked.connect(self.pick)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self.here_button)                          # far left, lower corner
        row.addStretch(1)
        row.addWidget(pick)
        row.addWidget(cancel)
        layout.addLayout(row)
        self.current = QLabel(f'Current folder: {self.launch_folder}')
        self.current.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.current)

    def use_launch_folder(self):
        self.choose(str(self.launch_folder))

    def say(self, text):
        self.note.setText(text)

    def pick(self):
        folder = QFileDialog.getExistingDirectory(self, 'Pick the project folder')
        if folder:
            self.choose(folder)

    def choose(self, folder):
        self.folder = folder
        self.accept()


class ConfirmProjectDialog(QDialog):
    """Confirm the project: the folder, whether it has a .git, its name (editable) and an optional folder rename.

    Used for a newly chosen folder and, with the open project, for "Project settings…"."""

    def __init__(self, folder, name, parent=None, title='Zygote — confirm the project folder'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.folder = Path(folder)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('You will be working in this project folder:'))
        where = QLabel(str(self.folder))
        where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bold = where.font()
        bold.setBold(True)
        where.setFont(bold)
        layout.addWidget(where)
        self.git_label = QLabel()
        if core.has_git(self.folder):
            self.git_label.setText('A .git folder was found: this folder is a Git repository.')
        else:
            self.git_label.setText('<span style="color:#b25a00;"><b>Warning:</b> no .git folder was found here. '
                                   'Commit will not work until this folder is in a Git repository.</span>')
        self.git_label.setWordWrap(True)
        layout.addWidget(self.git_label)
        self.form = QFormLayout()
        self.name_edit = QLineEdit(name)
        self.form.addRow('Project name:', self.name_edit)
        layout.addLayout(self.form)
        self.rename_box = QCheckBox('Also rename the folder to match the project name')
        layout.addWidget(self.rename_box)
        self.error = QLabel('')
        self.error.setObjectName('error')
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.check_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.name_edit.textChanged.connect(self.update_rename_box)
        self.update_rename_box()

    def update_rename_box(self):
        differs = self.name_edit.text().strip() != self.folder.name
        self.rename_box.setEnabled(differs)           # nothing to rename while the name matches the folder
        if not differs:
            self.rename_box.setChecked(False)

    def values(self):
        return self.name_edit.text().strip(), self.rename_box.isChecked()

    def check_and_accept(self):
        name, rename = self.values()
        try:
            core.check_project_name(name, rename)
        except core.ZygoteError as error:
            self.error.setText(str(error))
            return
        self.accept()


class ClearableLine(QLineEdit):
    """A line of text with the usual right-click items (Undo, Cut, Copy, Paste, Delete, Select All) and, last, Clear: the whole line is emptied in one step.
    The entry point and the command line arguments of Project settings are both this one class."""

    def line_menu(self):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        clear = menu.addAction('Clear')
        clear.setEnabled(bool(self.text()))
        clear.triggered.connect(self.clear)
        return menu

    def contextMenuEvent(self, event):
        menu = self.line_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()


class EntryLine(ClearableLine):
    """The entry point of Project settings: ONE line with a dotted border. Type a path, or drop the file that starts the project on it
    (from Explorer or from Zygote's own icon view). `dropped` tells the panel a file arrived, so it can suggest a runner."""
    dropped = Signal()

    def __init__(self, text='', folder=None):
        super().__init__(text)
        self.folder = Path(folder) if folder else None
        self.setObjectName('entryline')
        self.setAcceptDrops(True)
        self.setPlaceholderText('Entry point: type a path, or drop the file that starts the project here')

    def stored(self, path):
        """What a dropped file is stored as: relative to the project folder when it is inside it (a project that moves still runs), else the whole path."""
        try:
            return Path(path).relative_to(self.folder).as_posix() if self.folder else str(path)
        except ValueError:
            return str(path)

    def entry(self):
        return self.text().strip()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            self.setText(self.stored(url.toLocalFile()))
            break
        event.acceptProposedAction()
        self.dropped.emit()


class ArgsLine(ClearableLine):
    """The command line arguments of Project settings. Type them, or drop a file or a folder on the line (from Explorer or from Zygote's own icon view):
    its path is added at the end. A path inside the project is added relative to it (nothing bakes the project's own place into a setting); a path
    from anywhere else is added whole, because the person chose it. A path with spaces is put in quotes."""

    def __init__(self, folder, text=''):
        super().__init__(text)
        self.folder = Path(folder)
        self.setAcceptDrops(True)
        self.setPlaceholderText('Command line arguments (type them, or drop a file or folder here)')

    def word_for(self, path):
        return core.arguments_for(self.folder, [path])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        words = [self.word_for(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if words:
            self.setText((self.text().rstrip() + ' ' + ' '.join(words)).strip())
        event.acceptProposedAction()


class IconLine(QLineEdit):
    """The program icon line of Project settings. Drop a file on it (a .ico, or a picture to make an icon from) or paste a picture (Ctrl+V).
    `dropped` carries the path; `pasted` carries the picture."""
    dropped = Signal(str)
    pasted = Signal(QImage)

    def __init__(self, text=''):
        super().__init__(text)
        self.setObjectName('entryline')
        self.setAcceptDrops(True)
        self.setPlaceholderText('Program icon: drop a .ico or a picture here, or paste a picture')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        event.acceptProposedAction()
        if mime.hasUrls():
            self.dropped.emit(mime.urls()[0].toLocalFile())
        elif mime.hasImage():
            self.pasted.emit(QImage(mime.imageData()))

    def keyPressEvent(self, event):
        mime = QGuiApplication.clipboard().mimeData()
        if event.matches(QKeySequence.Paste) and mime is not None and mime.hasImage():
            self.pasted.emit(QImage(mime.imageData()))
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        """The usual right-click menu, with 'Paste picture' on top: on when the clipboard holds a picture (the standard Paste is for text)."""
        menu = self.createStandardContextMenu()
        mime = QGuiApplication.clipboard().mimeData()
        action = QAction('Paste picture', menu)
        action.setEnabled(mime is not None and mime.hasImage())
        action.triggered.connect(self.paste_picture)
        menu.insertAction(menu.actions()[0] if menu.actions() else None, action)
        menu.exec(event.globalPos())

    def paste_picture(self):
        mime = QGuiApplication.clipboard().mimeData()
        if mime is not None and mime.hasImage():
            self.pasted.emit(QImage(mime.imageData()))


class IconReplaceDialog(QDialog):
    """An icon with this name is already in the icons folder: shows it and asks to replace it. Replace = accept, Cancel = keep it."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote — replace the icon?')
        layout = QVBoxLayout(self)
        text = QLabel(f'{Path(path).name} is already there (shown below). Replace it?')
        text.setWordWrap(True)
        layout.addWidget(text)
        picture = QLabel()
        picture.setAlignment(Qt.AlignCenter)
        picture.setPixmap(QIcon(str(path)).pixmap(96, 96))
        layout.addWidget(picture)
        buttons = QDialogButtonBox()
        buttons.addButton('Replace', QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class IconPreviewDialog(QDialog):
    """A picture is about to become the program icon: a preview of the 256 pixel icon, and (for a picture that is not square) the choice
    Pad (keep everything, transparent bars) or Crop (cut the centre square). The preview follows the choice. OK makes the icon."""

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote — make an icon')
        self.image = image
        layout = QVBoxLayout(self)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(280, 280)
        layout.addWidget(self.preview)
        self.info = QLabel(f'Picture: {image.width()} × {image.height()} pixels. The icon will be {icons.ICON_SIDE} × {icons.ICON_SIDE}.')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        row = QHBoxLayout()
        self.pad_radio = QRadioButton('Pad')
        self.crop_radio = QRadioButton('Crop')
        self.pad_radio.setChecked(True)
        row.addWidget(self.pad_radio)
        row.addWidget(self.crop_radio)
        row.addStretch(1)
        layout.addLayout(row)
        self.is_square = image.width() == image.height()
        self.pad_radio.setEnabled(not self.is_square)                     # a square picture needs neither
        self.crop_radio.setEnabled(not self.is_square)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.pad_radio.toggled.connect(self.show_preview)
        self.show_preview()

    def mode(self):
        return 'crop' if self.crop_radio.isChecked() else 'pad'

    def show_preview(self):
        self.preview.setPixmap(QPixmap.fromImage(icons.icon_image(self.image, self.mode())))


class ProjectSettingsDialog(QDialog):
    """Project settings. NOT modal: the main window stays usable, so a file can be dragged from Zygote's own icon view onto the entry line.
    Top: the project path with OK / Cancel / Save in one row at its right, then the project name (and folder rename). Debug / Runtime radio buttons choose which saved set
    (runner, entry point, command line arguments) is shown and edited; each mode keeps its own. Below: the composed command.
    Save: `saved` signal (the window writes the values, the panel stays open). OK: `accepted` (the window writes them, the panel closes).
    Cancel: closes, nothing more written (the Debug / Runtime choice is saved the moment it is made, like the Debug menu's check box). The panel is never reused after it closes: the window makes a new one each time."""
    saved = Signal()
    mode_changed = Signal(str)                                                 # the Debug / Runtime radio buttons were pressed: the window saves the mode at once
    look_requested = Signal()                                                  # the Look button: the window opens the preferences panel (theme and outer colour)
    RUNNERS = ('', 'python', 'pythonw', 'ipython -i', 'py')

    def __init__(self, folder, name, runs, external, mode, parent=None, icon=''):
        super().__init__(parent)
        self.setWindowTitle('Zygote — project settings')
        self.setModal(False)
        self.folder = Path(folder)
        self.setMinimumWidth(600)
        self.drafts = {mode: dict(runs[mode]) for mode in core.RUN_MODES}      # what is typed, per mode, until Save or OK
        self.mode = core.check_mode(mode)                                        # shown first, and the one Run uses until another is chosen
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        left = QVBoxLayout()
        where = QLabel(str(self.folder))
        where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bold = where.font()
        bold.setBold(True)
        where.setFont(bold)
        left.addWidget(where)
        if not core.has_git(self.folder):
            git = QLabel('<span style="color:#b25a00;"><b>Warning:</b> no .git folder was found here. Commit will not work until this folder is in a Git repository.</span>')
            git.setWordWrap(True)
            left.addWidget(git)
        top.addLayout(left, 1)
        self.buttons = QWidget()                                                 # OK, Cancel, Save in one row, on the line of the project path
        buttons_row = QHBoxLayout(self.buttons)
        buttons_row.setContentsMargins(0, 0, 0, 0)
        self.ok_button = QPushButton('OK')
        self.cancel_button = QPushButton('Cancel')
        self.save_button = QPushButton('Save')
        for button in (self.ok_button, self.cancel_button, self.save_button):
            buttons_row.addWidget(button)
        self.save_button.clicked.connect(self.check_and_save)
        self.ok_button.clicked.connect(self.check_and_accept)
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.setDefault(True)
        top.addWidget(self.buttons, 0, Qt.AlignTop)
        layout.addLayout(top)
        self.error = QLabel('')
        self.error.setObjectName('error')
        layout.addWidget(self.error)
        name_group = QGroupBox('Project name')
        name_column = QVBoxLayout(name_group)
        self.name_edit = QLineEdit(name)
        name_column.addWidget(self.name_edit)
        self.rename_box = QCheckBox('Also rename the folder to match the project name')
        name_column.addWidget(self.rename_box)
        self.look_button = QPushButton('Theme and outer colour…')                      # the look is part of the project: one Settings place
        self.look_button.setToolTip('The look (theme, outer colour) is saved in this project and travels with it.')
        self.look_button.clicked.connect(self.look_requested.emit)
        name_column.addWidget(self.look_button, 0, Qt.AlignLeft)
        layout.addWidget(name_group)
        console_group = QGroupBox('Console')
        console_column = QVBoxLayout(console_group)
        self.external_box = QCheckBox('Show external console output')                  # a separate setting, not part of the run settings
        self.external_box.setToolTip('Unticked (the usual): Run and Commit show the program in the Console tab inside Zygote.\n'
                                     'Ticked: the program runs in its own console window, which stays open after it ends.')
        self.external_box.setChecked(bool(external))
        console_column.addWidget(self.external_box)
        layout.addWidget(console_group)
        group = QGroupBox('Run settings')
        column = QVBoxLayout(group)
        modes = QHBoxLayout()
        self.debug_radio = QRadioButton('Debug')
        self.runtime_radio = QRadioButton('Runtime')
        modes.addWidget(QLabel('Run uses:'))
        modes.addWidget(self.debug_radio)
        modes.addWidget(self.runtime_radio)
        modes.addStretch(1)
        column.addLayout(modes)
        form = QFormLayout()
        self.runner_box = QComboBox()
        self.runner_box.setEditable(True)
        self.runner_box.addItems(self.RUNNERS)
        self.runner_box.setToolTip('The program that runs the entry point. Empty: Windows opens the file with its own program.')
        form.addRow('Runner:', self.runner_box)
        self.entry_line = EntryLine(folder=self.folder)
        used = core.default_entry(self.folder)                                 # grey: what Run really starts while this is empty
        if used:
            self.entry_line.setPlaceholderText(f'{used}   (Run starts this while the box is empty; type or drop your own file to replace it)')
        form.addRow('Entry point:', self.entry_line)
        self.args_edit = ArgsLine(self.folder)
        form.addRow('Command line arguments:', self.args_edit)
        column.addLayout(form)
        self.command_label = QLabel('')
        self.command_label.setWordWrap(True)
        self.command_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        column.addWidget(self.command_label)
        layout.addWidget(group)
        assets = QGroupBox('Assets')
        assets_row = QHBoxLayout(assets)
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(48, 48)
        assets_row.addWidget(self.icon_preview)
        assets_row.addWidget(QLabel('Program icon:'))
        self.icon_line = IconLine(icon or '')
        if not icon:                                                          # grey: the icon in use now
            self.icon_line.setPlaceholderText(f'{core.ICON_FILE.name}   (Zygote\'s own icon, in use now; drop a .ico or picture, or paste one, to use your own)')
        assets_row.addWidget(self.icon_line, 1)
        self.browse_button = QPushButton('Browse…')
        self.browse_button.clicked.connect(self.browse_icon)
        assets_row.addWidget(self.browse_button)
        layout.addWidget(assets)
        self.icon_changes = 0                                                     # counts icon files written, so Save turns on when the same name is replaced
        self.icon_current = None                                                  # the icon file the line showed last: a typed new name renames it
        self.show_icon()
        self.show_mode(self.mode)
        self.saved_snapshot = self.snapshot()
        self.save_button.setEnabled(False)                                      # on only while name, rename, runner, entry point or arguments differ from what is saved
        self.debug_radio.toggled.connect(self.radio_changed)
        self.runner_box.currentTextChanged.connect(self.update_command)
        self.entry_line.textChanged.connect(self.update_command)
        self.entry_line.editingFinished.connect(self.suggest_runner)
        self.entry_line.dropped.connect(self.suggest_runner)
        self.args_edit.textChanged.connect(self.update_command)
        for widget in (self.runner_box.currentTextChanged, self.entry_line.textChanged, self.args_edit.textChanged, self.name_edit.textChanged,
                       self.rename_box.toggled, self.icon_line.textChanged):
            widget.connect(self.update_save_button)
        self.icon_line.textChanged.connect(self.show_icon)
        self.icon_line.dropped.connect(self.take_icon_file)
        self.icon_line.pasted.connect(self.take_icon_picture)
        self.name_edit.textChanged.connect(self.update_rename_box)
        self.update_rename_box()

    def show_mode(self, mode):
        """Put the saved/typed set of one mode into the fields, and tick its radio button."""
        self.mode = mode
        draft = self.drafts[mode]
        for widget in (self.debug_radio, self.runtime_radio, self.runner_box, self.entry_line, self.args_edit):
            widget.blockSignals(True)
        self.debug_radio.setChecked(mode == 'debug')
        self.runtime_radio.setChecked(mode == 'runtime')
        self.runner_box.setCurrentText(draft['runner'])
        self.entry_line.setText(draft['entry'])
        self.args_edit.setText(draft['args'])
        for widget in (self.debug_radio, self.runtime_radio, self.runner_box, self.entry_line, self.args_edit):
            widget.blockSignals(False)
        self.update_command()

    def keep_fields(self):
        self.drafts[self.mode] = {'runner': self.runner_box.currentText().strip(), 'entry': self.entry_line.entry(), 'args': self.args_edit.text().strip()}

    def radio_changed(self):
        self.keep_fields()
        self.show_mode('debug' if self.debug_radio.isChecked() else 'runtime')
        self.mode_changed.emit(self.mode)                                         # the one saved state changes now; the Debug menu follows

    def follow_mode(self, mode):
        """The Debug menu changed the mode: show it here (no signal back)."""
        if mode != self.mode:
            self.keep_fields()
            self.show_mode(mode)

    def suggest_runner(self):
        """An empty runner gets the usual one for the file type (IPython for debug, python for runtime). A typed runner is never changed."""
        if not self.runner_box.currentText().strip():
            hint = core.runner_hint(self.entry_line.entry(), self.mode)
            if hint:
                self.runner_box.setCurrentText(hint)

    def update_command(self):
        self.command_label.setText('<b>Command:</b> ' + html.escape(core.command_text(
            self.runner_box.currentText(), self.entry_line.entry(), self.args_edit.text())) + f'   <i>({self.mode})</i>')

    def update_rename_box(self):
        differs = self.name_edit.text().strip() != self.folder.name
        self.rename_box.setEnabled(differs)
        if not differs:
            self.rename_box.setChecked(False)

    def snapshot(self):
        """What the Save button cares about: name, rename, and the runner, entry point and arguments of both modes. NOT the buttons or the console box."""
        answer = self.settings()
        return (answer['name'], answer['rename'], answer['icon'], self.icon_changes, tuple((mode, tuple(answer['runs'][mode].items())) for mode in core.RUN_MODES))

    def update_save_button(self):
        self.save_button.setEnabled(self.snapshot() != self.saved_snapshot)

    def settings(self):
        self.keep_fields()
        return {'name': self.name_edit.text().strip(), 'rename': self.rename_box.isChecked(), 'external': self.external_box.isChecked(), 'mode': self.mode, 'icon': self.icon_line.text().strip(),
                'runs': {mode: dict(self.drafts[mode]) for mode in core.RUN_MODES}}

    def check(self):
        """True when the typed values are fine; otherwise the problem is written in the panel and False is returned."""
        answer = self.settings()
        try:
            core.check_project_name(answer['name'], answer['rename'])
            for mode in core.RUN_MODES:
                core.entry_relative(self.folder, answer['runs'][mode]['entry'])
            core.plan_icon(self.folder, answer['icon'], self.icon_current)
        except core.ZygoteError as error:
            self.error.setText(str(error))
            return False
        self.error.setText('')
        return True

    def check_and_save(self):
        if self.check() and self.rename_icon_if_asked():
            self.saved.emit()
            self.saved_snapshot = self.snapshot()
            self.save_button.setEnabled(False)

    def check_and_accept(self):
        if self.check() and self.rename_icon_if_asked():
            self.accept()

    def rename_icon_if_asked(self):
        """A name typed in the icon line (not a file) renames the current icon file to it, after asking when that name is taken.
        False when the person said no or it failed (the reason is in the panel); the line then shows the new path."""
        try:
            kind, current, target = core.plan_icon(self.folder, self.icon_line.text(), self.icon_current)
            if kind != 'rename':
                return True
            if target.exists() and target != current and not self.confirm_replace(target):
                return False
            self.icon_line.setText(core.rename_icon(self.folder, current, target))
            self.error.setText('')
            return True
        except (core.ZygoteError, OSError) as error:
            self.error.setText(str(error))
            return False

    # ---- the program icon ------------------------------------------------------------------------------------------------
    def show_icon(self):
        """The small preview beside the icon line: the chosen icon, else Zygote's own (the default)."""
        text = self.icon_line.text().strip()
        path = Path(text) if text else core.ICON_FILE
        if text and not path.is_absolute():
            path = core.clean_path(self.folder) / text
        icon = QIcon(str(path)) if path.is_file() else QIcon()
        self.icon_preview.setPixmap(icon.pixmap(48, 48))
        if text and path.is_file() and path.suffix.lower() == '.ico':
            self.icon_current = core.clean_path(path)

    def ask_icon_mode(self, image):
        """The preview pop-up. Returns 'pad' or 'crop' when OK is pressed, None when cancelled. Tests replace this."""
        dialog = IconPreviewDialog(image, self)
        return dialog.mode() if dialog.exec() == QDialog.Accepted else None

    def pick_icon_path(self):
        """The file picker of Browse…: starts in the project's icons folder (app_tree\\assets\\icons) so the whole set shows at once; a project without that folder starts in
        Zygote's own icon set. Tests replace this."""
        start = core.icons_dir(self.folder)
        if not start.is_dir():
            start = core.ICON_SET
        return QFileDialog.getOpenFileName(self, 'Choose the program icon', str(start),
                                           'Icons and pictures (*.ico *.png *.bmp *.jpg *.jpeg *.gif *.webp *.tif *.tiff)')[0]

    def browse_icon(self):
        path = self.pick_icon_path()
        if path:
            self.take_icon_file(path)

    def confirm_replace(self, path):
        """Ask whether to replace an icon that is already there, showing it. True = replace. Tests replace this."""
        return IconReplaceDialog(path, self).exec() == QDialog.Accepted

    def icon_goes_to(self):
        """Where a new icon goes: the icons folder, named after the project name as typed in the panel."""
        return core.icon_target(self.folder, self.name_edit.text())

    def take_icon_file(self, path):
        """A .ico goes into the icons folder as <project name>.ico (asking first when that icon is there). A picture goes through the preview first.
        Anything else is put in the line, where the check refuses it with the reason."""
        try:
            if icons.is_bitmap(path):
                self.make_icon(icons.load_picture(path))
            elif Path(path).suffix.lower() == '.ico':
                self.icon_line.setText(str(path))                 # only the link: nothing is copied, renamed or replaced here (Save copies in an icon from outside)
            else:
                self.icon_line.setText(str(path))
        except (core.ZygoteError, OSError) as error:
            self.error.setText(str(error))

    def take_icon_picture(self, image):
        try:
            if image.isNull():
                raise core.ZygoteError('The clipboard picture could not be read.')
            self.make_icon(image)
        except core.ZygoteError as error:
            self.error.setText(str(error))

    def make_icon(self, image):
        """Preview, and on OK write the .ico into the icons folder as <project name>.ico and use it (the Save button turns on)."""
        mode = self.ask_icon_mode(image)
        if mode is None:
            return
        self.install(lambda target: icons.save_icon(self.folder, image, mode, target))

    def install(self, write):
        """The path for a new icon made from a picture: written under a free name (nothing is replaced) and shown in the line."""
        target = core.free_icon_path(self.folder, self.icon_goes_to().name)        # a new icon never replaces another: a free name
        self.icon_line.setText(write(target))
        self.icon_changes += 1
        QPixmapCache.clear()                                                      # Qt keeps drawn icons: the replaced file must be read again
        self.show_icon()
        self.update_save_button()
        self.error.setText('')

    def say_saved(self, text):
        self.error.setText(f'<span style="color:#3fa34d;">{html.escape(text)}</span>')


class TestsDialog(QDialog):
    """Run Test Suite: every test of the project in a list; Run starts ONE process (the project's own Python running unittest) and the
    list follows its output: the test being run is selected and each result is written beside its line. Stop and Close end the process
    (only the person's button press or closing the window does). Nothing runs until Run is pressed."""
    COLORS = {'ok': '#3fa34d', 'FAIL': '#d9534f', 'ERROR': '#d9534f'}

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = Path(project)
        self.setWindowTitle(f'Zygote — tests of {core.project_name(self.project)}')
        self.resize(820, 620)
        self.ids = core.list_tests(self.project)                  # raises when there is nothing to list: the caller shows it
        self.rows = {}
        self.results = {}
        self.stream = core.TestStream()
        self.process = None
        self.sort_column = None
        self.sort_order = Qt.AscendingOrder
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['Test', 'Result'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 560)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)                       # a click on a header sorts: all the ok, FAIL and ERROR rows together
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self.sort_by)
        for found in self.ids:
            self.add_row(found)
        layout.addWidget(self.table, 3)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 2)
        self.summary = QLabel(f'{len(self.ids)} tests. Press Run.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        row.addStretch(1)
        self.run_button = QPushButton('Run')
        self.run_button.clicked.connect(self.press_run)
        self.stop_button = QPushButton('Stop')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.close)
        for button in (self.run_button, self.stop_button, self.close_button):
            row.addWidget(button)
        layout.addLayout(row)

    def add_row(self, found):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name, result = QTableWidgetItem(found), QTableWidgetItem('')
        self.table.setItem(row, 0, name)
        self.table.setItem(row, 1, result)
        self.rows[found] = (name, result)                       # items, not row numbers: a sorted table moves its rows
        return result

    def sort_by(self, column):
        """Header click: sort by that column (a second click on the same one reverses it). Not while the tests run: rows would jump."""
        if self.process is not None:
            return
        again = column == self.sort_column
        self.sort_order = Qt.DescendingOrder if again and self.sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        self.sort_column = column
        self.table.sortItems(column, self.sort_order)
        self.table.horizontalHeader().setSortIndicator(column, self.sort_order)

    @staticmethod
    def hide_console(arguments):
        arguments.flags |= 0x08000000                           # CREATE_NO_WINDOW: Windows opens no console window for the test process

    def press_run(self):
        try:
            command = core.test_command(self.project)
        except core.ZygoteError as error:
            self.summary.setText(str(error))
            self.summary.setStyleSheet('color: #d9534f;')
            return
        self.summary.setStyleSheet('')
        self.results = {}
        self.stream = core.TestStream()
        self.output.clear()
        self.table.setRowCount(0)                               # a new run starts from the list in its own order
        self.rows = {}
        for found in self.ids:
            self.add_row(found).setForeground(QColor('#888888'))
        self.sort_column = None
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.process = QProcess(self)                           # the one process of this press
        if hasattr(self.process, 'setCreateProcessArgumentsModifier'):       # Windows only
            self.process.setCreateProcessArgumentsModifier(self.hide_console)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONUNBUFFERED', '1')
        environment.insert('PYTHONIOENCODING', 'utf-8')
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(self.project))
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.finished.connect(self.process_ended)
        self.process.errorOccurred.connect(self.process_failed)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.summary.setText('Running…')
        self.process.start(command[0], command[1:])

    def read(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace')
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        for event in self.stream.feed(text):
            if event[1] not in self.rows:                        # a test the list did not know: added, never dropped
                self.add_row(event[1])
            item = self.rows[event[1]][1]
            if event[0] == 'start':
                self.table.selectRow(item.row())
                self.table.scrollToItem(item)
                item.setText('running…')
            else:
                self.results[event[1]] = event[2]
                item.setText(event[2])
                item.setForeground(QColor(self.COLORS.get(event[2], '#c9a227')))

    def process_ended(self, code, status):
        self.read()
        bad = sorted(found for found, status_text in self.results.items() if status_text in ('FAIL', 'ERROR'))
        good = sum(1 for status_text in self.results.values() if status_text == 'ok')
        never = [found for found in self.rows if found not in self.results]
        for found in never:
            self.rows[found][1].setText('not run')
        self.summary.setText(f'Ran {len(self.results)} of {len(self.rows)} tests: {good} ok, {len(bad)} failed or errored, {len(never)} not run. '
                             f'The process ended with code {code}.')
        self.summary.setStyleSheet('color: #d9534f;' if bad or never or code else 'color: #3fa34d;')
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.process = None

    def process_failed(self, error):
        if self.process is not None and self.process.state() == QProcess.NotRunning:
            self.summary.setText(f'The test process could not run ({self.process.errorString()}).')
            self.summary.setStyleSheet('color: #d9534f;')
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)

    def stop(self):
        if self.process is not None:
            self.process.kill()

    def closeEvent(self, event):
        if self.process is not None:                           # closing the window is the person's act: nothing is left running
            self.process.kill()
            self.process.waitForFinished(3000)
        super().closeEvent(event)


class PreferencesDialog(QDialog):
    """Settings > Preferences: the look of the window, in ONE panel. The Light theme box and the colour picker act at once (`preview` is
    called with every change, so the window itself shows the result); OK keeps it, Cancel puts back what was there. The drop list names
    what the colour is for: the outer container (menu bar, toolbar, frame) for now."""

    def __init__(self, light, outer, current_color, parent=None, preview=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote — preferences')
        self.start = (bool(light), outer)
        self.preview = preview
        self.outer = outer
        layout = QVBoxLayout(self)
        self.light_box = QCheckBox('Light theme (dark is the default)')
        self.light_box.setChecked(bool(light))
        self.light_box.toggled.connect(self.changed)
        layout.addWidget(self.light_box)
        row = QHBoxLayout()
        row.addWidget(QLabel('Colour of:'))
        self.what_box = QComboBox()
        self.what_box.addItem('Outer container')
        row.addWidget(self.what_box)
        row.addStretch(1)
        self.reset_button = QPushButton('Reset colour')
        self.reset_button.setToolTip('Go back to the colour the theme has')
        self.reset_button.clicked.connect(self.reset)
        row.addWidget(self.reset_button)
        layout.addLayout(row)
        self.picker = QColorDialog(self)                       # inside this panel, not a second window
        self.picker.setOptions(QColorDialog.NoButtons | QColorDialog.DontUseNativeDialog)
        self.picker.setWindowFlags(Qt.Widget)
        self.picker.setCurrentColor(QColor(outer or current_color))
        self.picker.currentColorChanged.connect(self.picked)
        layout.addWidget(self.picker)
        self.outer_label = QLabel()
        layout.addWidget(self.outer_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.show_outer()

    def show_outer(self):
        self.outer_label.setText('Outer container: ' + (self.outer or 'the colour of the theme'))

    def changed(self, *args):
        self.show_outer()
        if self.preview is not None:
            self.preview(*self.values())

    def picked(self, color):
        if color.isValid():
            self.outer = color.name()
            self.changed()

    def reset(self):
        self.outer = None
        self.changed()

    def values(self):
        return self.light_box.isChecked(), self.outer

    def reject(self):
        if self.preview is not None:
            self.preview(*self.start)                          # Cancel: the window looks as it did
        super().reject()


class GitSettingsDialog(QDialog):
    """Settings > Git settings…: which program does the Git work, TortoiseGit (its own windows) or the command line git. This computer's choice."""

    def __init__(self, program, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote — Git settings')
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Commit, New branch and Undo last Git step use the program chosen here. Each press starts one program, once.'))
        self.tortoise = QRadioButton('TortoiseGit (its own windows)')
        self.commandline = QRadioButton('Command line git (Zygote asks for what it needs, then runs git)')
        layout.addWidget(self.tortoise)
        layout.addWidget(self.commandline)
        (self.commandline if program == 'commandline' else self.tortoise).setChecked(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def program(self):
        return 'commandline' if self.commandline.isChecked() else 'tortoise'


class ToolsDialog(QDialog):
    """Tools > Settings…: (1) one row per group of file types (from assets/tools_defaults.json, plus any type the person saved on its own): the file types as a list
    (commas or semicolons) and a drop list of the programs found on this computer; (2) Command line tools: a menu name, a command (<file> = the selected file,
    <folder> = the folder in view), and two ticks. Every row has an X that removes it after a question. Works on copies; accept() saves both lists."""

    OTHER = 'Other program…'

    def __init__(self, mapping, parent=None, commands=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote — tools')
        self.setMinimumSize(900, 560)
        self.rows = []                                         # [(types edit, program combo)] of the rows still there
        self.row_buttons = []                                  # the X of each row, same order as self.rows
        self.command_rows = []                                 # [{'name', 'command', 'console', 'keep_open', 'button'}] of the rows still there
        self.removed_widgets = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>Which program opens which file</b><br>A double-click opens each list of file types with the program chosen in its drop list. The drop list shows the programs found on this computer.'))
        self.grid = QGridLayout()
        self.grid.addWidget(QLabel('File types (separate with commas or semicolons)'), 0, 0)
        self.grid.addWidget(QLabel('Opens with'), 0, 1)
        layout.addLayout(self.grid)
        row = QHBoxLayout()
        self.add_button = QPushButton('Add a row…')
        self.add_button.clicked.connect(lambda: self.add_row([], core.WINDOWS_OWN))
        row.addWidget(self.add_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(QLabel('<b>Command line tools</b><br>Each one is a menu entry under Tools. <code>&lt;file&gt;</code> is the selected file, <code>&lt;folder&gt;</code> the folder in view; Zygote writes them '
                                'relative to the project root and puts quotes around them. Each press starts one process.'))
        self.command_grid = QGridLayout()
        for column, title in enumerate(('Menu name', 'Command', 'Run in Zygote Console', 'Keep console open (external)')):
            self.command_grid.addWidget(QLabel(title), 0, column)
        layout.addLayout(self.command_grid)
        row = QHBoxLayout()
        self.add_command_button = QPushButton('Add a row…')
        self.add_command_button.clicked.connect(lambda: self.add_command_row())
        row.addWidget(self.add_command_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.error = QLabel('')
        self.error.setObjectName('error')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.fill(dict(mapping))
        for tool in (core.command_tools() if commands is None else commands):
            self.add_command_row(tool)

    def fill(self, mapping):
        covered = set()
        for group in core.tool_groups():
            covered.update(group['types'])
            chosen = mapping.get(group['types'][0]) or core.default_program(group['types'][0]) or core.WINDOWS_OWN
            self.add_row(group['types'], chosen)
        extra = {}
        for extension, program in sorted(mapping.items()):
            if extension not in covered:
                extra.setdefault(program, []).append(extension)
        for program, types in extra.items():
            self.add_row(types, program)

    def ask_remove(self, what):
        """A row is about to go: True when the person agrees. No is the default. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Zygote — remove this row?', f'Remove {what}?\n\nNothing is saved until you press OK.', QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def remover(self, grid, row_number, widgets, what, forget):
        button = QPushButton('X')
        button.setFixedWidth(28)
        button.setToolTip('Remove this row')
        button.clicked.connect(lambda: self.remove_row(widgets + [button], what, forget))
        return button

    def remove_row(self, widgets, what, forget):
        if not self.ask_remove(what()):
            return False
        forget()
        for widget in widgets:
            widget.hide()
            widget.setParent(None)
            self.removed_widgets.append(widget)
        return True

    def add_row(self, types, chosen):
        number = len(self.rows) + 1
        edit = QLineEdit(', '.join(types))
        combo = QComboBox()
        combo.setMinimumWidth(360)
        self.load_combo(combo, types, chosen)
        combo.activated.connect(lambda _index, box=combo: self.maybe_other(box))
        entry = (edit, combo)
        button = self.remover(self.grid, number, [edit, combo], lambda: 'the row for ' + (edit.text().strip() or 'this empty list'), lambda: self.rows.remove(entry))
        self.grid.addWidget(edit, number, 0)
        self.grid.addWidget(combo, number, 1)
        self.grid.addWidget(button, number, 2)
        self.rows.append(entry)
        self.row_buttons.append(button)
        return entry

    def add_command_row(self, tool=None):
        tool = tool or {'name': '', 'command': '', 'console': True, 'keep_open': True}
        number = len(self.command_rows) + 1
        name, command = QLineEdit(tool['name']), QLineEdit(tool['command'])
        name.setMinimumWidth(120)
        command.setMinimumWidth(320)
        console, keep = QCheckBox(), QCheckBox()
        console.setChecked(bool(tool['console']))
        keep.setChecked(bool(tool['keep_open']))
        entry = {'name': name, 'command': command, 'console': console, 'keep_open': keep}
        button = self.remover(self.command_grid, number, [name, command, console, keep], lambda: 'the tool ' + (name.text().strip() or 'in this empty row'), lambda: self.command_rows.remove(entry))
        for column, widget in enumerate((name, command, console, keep, button)):
            self.command_grid.addWidget(widget, number, column)
        entry['button'] = button
        self.command_rows.append(entry)
        return entry

    def load_combo(self, combo, types, chosen):
        combo.clear()
        combo.addItem("Windows' own choice", core.WINDOWS_OWN)
        offered = []
        for extension in types:
            for program in core.program_choices(extension):
                if program not in offered:
                    offered.append(program)
        if chosen != core.WINDOWS_OWN and chosen not in offered:
            offered.append(chosen)
        for program in offered:
            combo.addItem(program, program)
        combo.addItem(self.OTHER, None)
        combo.setCurrentIndex(max(0, combo.findData(chosen)))

    def pick_program(self):
        program, _ = QFileDialog.getOpenFileName(self, 'Pick the program', '', 'Programs (*.exe *.bat *.cmd);;All files (*)')
        return program

    def maybe_other(self, combo):
        if combo.currentData() is not None:
            return
        program = self.pick_program()
        if not program:
            combo.setCurrentIndex(0)
            return
        combo.insertItem(combo.count() - 1, program, program)
        combo.setCurrentIndex(combo.count() - 2)

    def values(self):
        """{'.md': program, ...} for every row; a type given to two rows fails loud."""
        mapping = {}
        for edit, combo in self.rows:
            for extension in core.split_types(edit.text()):
                if extension in mapping:
                    raise core.ZygoteError(f'The file type {extension} is in two rows.')
                mapping[extension] = combo.currentData() or core.WINDOWS_OWN
        return mapping

    def command_values(self):
        """[{'name', 'command', 'console', 'keep_open'}] for every row that has something in it (a row with nothing typed is left out); a half-filled row fails loud."""
        tools = []
        for entry in self.command_rows:
            name, command = entry['name'].text().strip(), entry['command'].text().strip()
            if not name and not command:
                continue
            tools.append(core.check_command_tool({'name': name, 'command': command, 'console': entry['console'].isChecked(), 'keep_open': entry['keep_open'].isChecked()}))
        return tools

    def accept(self):
        try:
            mapping, tools = self.values(), self.command_values()
            for extension, program in mapping.items():
                core.check_association(extension, program)
            core.save_command_tools(tools)                     # checks the names are different before anything is written
            core.save_associations(mapping)
        except core.ZygoteError as error:
            self.error.setText(str(error))
            return
        self.error.setText('')
        super().accept()


class RevertDialog(QDialog):
    """Project > Revert project…: the drop snapshots kept in the zip folder, newest first. The person picks one; the project goes
    back to how it was before that drop. Result: .chosen (a snapshot file name) after accept()."""

    COLUMNS = ['Drop', 'Version before', 'Version after', 'Saved', 'ZIP that was dropped', 'Files replaced / new']

    def __init__(self, snapshots, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote — revert project')
        self.setMinimumSize(760, 380)
        self.snapshots = snapshots
        self.chosen = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Pick the drop to go back before. Reverting also undoes every drop after it (the ones above it in the list).\n'
                                'The snapshots live in the zip\\undo folder; reverting uses up the ones it undoes.'))
        self.table = QTableWidget(len(snapshots), len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for row, snap in enumerate(snapshots):
            values = [snap['name'].replace('undo_', '').replace('.zip', ''), snap['version_before'] or '?', snap['version_after'] or '?',
                      snap['saved'].replace('T', ' ')[:19], snap['zip'], f'{len(snap["replaced"])} / {len(snap["created"])}']
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        if snapshots:
            self.table.selectRow(0)
        self.table.doubleClicked.connect(self.accept)
        layout.addWidget(self.table, 1)
        self.error = QLabel('' if snapshots else 'There are no snapshots yet: no build ZIP has been dropped on this project.')
        self.error.setObjectName('error')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.revert_button = buttons.addButton('Revert to before this drop', QDialogButtonBox.AcceptRole)
        self.revert_button.setEnabled(bool(snapshots))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.error.setText('Pick one drop in the list first.')
            return
        self.chosen = self.snapshots[rows[0].row()]['name']
        super().accept()


class AboutDialog(QDialog):
    """Help > About Zygote: the icon, the running version, when it was built, and where it lives. Read-only."""

    def __init__(self, parent=None, notice=''):
        super().__init__(parent)
        self.setWindowTitle('About Zygote')
        self.notice = notice
        picture = QLabel()
        picture.setPixmap(QPixmap(str(core.SYSTEM_ASSETS / 'zygote.png')).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        text = QLabel(self.lines(notice))
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row = QHBoxLayout()
        row.addWidget(picture, 0, Qt.AlignTop)
        row.addWidget(text, 1)
        self.update_button = QPushButton('Update')                 # the same as File > Update project's core (the window decides what it does)
        self.update_button.setToolTip("Same as File > Update project's core")
        self.update_button.clicked.connect(self.update_pressed)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.update_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addLayout(buttons)
        self.text = text

    def update_pressed(self):
        """Close this window and do what the File menu item does (when there is a window to do it)."""
        self.accept()
        window = self.parent()
        if window is not None and hasattr(window, 'update_core'):
            window.guarded(window.update_core)

    @staticmethod
    def lines(notice=''):
        """The About text. `notice` is the open project's own copyright and license line (core.license_notice); '' shows none."""
        import platform
        import PySide6
        out = [f'<h2>Zygote {core.RUNNING_VERSION}</h2>', 'A project manager: drop a ZIP, run, test, revert.',
               f'<p>Build date: {html.escape(core.build_date())}</p>']
        if core.restart_pending():
            out.append(f'<p><b>The disk has {html.escape(core.tool_version())}: use File &gt; Restart Zygote to run it.</b></p>')
        out.append(f'<p>Folder: {html.escape(str(core.ZYGOTE_ROOT))}<br>Python {platform.python_version()}, PySide6 {PySide6.__version__}</p>')
        out.append('© Luis R. Lopez (RedHorseVR). All rights reserved.')
        if notice:
            out.append(f'<p><b>This project:</b> {html.escape(notice)}</p>')
        return ''.join(out)


class MakeZipDialog(QDialog):
    """Make ZIP: one short question. ZIP (the default, the update file), EXE (one setup program with the ZIP inside) or both, and the two private
    folders, both unticked. The folder opens afterwards. Result after accept(): .include_user, .include_credentials, .kind ('zip', 'exe' or 'both')."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.include_user = self.include_credentials = False
        self.kind = 'zip'
        self.setWindowTitle('Zygote — make ZIP')
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Make:'))
        self.kind_buttons = {}
        for kind, text in (('zip', 'ZIP  (the update file you drop on Zygote)'),
                           ('exe', 'EXE  (one program with the ZIP inside: double-click it on another computer)'),
                           ('both', 'Both')):
            button = QRadioButton(text)
            button.setChecked(kind == 'zip')
            button.toggled.connect(self.show_where)
            self.kind_buttons[kind] = button
            layout.addWidget(button)
        self.where = QLabel()
        self.where.setWordWrap(True)
        layout.addWidget(self.where)
        layout.addWidget(QLabel('Never in the ZIP: .git, zip, logs and env. The folder opens with the new file selected when it is made.'))
        self.user_box = QCheckBox('Include user info  (.zygote\\user: this project\'s remembered settings: window, shell tabs, AI)')
        self.credentials_box = QCheckBox('Include credentials  (.zygote\\credentials: keys and passwords; do not share this ZIP)')
        for box in (self.user_box, self.credentials_box):
            box.toggled.connect(self.show_where)
            layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.make_button = buttons.addButton('Make', QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.show_where()

    def chosen_kind(self):
        return next(kind for kind, button in self.kind_buttons.items() if button.isChecked())

    def show_where(self):
        dest = core.made_zip_path(self.project, include_user=self.user_box.isChecked(), include_credentials=self.credentials_box.isChecked())
        paths = core.package_paths(dest, self.chosen_kind())
        self.where.setText('Will be written to:\n' + '\n'.join(str(path) for path in paths))

    def accept(self):
        self.include_user = self.user_box.isChecked()
        self.include_credentials = self.credentials_box.isChecked()
        self.kind = self.chosen_kind()
        super().accept()


class DeployDialog(QDialog):
    """Deploy: the questions before the package is made. Top: the options (own window or console) and where the exe goes. Then the optional items (unticked), the
    requirements file when the project has one, and at the bottom every ticked item in groups (the program, assets, versions, Zygote core components), then what is only
    checked on the computer. The tests, notes and hand-over file are never offered. Result after accept(): .requirements (relative path or ''), .window (bool), .args
    (kept as saved; the deployed program's arguments are set in its runner), .ticked (keys of the items to carry). Nothing is made by opening this."""
    BIGGER = 3                                                 # points added to the font: readable on a laptop

    def __init__(self, project, plan, saved, parent=None):
        super().__init__(parent)
        from functional import deploy
        self.requirements, self.window, self.args, self.ticked = saved['requirements'], saved['window'], saved['args'], []
        self.target = saved.get('target', 'folder')
        self.setWindowTitle('Zygote — deploy')
        font = self.font()
        font.setPointSizeF(max(font.pointSizeF(), 9) + self.BIGGER)
        self.setFont(font)
        self.setMinimumSize(780, 560)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        intro = QLabel(f'Deploy makes a package of {plan["name"]} for another computer: a FOLDER with start files (Windows, Linux, Mac; no exe, so Windows Defender leaves it alone), '
                       f'or ONE exe that unpacks the folder {deploy.home_name(project)} beside itself. The exe makes the environment when one is needed and starts {plan["entry"]}; the folder has setup files and makes it when setup is run.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self.heading('Options'))
        self.form_runtime = QRadioButton('Runtime copy: only what runs the program')
        self.form_development = QRadioButton('Development copy: the project to work on, with its Git history')
        self.form_runtime.setChecked(True)
        self.form_development.setEnabled(False)                  # greyed until the development form is built and tested
        self.form_development.setToolTip('Not built yet')
        layout.addWidget(self.form_runtime)
        layout.addWidget(self.form_development)
        self.window_box = QCheckBox('The program has its own window (no console window)')
        self.window_box.setChecked(saved['window'])
        layout.addWidget(self.window_box)
        self.folder_radio = QRadioButton(f'A folder with setup files (setup.bat, setup.sh, setup.command) and the program: {deploy.folder_path(project)}')
        self.exe_radio = QRadioButton(f'One exe (Windows; an antivirus may delete an unsigned one): {deploy.exe_path(project)}')
        (self.exe_radio if saved.get('target') == 'exe' else self.folder_radio).setChecked(True)
        layout.addWidget(self.folder_radio)
        layout.addWidget(self.exe_radio)
        self.requirements_box = None
        offer = deploy.requirements_offer(project)
        if offer:
            layout.addWidget(self.heading('Dependencies'))
            self.requirements_rel = offer[0]
            self.requirements_box = QCheckBox(f'Install the packages listed in {offer[0]} when the program is first started')
            self.requirements_box.setChecked(offer[1])
            layout.addWidget(self.requirements_box)
        self.item_boxes = {}
        self.boxes = {}                                          # title -> its group box (the required ones are greyed out: Deploy decides them)
        program_layout = None
        for title, items in deploy.sections(project):
            required = title != 'Optional (your choice)'
            group = QGroupBox(title)
            column = QVBoxLayout(group)
            for one in items:
                box = QCheckBox(one['label'])
                box.setChecked(one['ticked'])
                box.setEnabled(not one['required'])
                box.setToolTip(one['why'])
                self.item_boxes[one['key']] = box
                column.addWidget(box)
                if one['why']:
                    column.addWidget(self.note(one['why']))
            self.boxes[title] = group
            if title == 'Assets' and program_layout is not None:        # the assets belong to the program: a box inside its box
                program_layout.addWidget(group)
                continue
            if title == 'Program (required)':
                program_layout = column
            group.setEnabled(not required)
            layout.addWidget(group)
        if 'Assets' in self.boxes and program_layout is not None:
            self.boxes['Program (required)'].setEnabled(False)
        elif 'Assets' in self.boxes:
            self.boxes['Assets'].setEnabled(False)
        needs = deploy.runtime_needs(project)
        if needs:
            layout.addWidget(self.heading('Not copied, checked on the computer'))
            for name, what, kind, why in needs:
                layout.addWidget(self.note(f'{name}: {what} ({kind}). {why}'))
        layout.addStretch(1)
        outer.addWidget(self.note('Not in the package: .zygote, app_tree, zip and .git. Make ZIP is the snapshot of the whole project; this is the program.', 0))
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.addButton('Deploy', QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    @staticmethod
    def heading(text):
        label = QLabel(f'<b>{html.escape(text)}</b>')
        label.setObjectName('sectionhead')
        return label

    @staticmethod
    def note(text, indent=26):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName('why')
        label.setStyleSheet(f'margin-left: {indent}px;')       # no colour here: the theme gives the words their contrast
        return label

    def accept(self):
        self.requirements = self.requirements_rel if self.requirements_box is not None and self.requirements_box.isChecked() else ''
        self.window = self.window_box.isChecked()
        self.target = 'exe' if self.exe_radio.isChecked() else 'folder'
        self.ticked = [name for name, box in self.item_boxes.items() if box.isChecked()]
        super().accept()


class RebuildDialog(QDialog):
    """Project > Remake launchers…: the health of each part that can be made again, with a tick box for those that can be. The unhealthy ones start ticked.
    Rebuild: `accepted` (the window does the ticked parts); Cancel closes. Nothing is made by opening this panel."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Remake launchers')
        self.boxes = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>Remake</b>: tick what to make again. Parts that look unhealthy are ticked for you.'))
        for item in items:
            row = QVBoxLayout()
            if item.tickable:
                box = QCheckBox(item.label)
                box.setChecked(item.ticked)
                self.boxes[item.key] = box
                row.addWidget(box)
            else:
                row.addWidget(QLabel(f'<b>{html.escape(item.label)}</b>'))
            note = QLabel(f'{html.escape(item.text)}' if item.tickable else html.escape(item.text))
            note.setWordWrap(True)
            note.setObjectName('why')
            note.setStyleSheet('margin-left: 22px;')
            row.addWidget(note)
            layout.addLayout(row)
        buttons = QDialogButtonBox()
        self.rebuild_button = buttons.addButton('Remake', QDialogButtonBox.AcceptRole)
        buttons.addButton('Cancel', QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def keys(self):
        return [key for key, box in self.boxes.items() if box.isChecked()]


class CleanupDialog(QDialog):
    """Update of the project's core found files that an earlier Zygote made. Each is ticked (it goes to the recycle bin); untick what to keep. OK / Cancel."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote \u2014 tidy up while updating')
        self.items, self.boxes = items, []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('The structure under the project is being updated; you will not notice anything.\n'
                                'These files are left from an earlier Zygote. Untick any you want to keep, then press OK.'))
        for one in items:
            box = QCheckBox(f'{one.path.name}  \u2014  {one.why}')
            box.setChecked(True)
            self.boxes.append(box)
            layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self):
        return [one for one, box in zip(self.items, self.boxes) if box.isChecked()]


class LicenseFields(QWidget):
    """The license settings, one set of boxes for Project > License settings… and Project > New…: developer and organization (each with a copyright tick), the year and ONE
    license line with ONE button. The line's first entry is "(none)", or the NAME of the project's own license file when there is one; the other entries are the standard
    types. The button follows the line: Browse… while there is no license file (it finds one, and the line then shows its name), Open when there is one to show."""

    NONE = '(none)'

    def __init__(self, record, parent=None, project=None):
        super().__init__(parent)
        self.project = project
        self.pending = ''                                        # a file found with Browse…, used when the dialog is accepted
        self.own = core.own_license_file(project, record) if project is not None else ''
        form = QGridLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.developer, self.organization, self.year = QLineEdit(), QLineEdit(), QLineEdit()
        self.developer_copyright, self.organization_copyright = QCheckBox('Copyright'), QCheckBox('Copyright')
        self.type = QComboBox()
        self.button = QPushButton('Browse…')
        form.addWidget(QLabel('Developer'), 0, 0)
        form.addWidget(self.developer, 0, 1)
        form.addWidget(self.developer_copyright, 0, 2)
        form.addWidget(QLabel('Organization'), 1, 0)
        form.addWidget(self.organization, 1, 1)
        form.addWidget(self.organization_copyright, 1, 2)
        form.addWidget(QLabel('Year'), 2, 0)
        form.addWidget(self.year, 2, 1)
        form.addWidget(QLabel('License'), 3, 0)
        form.addWidget(self.type, 3, 1)
        form.addWidget(self.button, 3, 2)
        self.type.currentIndexChanged.connect(self.show_button)
        self.set_record(record)

    def fill_list(self):
        """The first entry shows the license file's name (type Custom: the project's own file) or (none); the rest are the standard types."""
        self.type.blockSignals(True)
        self.type.clear()
        name = Path(self.pending).name if self.pending else self.own
        self.type.addItem(name or self.NONE, 'Custom' if name else '')
        for kind in core.LICENSE_TYPES:
            if kind != 'Custom':
                self.type.addItem(kind, kind)
        self.type.blockSignals(False)

    def set_record(self, record):
        self.developer.setText(record['developer'])
        self.developer_copyright.setChecked(record['developer_copyright'])
        self.organization.setText(record['organization'])
        self.organization_copyright.setChecked(record['organization_copyright'])
        self.year.setText(record['year'])
        self.file = record['file'] if record['type'] == 'Custom' or self.own else core.LICENSE_FILE
        self.fill_list()
        self.type.setCurrentIndex(max(0, self.type.findData(record['type'] if record['type'] not in ('Custom', '') else self.type.itemData(0))))
        self.show_button()

    def has_file(self):
        """True when the line points at a license file that can be shown (the project's own, the file just found, or a standard type's text)."""
        return self.type.currentData() not in ('',)

    def show_button(self):
        self.button.setText('Open' if self.has_file() else 'Browse…')
        self.button.setToolTip('Show the license text' if self.has_file() else 'Find a license file (a file of another project, say) and use it')

    def found(self, path):
        """Browse… found a file: the line shows its name."""
        self.pending = str(path)
        self.fill_list()
        self.type.setCurrentIndex(0)
        self.show_button()

    def shown_file(self):
        """The file Open shows: the project's own / the found one, the LICENSE written for the chosen type, else Zygote's own copy of that type's text."""
        kind = self.type.currentData()
        if kind == 'Custom':
            return Path(self.pending) if self.pending else core.clean_path(self.project) / self.own
        if self.project is not None and (core.clean_path(self.project) / core.LICENSE_FILE).is_file():
            written = core.clean_path(self.project) / core.LICENSE_FILE
            if written.read_text(encoding='utf-8', errors='replace') == core.license_text(dict(self.record(), type=kind)):
                return written
        return core.LICENSE_TEXTS / f'{kind}.txt'

    def record(self):
        kind = self.type.currentData() or ''
        file = core.LICENSE_FILE
        if kind == 'Custom' and self.pending:
            file = (core.project_relative(self.project, self.pending) if self.project is not None else None) or core.LICENSE_FILE    # a file inside the project stays where it is
        elif kind == 'Custom':
            file = self.own or core.LICENSE_FILE
        return {'developer': self.developer.text(), 'developer_copyright': self.developer_copyright.isChecked(), 'organization': self.organization.text(),
                'organization_copyright': self.organization_copyright.isChecked(), 'year': self.year.text(), 'type': kind, 'file': file}


class LicenseDialog(QDialog):
    """Project > License settings…: the project's developer, organization, year and license. OK saves the record in the project's config (it travels in a ZIP). A standard type
    writes LICENSE; a LICENSE that holds something else is asked about first (No is the default) and, when replaced, kept as LICENSE.old. A file found with Browse… is used."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle('Zygote — license settings')
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Copyright and license of {core.project_name(project)}. Saved with the project.'))
        self.fields = LicenseFields(core.license_record(project) or core.license_defaults(), project=project)
        self.fields.button.clicked.connect(self.button_pressed)
        layout.addWidget(self.fields)
        self.error = QLabel('')
        self.error.setObjectName('error')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.result_text = ''

    def pick_license_file(self):
        """The file picker of Browse…: starts in the project. Tests replace this."""
        return QFileDialog.getOpenFileName(self, 'Find the license file', str(core.clean_path(self.project)), 'All files (*)')[0]

    def ask_replace(self, name):
        """A standard type would replace a license file that holds something else. True when the person agrees; No is the default. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Zygote — replace the license file?', f'{name} is in the project and holds another license.\n\nReplace it? The old file is kept as {name}.old.',
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def button_pressed(self):
        try:
            self.error.setText('')
            if self.fields.has_file():
                core.open_file(self.fields.shown_file())
                return
            path = self.pick_license_file()
            if path:
                self.fields.found(path)
        except core.ZygoteError as error:
            self.error.setText(str(error))

    def accept(self):
        try:
            record = self.fields.record()
            if record['type'] == 'Custom' and self.fields.pending:
                record['file'] = core.adopt_license_file(self.project, self.fields.pending)
            elif core.license_file_in_the_way(self.project, record) and not self.ask_replace(record['file']):
                return                                           # No: nothing changes, the box stays open
            saved = core.save_license(self.project, record)
            kind = core.write_license_file(self.project, saved, replace=True)
        except core.ZygoteError as error:
            self.error.setText(str(error))
            return
        self.result_text = {'written': f'License saved; {saved["file"]} written.', 'replaced': f'License saved; {saved["file"]} replaced, the old one is {saved["file"]}.old.',
                            'kept': f'License saved; {saved["file"]} is as it was.'}.get(kind, 'License saved.')
        super().accept()


class NewProjectDialog(QDialog):
    """Project > New…: the name, the folder to make it in, and the license settings. values() is (parent folder, name, license record)."""

    def __init__(self, parent_folder, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Zygote — new project')
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        form = QGridLayout()
        self.name = QLineEdit()
        self.folder = QLineEdit(str(parent_folder))
        self.browse = QPushButton('Browse…')
        self.browse.clicked.connect(self.browse_folder)
        form.addWidget(QLabel('Project name'), 0, 0)
        form.addWidget(self.name, 0, 1, 1, 2)
        form.addWidget(QLabel('Make it in the folder'), 1, 0)
        form.addWidget(self.folder, 1, 1)
        form.addWidget(self.browse, 1, 2)
        layout.addLayout(form)
        layout.addWidget(QLabel('The project folder is made inside that folder. Developer, organization and license can be changed later (Project > License settings…).'))
        self.fields = LicenseFields(core.license_defaults())
        self.fields.button.clicked.connect(self.button_pressed)
        layout.addWidget(self.fields)
        self.error = QLabel('')
        self.error.setObjectName('error')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, 'Make the project in which folder?', self.folder.text())
        if chosen:
            self.folder.setText(chosen)

    def pick_license_file(self):
        """The file picker of Browse…. Tests replace this."""
        return QFileDialog.getOpenFileName(self, 'Find the license file', self.folder.text(), 'All files (*)')[0]

    def button_pressed(self):
        if self.fields.has_file():
            try:
                core.open_file(self.fields.shown_file())
            except core.ZygoteError as error:
                self.error.setText(str(error))
            return
        path = self.pick_license_file()
        if path:
            self.fields.found(path)

    def values(self):
        record = self.fields.record()
        if self.fields.pending:
            record['source'] = self.fields.pending               # copied into the new project as LICENSE (core.create_project)
        return self.folder.text().strip(), self.name.text().strip(), record

    def accept(self):
        try:
            parent, name, record = self.values()
            core.check_new_project(parent, name)
            if record.get('source') and not Path(record['source']).is_file():
                raise core.ZygoteError(f'The license file is not a file: {record["source"]}')
            core.check_license(record)
        except core.ZygoteError as error:
            self.error.setText(str(error))
            return
        super().accept()


class TickListDialog(QDialog):
    """A list of files with a tick each (all unticked), Continue and Cancel. One class for every "which of these may be replaced" question (locked files in a ZIP,
    icons that differ from Zygote's set). Result: .chosen (the keys of the ticked lines) after accept(); Cancel changes nothing."""

    def __init__(self, title, intro, lines, parent=None, ticked=(), pictures=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 340)
        self.chosen = None
        layout = QVBoxLayout(self)
        label = QLabel(intro)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.list = QListWidget()
        self.list.setObjectName('tickbox')
        for key, text in lines:
            entry = QListWidgetItem(text)
            if pictures and pictures.get(key):                      # a line may carry its picture (the standard-layout panel)
                entry.setIcon(QIcon(str(pictures[key])))
            entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
            entry.setCheckState(Qt.Checked if key in ticked else Qt.Unchecked)
            entry.setData(Qt.UserRole, key)
            self.list.addItem(entry)
        layout.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.addButton('Continue', QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        self.chosen = [self.list.item(row).data(Qt.UserRole) for row in range(self.list.count()) if self.list.item(row).checkState() == Qt.Checked]
        super().accept()


class HeldFilesDialog(TickListDialog):
    """A dropped ZIP carries locked files that Zygote cannot call stale: the ticked ones are replaced this once and stay locked, the others are kept as they are."""

    def __init__(self, files, parent=None):
        lines = [(one['rel'], one['rel'] + ('' if one['tracked'] else '     (no fingerprint yet: drop a ZIP and Zygote starts tracking this file)')) for one in files]
        super().__init__('Zygote — locked files in this ZIP',
                         'These files are locked, and the ZIP brings a copy that is not the one it brought last time (or Zygote has no record of the last copy).\n'
                         'Tick the ones the ZIP may replace this once. The others are kept as they are. Every file stays locked.', lines, parent)


class IconsDialog(TickListDialog):
    """Icons of this project that differ from Zygote's own set: the ticked ones are replaced by Zygote's, the others are kept."""

    def __init__(self, names, parent=None):
        super().__init__("Zygote — icons that differ from Zygote's set",
                         "These icons are in this project and are not the same as the ones in Zygote's set.\nTick the ones Zygote may replace. The others are kept as they are.",
                         [(name, name) for name in names], parent)


class SystemCopiesDialog(TickListDialog):
    """Old copies, in this project's icons folder, of pictures Zygote now keeps in its core: all ticked; the ticked ones go to the recycle bin."""

    def __init__(self, names, parent=None):
        super().__init__("Zygote — old copies of Zygote's own pictures",
                         "These files are in this project's icons folder and are exactly the same as the ones Zygote keeps in its core (.zygote\\core\\app\\assets).\n"
                         "Tick the ones to move to the recycle bin. Your own icons are never listed.",
                         [(name, name) for name in names], parent, ticked=names)


class StampDelegate(QStyledItemDelegate):
    """A list line as usual, plus a coloured stamp in capitals at its right end (the layout panel's REQUIRED / IN USE / SOME IN USE): the reason a line cannot be unticked.
    The check box of a locked (in use) line gets a light grey background, so it reads as different from the white boxes of the lines that can be changed."""
    ROLE = Qt.UserRole + 1
    COLOURS = {'REQUIRED': '#5fd35f', 'IN USE': '#ff7a7a', 'SOME IN USE': '#ffc24a'}
    LOCKED_BOX = QColor('#a9a9a9')

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        stamp = index.data(self.ROLE)
        if not stamp:
            return
        painter.save()
        if stamp != 'REQUIRED' and index.data(Qt.CheckStateRole) is not None and not (index.flags() & Qt.ItemIsUserCheckable):
            box = QStyleOptionViewItem(option)
            self.initStyleOption(box, index)
            rect = option.widget.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, box, option.widget)
            painter.setPen(QColor('#555555'))
            painter.setBrush(self.LOCKED_BOX)
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 2, 2)
            mark = QPixmap(str(core.ui_picture('check_dark.png' if Qt.CheckState(index.data(Qt.CheckStateRole)) == Qt.Checked else 'dash_dark.png')))
            painter.drawPixmap(rect, mark)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(self.COLOURS.get(stamp, '#ff7a7a')))
        painter.drawText(option.rect.adjusted(0, 0, -10, 0), Qt.AlignRight | Qt.AlignVCenter, stamp)
        painter.restore()


class LayoutDialog(QDialog):
    """The standard layout panel of Update project's core: every standard item with its own picture; what the project has is ticked. The required lines (START_HERE.md,
    app_tree) are first, greyed, above a separator line. Tick to add, untick to remove: a folder is removed only when it holds nothing but what Zygote made (the person is told
    when it is refused); an icon line adds the missing icons, or moves the icons with Zygote's names to the recycle bin. Result after Continue: .add and .remove (keys).
    Cancel: both empty and .cancelled."""

    GREY = QColor('#8a8a8a')

    def __init__(self, items, parent=None, headline=('', ''), restart=None):
        super().__init__(parent)
        self.setWindowTitle("Zygote \u2014 the standard layout")
        self.items = {one['key']: one for one in items}
        self.add, self.remove, self.cancelled = [], [], True
        layout = QVBoxLayout(self)
        first, second = headline
        top = QLabel(first or 'The standard layout of a Zygote project')
        font = top.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        top.setFont(font)
        top.setWordWrap(True)
        layout.addWidget(top)
        if restart:
            note = QLabel(f'RESTART REQUIRED: this window runs {restart[0]}, the files are {restart[1]}. Zygote restarts after Continue.')
            note.setObjectName('restartwarning')
            layout.addWidget(note)
        sub = QLabel((second or 'What a Zygote project has') + ' \u2014 ticked = this project has it. Tick to add, untick to remove. Hover a line for more.')
        sub.setWordWrap(True)
        layout.addWidget(sub)
        self.list = QListWidget()
        self.list.setObjectName('tickbox')
        self.list.setIconSize(QSize(36, 36))
        self.list.setItemDelegate(StampDelegate(self.list))
        for number, one in enumerate(items):
            entry = QListWidgetItem(f"{one['label']}   \u2014   {one['why']}")
            entry.setData(Qt.UserRole, one['key'])
            if one.get('picture'):
                entry.setIcon(QIcon(str(one['picture'])))
            entry.setToolTip(one['tip'])
            entry.setData(StampDelegate.ROLE, one.get('stamp'))
            if one.get('required'):                                    # no box at all: the system needs it; a grey band and the green word REQUIRED
                entry.setBackground(QBrush(QColor('#3c3c3c')))
                entry.setFlags(entry.flags() & ~Qt.ItemIsUserCheckable)
            else:
                entry.setCheckState({'checked': Qt.Checked, 'partial': Qt.PartiallyChecked, 'unchecked': Qt.Unchecked}[one['state']])
                if one['enabled']:
                    entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
                else:
                    entry.setFlags(entry.flags() & ~Qt.ItemIsUserCheckable)
                    entry.setForeground(QBrush(self.GREY))
            self.list.addItem(entry)
            if one.get('required') and not (number + 1 < len(items) and items[number + 1].get('required')) and number + 1 < len(items):
                line = QListWidgetItem()                                  # the separator under the required group
                line.setFlags(Qt.NoItemFlags)
                line.setSizeHint(QSize(10, 14))
                self.list.addItem(line)
                rule = QFrame()
                rule.setFrameShape(QFrame.HLine)
                rule.setObjectName('layoutrule')
                self.list.setItemWidget(line, rule)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rows = sum(14 if self.list.item(row).data(Qt.UserRole) is None else max(self.list.sizeHintForRow(row), 0) for row in range(self.list.count()))     # (the separator is 14 high)
        self.list.setMinimumHeight(rows + 12)                          # every line shows, no scroll bars
        layout.addWidget(self.list)
        self.setMinimumWidth(900)
        buttons = QHBoxLayout()
        buttons.addStretch()
        go = QPushButton('Continue')
        go.clicked.connect(self.accept)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(go)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def accept(self):
        self.cancelled = False
        for row in range(self.list.count()):
            key = self.list.item(row).data(Qt.UserRole)
            if key is None:
                continue
            one, state = self.items[key], self.list.item(row).checkState()
            if state == Qt.Checked and not one['present']:
                self.add.append(key)
            elif state == Qt.Unchecked and one['enabled'] and (one['present'] or one.get('have')):
                self.remove.append(key)
        super().accept()


class HistoryTree(QTreeWidget):
    """The history list: names can be selected, Ctrl+C copies the selected lines."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            QGuiApplication.clipboard().setText('\n'.join(item.text(0) for item in self.selectedItems()))
            return
        super().keyPressEvent(event)


class HistoryWindow(QDialog):
    """Project > Project history. One entry per event (oldest first). A dropped ZIP is an entry that opens into the files it changed, the locked ones it kept and the
    locked ones you allowed it to replace. Search and a filter (all, drops, locked); a double-click on a file opens it; Ctrl+C copies the selected lines.
    Archive: the selected entry and every entry above it go into a ZIP and one coloured line stands for them; a double-click on that line opens them in the list again,
    and closing the window asks whether to put the opened archive back."""
    FILTERS = ('All', 'Drops', 'Locked')

    def __init__(self, title, data, project, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.resize(900, 640)
        self.project = Path(project)
        self.opened = []                                           # the archive lines opened in the list, in the order they were opened
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search')
        self.search.setClearButtonEnabled(True)
        self.filter = QComboBox()
        self.filter.addItems(self.FILTERS)
        top.addWidget(self.search, 1)
        top.addWidget(self.filter)
        layout.addLayout(top)
        self.tree = HistoryTree()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.fill(data)
        layout.addWidget(self.tree, 1)
        self.archive_button = QPushButton('Archive up to the selected entry')
        self.archive_button.clicked.connect(self.archive_selected)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addWidget(self.archive_button)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        self.search.textChanged.connect(self.apply_filter)
        self.filter.currentIndexChanged.connect(self.apply_filter)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.itemSelectionChanged.connect(self.sync_archive_button)
        self.sync_archive_button()
        self.tree.scrollToBottom()

    def fill(self, data):
        self.tree.clear()
        self.heads = [QTreeWidgetItem(self.tree, [f'Started with Zygote:       {data.get("started_with", "?")}']),
                      QTreeWidgetItem(self.tree, [f'Last opened with Zygote:   {data.get("last_upgraded_to", "?")}'])]
        for event in data.get('events', []):
            self.add_event(event, self.tree.topLevelItemCount())
        self.collect_events()

    def collect_events(self):
        """self.events = the entry rows of the list, in the order shown (the two lines at the top are not entries)."""
        self.events = [self.tree.topLevelItem(row) for row in range(len(self.heads), self.tree.topLevelItemCount())]

    def add_event(self, event, row):
        when = datetime.datetime.fromisoformat(event['when'])
        drop = event.get('drop')
        archive = event.get('archive')
        top = QTreeWidgetItem([f'{when:%Y-%m-%d %H:%M}   [Zygote {event.get("zygote", "?")}]   {event.get("what", "")}'])
        self.tree.insertTopLevelItem(row, top)
        top.setData(0, Qt.UserRole + 1, bool(drop))
        top.setData(0, Qt.UserRole + 2, bool(drop and (drop.get('kept') or drop.get('overridden'))))
        top.setData(0, Qt.UserRole + 3, archive)                   # an archive line carries its record (zip, count, first, last)
        if archive:
            first, last = datetime.datetime.fromisoformat(archive['first']), datetime.datetime.fromisoformat(archive['last'])
            top.setText(0, f'Archived: {first:%Y-%m-%d} to {last:%Y-%m-%d}, {archive["count"]} entries   (double-click to open)')
            top.setForeground(0, QBrush(QColor(Theme.colors()['bright'])))
            top.setToolTip(0, archive['zip'])
        if drop:
            top.setText(0, f'{when:%Y-%m-%d %H:%M}   {drop.get("zip", "")}:  {drop.get("before") or "?"} -> {drop.get("after") or "?"}   '
                           f'changed {len(drop.get("changed", []))}, kept locked {len(drop.get("kept", []))}, replaced locked {len(drop.get("overridden", []))}   [Zygote {event.get("zygote", "?")}]')
            for label, key in (('Changed', 'changed'), ('Kept because locked', 'kept'), ('Locked, replaced because you allowed it', 'overridden')):
                names = drop.get(key, [])
                if names:
                    section = QTreeWidgetItem(top, [f'{label} ({len(names)})'])
                    for name in names:
                        QTreeWidgetItem(section, [name]).setData(0, Qt.UserRole, name)
        return top

    def entry_row(self, item):
        """The top-level entry that holds this item (the item itself when it is one), or None."""
        while item is not None and item.parent() is not None:
            item = item.parent()
        return item if item in self.events else None

    def sync_archive_button(self):
        """Archive works on the entries as they are on disk, so it waits while an archive is open in the list."""
        self.archive_button.setEnabled(not self.opened and self.selected_entry() is not None)
        self.archive_button.setToolTip('Put the opened archive back first (close this window)' if self.opened else 'The selected entry and every entry above it are packed into a ZIP')

    def selected_entry(self):
        rows = [self.entry_row(item) for item in self.tree.selectedItems()]
        rows = [row for row in rows if row is not None]
        return max(rows, key=self.events.index) if rows else None

    def ask_archive(self, count, first, last):
        """Archive asks first, naming how many entries and the dates. No is the default. Tests replace this."""
        return QMessageBox.question(self, 'Zygote — archive', f'Pack {count} entries ({first:%Y-%m-%d} to {last:%Y-%m-%d}) into a ZIP and leave one line?\n'
                                    'The ZIP stays in the notes folder; a double-click on the line opens them again.', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def archive_selected(self):
        chosen = self.selected_entry()
        if chosen is None or self.opened:
            return
        last_index = self.events.index(chosen)
        data = core.load_history(self.project)
        packed = data['events'][:last_index + 1]
        count = sum(core.entry_count(one) for one in packed)
        if not self.ask_archive(count, datetime.datetime.fromisoformat(packed[0]['when']), datetime.datetime.fromisoformat(packed[-1]['when'])):
            return
        core.archive_history(self.project, last_index)
        self.fill(core.load_history(self.project))
        self.apply_filter()
        self.sync_archive_button()

    def ask_put_back(self):
        """Closing with an archive open: put it back (one line again, nothing rewritten)? Yes is the default. Tests replace this."""
        return QMessageBox.question(self, 'Zygote — archive', 'Put the opened archive back?', QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes

    def reject(self):
        """Closing (the button, Esc, the window's X). Yes keeps the archive as it is on disk. No leaves its entries in the history for good."""
        if self.opened and not self.ask_put_back():
            for record in self.opened:
                core.unpack_archive(self.project, record['zip'])
            self.opened = []
        super().reject()

    def apply_filter(self):
        """Show the entries that pass the filter and hold the search words (in the entry line or in a file name); with a search, only the matching files are left under an entry."""
        word = self.search.text().strip().lower()
        mode = self.filter.currentText()
        for top in self.events:
            passes = mode == 'All' or (mode == 'Drops' and top.data(0, Qt.UserRole + 1)) or (mode == 'Locked' and top.data(0, Qt.UserRole + 2))
            matches = self.show_matches(top, word)
            top.setHidden(not (passes and matches))
        for head in self.heads:
            head.setHidden(bool(word) or mode != 'All')

    def show_matches(self, top, word):
        if not word:
            self.reset(top)
            return True
        found = word in top.text(0).lower()
        for index in range(top.childCount()):
            section = top.child(index)
            hits = 0
            for number in range(section.childCount()):
                one = section.child(number)
                match = word in one.text(0).lower()
                one.setHidden(not (match or found))
                hits += match
            section.setHidden(not (hits or found))
            if hits:
                section.setExpanded(True)
                found = True
        return found

    def reset(self, top):
        for index in range(top.childCount()):
            top.child(index).setHidden(False)
            for number in range(top.child(index).childCount()):
                top.child(index).child(number).setHidden(False)

    def open_item(self, item):
        archive = item.data(0, Qt.UserRole + 3)
        if archive:
            self.open_archive(item, archive)
            return
        rel = item.data(0, Qt.UserRole)
        if rel and (self.project / rel).exists():
            core.open_file(self.project / rel)

    def open_archive(self, item, archive):
        """The archive line is replaced in the list by the entries inside it (the disk is not changed: closing asks whether they go back)."""
        row = self.tree.indexOfTopLevelItem(item)
        self.tree.takeTopLevelItem(row)
        for number, event in enumerate(core.read_archive(self.project, archive['zip'])):
            self.add_event(event, row + number)
        self.opened.append(archive)
        self.collect_events()
        self.apply_filter()
        self.sync_archive_button()

    def all_text(self):
        """Every line of the list, sections and files included (for tests and for copying all)."""
        lines = []
        for row in range(self.tree.topLevelItemCount()):
            self.add_lines(lines, self.tree.topLevelItem(row), 0)
        return '\n'.join(lines)

    def add_lines(self, lines, item, depth):
        lines.append('  ' * depth + item.text(0))
        for index in range(item.childCount()):
            self.add_lines(lines, item.child(index), depth + 1)
