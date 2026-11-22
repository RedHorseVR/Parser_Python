"""The folder view (icons and details) and the path bar above it.

The views take drops of two kinds only, both made by Zygote itself: green items dropped on the recycle bin row (thrown away), and items dragged
out of the recycle bin window (put into the folder in view). A drop from the desktop or Explorer goes to the main window as before (a project
folder or a build ZIP); it never reaches the recycle bin."""
from pathlib import Path

from PySide6.QtCore import QModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QListView, QMenu, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeView

from ui_ux.lazy_model import PATHS_FORMAT
from ui_ux.recycle import SLOTS_FORMAT


class BinDrops:
    """What the two views share (one code path): drops on the recycle bin row, drops of bin items on the folder in view."""
    def bin_target(self, event):
        """The row under the pointer when it can take a drop: the recycle bin row or a folder (a folder takes the green items moved into it)."""
        index = self.indexAt(event.position().toPoint())
        model = self.model()
        return index if model.is_bin(index) or model.is_folder_target(index) else QModelIndex()

    def dragEnterEvent(self, event):
        self.refused_told = False
        if event.mimeData().hasFormat(PATHS_FORMAT) or event.mimeData().hasFormat(SLOTS_FORMAT):
            event.acceptProposedAction()
        else:
            self.window().dragEnterEvent(event)                 # the desktop and Explorer: the main window (open a project, unpack a ZIP)

    def dragMoveEvent(self, event):
        data = event.mimeData()
        if data.hasFormat(SLOTS_FORMAT):
            event.acceptProposedAction()
        elif data.hasFormat(PATHS_FORMAT):
            target = self.bin_target(event)
            if target.isValid() and self.model().canDropMimeData(data, Qt.MoveAction, -1, -1, target):
                event.acceptProposedAction()
            else:
                event.ignore()                                  # the no-drop cursor
                if target.isValid() and not getattr(self, 'refused_told', False):
                    self.refused_told = True
                    names = ', '.join(Path(path).name for path in self.model().dragged_paths(data))
                    if self.model().is_bin(target):
                        self.refused.emit(f'Refused by the recycle bin: {names} (only the green items you work on can be thrown away).')
                    else:
                        self.refused.emit(f'Not moved into {target.data()}: {names} (only the green items you work on can be moved, and not into themselves or into Zygote folders).')
        else:
            self.window().dragEnterEvent(event)

    def dropEvent(self, event):
        data = event.mimeData()
        if data.hasFormat(SLOTS_FORMAT):
            self.restoreDropped.emit(bytes(data.data(SLOTS_FORMAT)).decode('utf-8').split('\n'))
            event.acceptProposedAction()
        elif data.hasFormat(PATHS_FORMAT):
            target = self.bin_target(event)
            if target.isValid() and self.model().dropMimeData(data, Qt.MoveAction, -1, -1, target):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            self.window().dropEvent(event)


class UpButton(QPushButton):
    """The up-one-folder button. Green items of Zygote's own folder view dropped on it are moved out, into the folder above the one in view."""
    movedOut = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PATHS_FORMAT) and self.isEnabled():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = bytes(event.mimeData().data(PATHS_FORMAT)).decode('utf-8').split('\n')
        self.movedOut.emit(paths)
        event.acceptProposedAction()


class FullNameDelegate(QStyledItemDelegate):
    """The icon view cuts a long name with … . The item that is selected shows its whole name instead, wrapped inside its own highlight (the way Explorer does)."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        if isinstance(painter.device(), (QPixmap, QImage)):         # the picture that follows the mouse in a drag is made from the cell alone: the taller highlight would be cut to its top few pixels
            super().paint(painter, option, index)
            return
        if not (opt.state & QStyle.State_Selected) or not text or opt.decorationPosition != QStyleOptionViewItem.Top:
            super().paint(painter, option, index)
            return
        width = max(option.rect.width() - 8, 10)
        needed = opt.fontMetrics.boundingRect(QRect(0, 0, width, 1000), int(Qt.AlignHCenter | Qt.TextWrapAnywhere), text).height()
        room = option.rect.height() - opt.decorationSize.height() - 8
        if needed <= room:
            super().paint(painter, option, index)
            return
        opt.textElideMode = Qt.ElideNone
        opt.features |= QStyleOptionViewItem.WrapText
        opt.rect = option.rect.adjusted(0, 0, 0, needed - room)          # taller than its cell, drawn over what is below it
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)


class FolderIcons(BinDrops, QListView):
    refused = Signal(str)                                      # a refused drop on the recycle bin row (the Log says it)
    restoreDropped = Signal(list)                              # slots dragged out of the bin and dropped on the view

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(FullNameDelegate(self))

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        self.viewport().update()                               # the taller highlight of the selected item covers its neighbours: draw them again


class FolderDetails(BinDrops, QTreeView):
    refused = Signal(str)
    restoreDropped = Signal(list)


class PathBar(QLabel):
    """The title of the folder view: the path from the project's name, each name a link to that level, the folder in view plain. A path that
    does not fit keeps the project's name and the last folders, with … for the middle (it opens a list of the hidden levels)."""
    chosen = Signal(str)

    ARROW = '  →  '

    def __init__(self):
        super().__init__('')
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.setMinimumWidth(40)
        self.segments = []                                     # [(name, path)] from the first level to the folder in view
        self.plain = ''
        self.hidden = []
        self.linkActivated.connect(self.clicked)

    def text(self):
        return self.plain

    def show_path(self, segments):
        self.segments = list(segments)
        self.plain = self.ARROW.join(name for name, _ in self.segments)
        self.setToolTip(self.segments[-1][1] if self.segments else '')
        self.refit()

    def fits(self, shown):
        return self.fontMetrics().horizontalAdvance(self.ARROW.join(name for name, _ in shown)) <= max(self.width() - 12, 40)

    def refit(self):
        """Show all the levels when they fit; else the first, … and as many of the last ones as fit (at least the folder in view)."""
        segments = self.segments
        self.hidden = []
        shown = segments
        if segments and not self.fits(segments):
            keep = len(segments) - 1
            while keep > 1 and not self.fits([segments[0], ('…', '')] + segments[-keep:]):
                keep -= 1
            shown = [segments[0], ('…', '')] + segments[-max(keep, 1):]
            self.hidden = segments[1:len(segments) - max(keep, 1)]
        parts = []
        for number, (name, path) in enumerate(shown):
            if name == '…' and not path:
                parts.append('<a href="zygote:hidden" style="text-decoration:none">…</a>')
            elif number == len(shown) - 1:
                parts.append(f'<b>{name}</b>')
            else:
                parts.append(f'<a href="{path}" style="text-decoration:none">{name}</a>')
        QLabel.setText(self, self.ARROW.join(parts))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refit()

    def clicked(self, href):
        if href == 'zygote:hidden':
            menu = QMenu(self)
            for name, path in self.hidden:
                menu.addAction(name, lambda p=path: self.chosen.emit(p))
            menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        else:
            self.chosen.emit(href)
