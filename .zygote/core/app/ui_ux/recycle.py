"""The recycle bin: its picture (drawn here, it is also the picture of its window) and its window.

The window is not modal and is owned by the main window (it floats above it, goes with it). Each item has a tick, its name, the place it came
from and the date and time it was thrown away. Restore puts the ticked ones back where they came from; Empty deletes the ticked ones for good
(after a question that says how many and that it cannot be undone). Drag an item out of the bin onto the folder view to put it into that folder;
drag a green item of the folder view onto the bin to throw it away. Nothing from the desktop or Explorer is accepted."""
from pathlib import Path

from PySide6.QtCore import QFileInfo, QMimeData, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileIconProvider, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from functional import core
from ui_ux.lazy_model import PATHS_FORMAT

SLOTS_FORMAT = 'application/x-zygote-trash'                    # what a drag out of the bin carries: the slots of the items


def bin_icon(full=True):
    """The recycle bin pictures (app_tree\\assets\\ui\\recycle_bin.png with paper, recycle_bin_empty.png): the bin row and the window icon."""
    return QIcon(str(core.ui_picture('recycle_bin.png' if full else 'recycle_bin_empty.png')))


class BinTree(QTreeWidget):
    """The list of the bin; an item dragged out carries its slot, for the folder view to put into the folder it is dropped on."""

    def mimeTypes(self):
        return [SLOTS_FORMAT]

    def mimeData(self, items):
        data = QMimeData()
        data.setData(SLOTS_FORMAT, '\n'.join(item.data(0, Qt.UserRole) for item in items).encode('utf-8'))
        return data


class BinIcons(QListWidget):
    """The icon view of the bin: each item is a picture with its name and a tick box; dragged out like the list's items."""

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWordWrap(True)
        self.setSpacing(8)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def mimeTypes(self):
        return [SLOTS_FORMAT]

    def mimeData(self, items):
        data = QMimeData()
        data.setData(SLOTS_FORMAT, '\n'.join(item.data(Qt.UserRole) for item in items).encode('utf-8'))
        return data


class TrashWindow(QDialog):
    refused = Signal(str)                                      # a drop that was not accepted, and why (the Log says it)
    changed = Signal()                                         # the trash or the project's folders changed (the views refresh)
    thrown = Signal(list)                                      # paths dropped on the window: the main window throws them away

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = Path(project)
        self.setModal(False)
        self.setWindowTitle('Recycle bin')
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(640, 380)
        self.setAcceptDrops(True)
        self.select_all = QCheckBox('Select all')
        self.select_all.setTristate(False)
        self.select_all.clicked.connect(self.tick_all)
        self.items = BinTree()
        self.items.setHeaderLabels(['Name', 'From', 'Thrown away'])
        self.items.setRootIsDecorated(False)
        self.items.setAlternatingRowColors(False)
        self.items.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.items.setDragEnabled(True)
        self.items.setDragDropMode(QAbstractItemView.DragOnly)
        self.items.itemChanged.connect(self.ticks_changed)
        self.icons = BinIcons()
        self.icons.itemChanged.connect(self.icon_ticked)
        self.view_stack = QStackedWidget()                         # the list or the icons: the same items, the same ticks
        self.view_stack.addWidget(self.items)
        self.view_stack.addWidget(self.icons)
        self.view_button = QPushButton('Icon view')
        self.view_button.setObjectName('toolbutton')
        self.view_button.setToolTip('Switch the bin between the list and the icons')
        self.view_button.clicked.connect(self.switch_view)
        self.status = QLabel('')
        self.restore_button = QPushButton('Restore')
        self.restore_button.setToolTip('Put the ticked items back where they came from')
        self.empty_button = QPushButton('Empty')
        self.empty_button.setToolTip('Delete the ticked items for good; asks first')
        self.restore_button.clicked.connect(self.restore)
        self.empty_button.clicked.connect(self.empty)
        row = QHBoxLayout()
        row.addWidget(self.restore_button)
        row.addWidget(self.empty_button)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.select_all)
        top.addStretch(1)
        top.addWidget(self.view_button)
        layout.addLayout(top)
        layout.addWidget(self.view_stack, 1)
        layout.addWidget(self.status)
        layout.addLayout(row)
        self.reload()

    def switch_view(self):
        """The button next to Select all: its name is the view it switches TO."""
        icons = self.view_stack.currentWidget() is self.items
        self.view_stack.setCurrentWidget(self.icons if icons else self.items)
        self.view_button.setText('List view' if icons else 'Icon view')

    # ---- the list -----------------------------------------------------------------------------------------------
    def reload(self):
        self.items.blockSignals(True)
        self.icons.blockSignals(True)
        self.items.clear()
        self.icons.clear()
        found = core.trash_items(self.project)
        for item in found:
            entry = QTreeWidgetItem([item['name'], item['from'], item['when'].replace('T', ' ')[:16]])
            entry.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            entry.setCheckState(0, Qt.Unchecked)
            entry.setData(0, Qt.UserRole, str(item['slot']))
            self.items.addTopLevelItem(entry)
            tile = QListWidgetItem(item['name'])
            tile.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            tile.setCheckState(Qt.Unchecked)
            tile.setData(Qt.UserRole, str(item['slot']))
            tile.setIcon(QFileIconProvider().icon(QFileInfo(str(Path(item['slot']) / item['name']))))
            tile.setToolTip(f"{item['from']}  ({item['when'].replace('T', ' ')[:16]})")
            self.icons.addItem(tile)
        for column in range(3):
            self.items.resizeColumnToContents(column)
        self.items.blockSignals(False)
        self.icons.blockSignals(False)
        self.setWindowIcon(bin_icon(bool(found)))                  # paper in it, or empty
        self.status.setText(f'{len(found)} item(s) in the recycle bin.' if found else 'The recycle bin is empty.')
        self.ticks_changed()

    def entries(self):
        return [self.items.topLevelItem(row) for row in range(self.items.topLevelItemCount())]

    def ticked(self):
        return [entry.data(0, Qt.UserRole) for entry in self.entries() if entry.checkState(0) == Qt.Checked]

    def tick_all(self, on):
        self.items.blockSignals(True)
        self.icons.blockSignals(True)
        for row, entry in enumerate(self.entries()):
            entry.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
            self.icons.item(row).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.items.blockSignals(False)
        self.icons.blockSignals(False)
        self.ticks_changed()

    def icon_ticked(self, tile):
        """A tick box of the icon view: the list keeps the same tick (the list holds the truth)."""
        self.items.blockSignals(True)
        self.items.topLevelItem(self.icons.row(tile)).setCheckState(0, tile.checkState())
        self.items.blockSignals(False)
        self.ticks_changed()

    def ticks_changed(self, entry=None, *_):
        """Restore and Empty need at least one ticked item; Select all follows the ticks; the icon view shows the same ticks."""
        self.icons.blockSignals(True)
        for row, each in enumerate(self.entries()):
            self.icons.item(row).setCheckState(each.checkState(0))
        self.icons.blockSignals(False)
        count, total = len(self.ticked()), self.items.topLevelItemCount()
        self.restore_button.setEnabled(count > 0)
        self.empty_button.setEnabled(count > 0)
        self.select_all.setEnabled(total > 0)
        self.select_all.blockSignals(True)
        self.select_all.setChecked(total > 0 and count == total)
        self.select_all.blockSignals(False)

    # ---- the two buttons ----------------------------------------------------------------------------------------
    def restore(self):
        slots = self.ticked()
        if not slots:
            return
        put, failed = [], []
        for slot in slots:
            try:
                put.append(core.restore_item(self.project, slot).name)
            except core.ZygoteError as error:
                failed.append(str(error))
        self.reload()
        self.status.setText(f'Put back: {", ".join(put)}.' + (' ' + ' '.join(failed) if failed else '') if put or failed else '')
        self.changed.emit()

    def ask_empty(self, count):
        """The guard: how many go for good, that it cannot be undone, and No is the default. Tests replace this."""
        box = QMessageBox(QMessageBox.Warning, 'Empty the recycle bin',
                          f'Delete {count} item(s) for good?\n\nThis cannot be undone.', QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def empty(self):
        slots = self.ticked()
        if slots and self.ask_empty(len(slots)):
            count = core.empty_trash(self.project, slots)
            self.reload()
            self.status.setText(f'{count} item(s) deleted for good.')
            self.changed.emit()

    # ---- drops: only green items of this project's folder view -----------------------------------------------------
    def accepts(self, data):
        if not data.hasFormat(PATHS_FORMAT):
            self.refused.emit('Refused by the recycle bin: only items dragged from this project\'s folder view can go in (nothing from the desktop or Explorer).')
            return False
        paths = bytes(data.data(PATHS_FORMAT)).decode('utf-8').split('\n')
        bad = [Path(path).name for path in paths if not core.can_trash(self.project, path)]
        if bad:
            self.refused.emit(f'Refused by the recycle bin: {", ".join(bad)} (only the green items you work on can be thrown away).')
            return False
        return True

    def dragEnterEvent(self, event):
        if self.accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction() if event.mimeData().hasFormat(PATHS_FORMAT) else event.ignore()

    def dropEvent(self, event):
        if self.accepts(event.mimeData()):
            self.thrown.emit(bytes(event.mimeData().data(PATHS_FORMAT)).decode('utf-8').split('\n'))
            event.acceptProposedAction()
