"""The code window: read-only source files in tabs, with line numbers. Click a line number to set or clear a breakpoint (a red circle); the line the
debugger stopped on has an arrow and a coloured band. One tab per file, named with the file name (the parent folder is added only when two tabs
would read the same, a long name is shortened in the middle with …, the full path shows when the mouse rests on the tab)."""
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, QObject, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPolygonF, QTextFormat
from PySide6.QtWidgets import QLabel, QListWidget, QPlainTextEdit, QTabBar, QTabWidget, QTextEdit, QVBoxLayout, QWidget

from functional import core
from ui_ux import highlighter
from ui_ux.lazy_model import PATHS_FORMAT

BACK, TEXT, GUTTER, NUMBER = '#1e1e1e', '#d4d4d4', '#2b2b2b', '#858585'
BREAKPOINT, HERE, BAND = '#e51400', '#ffcc00', '#3a3d41'
MAX_TAB_NAME = 24


def disk_stamp(path):
    """(modified time in ns, size) of a file, or None when it is not there: two stamps that differ mean the file changed."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def read_source(path):
    """The text of a file for the code window (UTF-8, anything unreadable replaced), or None when it is not a file, too large, or binary."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > core.MAX_TEXT_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b'\x00' in data:
        return None
    return data.decode('utf-8', errors='replace').replace('\r\n', '\n')


class Gutter(QWidget):
    """The strip with the line numbers, beside a CodeView. It only asks the view to draw it and to say what a click means."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Click a line number: set or clear a breakpoint')

    def sizeHint(self):
        return self.view.gutter_size()

    def paintEvent(self, event):
        self.view.paint_gutter(self, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.view.gutter_clicked(event.position().toPoint().y())


class CodeView(QPlainTextEdit):
    breakpointClicked = Signal(int)                                 # a line number was clicked (1-based)

    def __init__(self, path, text, breakpoints, parent=None):
        super().__init__(parent)
        self.path = str(path)
        self.breakpoints = set(breakpoints)
        self.current = 0                                            # the line the debugger stopped on (0 = none)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(10)
        self.setFont(font)
        palette = self.palette()
        palette.setColor(QPalette.Base, QColor(BACK))
        palette.setColor(QPalette.Text, QColor(TEXT))
        self.setPalette(palette)
        self.setPlainText(text)
        self.colours = highlighter.attach(self.document(), self.path)   # None when the language is not known
        self.stamp = disk_stamp(self.path)                             # what the disk held when the text was read
        self.gutter = Gutter(self)
        self.blockCountChanged.connect(self.fit_gutter)
        self.updateRequest.connect(self.scroll_gutter)
        self.fit_gutter()

    def gutter_size(self):
        digits = len(str(max(1, self.blockCount())))
        return QRect(0, 0, 26 + self.fontMetrics().horizontalAdvance('9') * digits, 0).size()

    def fit_gutter(self):
        self.setViewportMargins(self.gutter_size().width(), 0, 0, 0)

    def scroll_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.fit_gutter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        area = self.contentsRect()
        self.gutter.setGeometry(QRect(area.left(), area.top(), self.gutter_size().width(), area.height()))

    def paint_gutter(self, gutter, event):
        painter = QPainter(gutter)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(event.rect(), QColor(GUTTER))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            line = block.blockNumber() + 1
            if block.isVisible() and top + height >= event.rect().top():
                painter.setPen(QColor(NUMBER))
                painter.drawText(0, top, gutter.width() - 6, height, Qt.AlignRight | Qt.AlignVCenter, str(line))
                if line in self.breakpoints:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(BREAKPOINT))
                    painter.drawEllipse(QPointF(8, top + height / 2), 5, 5)
                if line == self.current:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(HERE))
                    middle = top + height / 2
                    painter.drawPolygon(QPolygonF([QPointF(14, middle - 5), QPointF(21, middle), QPointF(14, middle + 5)]))
            block = block.next()
            top += height
        painter.end()

    def gutter_clicked(self, y):
        line = self.cursorForPosition(QPoint(0, y)).blockNumber() + 1
        if 1 <= line <= self.blockCount():
            self.breakpointClicked.emit(line)

    def reload_text(self, text):
        """New text from disk. The place in the file stays: the scroll position and the cursor line (the lines of a changed file may have moved)."""
        if text == self.toPlainText():
            return False
        line = self.textCursor().blockNumber()
        scroll = self.verticalScrollBar().value()
        self.setPlainText(text)
        cursor = self.textCursor()
        cursor.setPosition(self.document().findBlockByNumber(min(line, self.blockCount() - 1)).position())
        self.setTextCursor(cursor)
        self.verticalScrollBar().setValue(scroll)
        self.set_current(self.current)
        return True

    def set_breakpoints(self, lines):
        self.breakpoints = set(lines)
        self.gutter.update()

    def set_current(self, line):
        """Show where the debugger stopped (0 = nowhere): the band, the arrow, and the line is scrolled into the middle."""
        self.current = line
        selections = []
        if line:
            cursor = self.textCursor()
            cursor.setPosition(self.document().findBlockByNumber(line - 1).position())
            self.setTextCursor(cursor)
            self.centerCursor()
            mark = QTextEdit.ExtraSelection()
            mark.format.setBackground(QColor(BAND))
            mark.format.setProperty(QTextFormat.FullWidthSelection, True)
            mark.cursor = cursor
            selections.append(mark)
        self.setExtraSelections(selections)
        self.gutter.update()


def tab_names(paths):
    """The tab label of each path: the file name; with the parent folder in front when two paths share a name; shortened in the middle when long."""
    names = [Path(path).name for path in paths]
    labels = []
    for path, name in zip(paths, names):
        label = f'{Path(path).parent.name}/{name}' if names.count(name) > 1 else name
        if len(label) > MAX_TAB_NAME:
            keep = (MAX_TAB_NAME - 1) // 2
            label = label[:keep] + '…' + label[-keep:]
        labels.append(label)
    return labels


class CodeTabBar(QTabBar):
    """The tabs of the code window. A tab dragged 40 pixels or more above or below the bar is torn away as a shell tab is: it follows the cursor
    (the main window shows a ghost of it) and the whole code window opens in a window of its own where the mouse is let go."""
    tear_wanted = Signal(QPoint)                                    # the tab left the bar (where on screen)
    tear_moved = Signal(QPoint)                                     # the torn tab is carried (the mouse is still down)
    tear_dropped = Signal(QPoint)                                   # where on screen the mouse was let go
    TEAR_DISTANCE = 40

    def __init__(self):
        super().__init__()
        self.dragging = False                                       # the left button went down on a tab
        self.tearing = False                                        # the tab is being carried

    def mousePressEvent(self, event):
        self.dragging = event.button() == Qt.LeftButton and self.tabAt(event.position().toPoint()) >= 0
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.tearing:
            self.tear_moved.emit(event.globalPosition().toPoint())
            return
        if self.dragging and event.buttons() & Qt.LeftButton:
            if not self.rect().adjusted(0, -self.TEAR_DISTANCE, 0, self.TEAR_DISTANCE).contains(event.position().toPoint()):
                self.tearing = True
                self.tear_wanted.emit(event.globalPosition().toPoint())
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was, self.dragging, self.tearing = self.tearing, False, False
        super().mouseReleaseEvent(event)
        if was:
            self.tear_dropped.emit(event.globalPosition().toPoint())


class CodeFloat(QWidget):
    """The code window torn away: a window of its own. Its X closes it for real (the main window asks first when several files are open);
    minimizing it puts the code window back beside the Console."""
    dock_wanted = Signal()                                          # minimized
    close_wanted = Signal()                                         # the X

    def __init__(self, code):
        super().__init__(None, Qt.Window)
        self.setWindowTitle('Zygote: code')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(code)
        code.show()
        self.resize(820, 520)

    def event(self, event):
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            self.setWindowState(Qt.WindowNoState)
            self.dock_wanted.emit()
        return super().event(event)

    def closeEvent(self, event):
        event.ignore()
        self.close_wanted.emit()


class DropToCode(QObject):
    """Installed on a widget (the Debug console): files dragged from Zygote's folder view onto it are handed on to open in the code window."""
    dropped = Signal(list)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.DragEnter, QEvent.DragMove) and event.mimeData().hasFormat(PATHS_FORMAT):
            event.acceptProposedAction()
            return True
        if kind == QEvent.Drop and event.mimeData().hasFormat(PATHS_FORMAT):
            self.dropped.emit(bytes(event.mimeData().data(PATHS_FORMAT)).decode('utf-8').split('\n'))
            event.acceptProposedAction()
            return True
        return False


class BreakpointsWindow(QWidget):
    """The breakpoints of the project: a window of its own with one tab per file, each listing its breakpoint lines (line number and the text)."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle('Zygote: breakpoints')
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.note = QLabel('No breakpoints. Click a line number in the code window to set one.')
        self.note.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.note)
        layout.addWidget(self.tabs)
        self.resize(520, 320)

    def show_found(self, found):
        """found: {file path: [line numbers]}. The tabs are made again each time."""
        self.tabs.clear()
        paths = list(found)
        for path, label in zip(paths, tab_names(paths)):
            try:
                text = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
            except OSError:
                text = []
            page = QListWidget()
            for line in found[path]:
                page.addItem(f'line {line}    {text[line - 1].strip() if 0 < line <= len(text) else ""}')
            index = self.tabs.addTab(page, label)
            self.tabs.setTabToolTip(index, path)
        self.note.setVisible(not paths)
        self.tabs.setVisible(bool(paths))


class CodeWindow(QTabWidget):
    breakpointToggled = Signal(str, int)                            # (file, line): the person clicked a line number
    emptied = Signal()                                              # the last tab was closed
    fileReloaded = Signal(str)                                      # a tab's text was replaced by what the disk holds now
    pathsDropped = Signal(list)                                     # files dragged here from Zygote's own folder view
    dropRefused = Signal(str)                                       # a drop that was not accepted, and why (the Log says it)
    NO_FILE = 'No file yet. The debugger opens a tab when it stops in a file, or drag a text file here from the folder view.'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setTabBar(CodeTabBar())
        self.note = QLabel(self.NO_FILE, self)                      # shown while no tab is open
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setStyleSheet(f'color: {NUMBER}; background: {BACK}; padding: 12px;')
        self.setTabsClosable(True)
        self.setDocumentMode(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self.close_tab)
        self.watcher = QFileSystemWatcher(self)                     # a message from the system when a shown file or its folder changes: no polling
        self.watcher.fileChanged.connect(self.refresh)
        self.watcher.directoryChanged.connect(self.refresh)

    def place_note(self):
        self.note.setGeometry(self.rect().adjusted(0, self.tabBar().height(), 0, 0))
        self.note.setVisible(self.count() == 0)
        self.note.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_note()

    def tabInserted(self, index):
        super().tabInserted(index)
        self.place_note()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self.place_note()

    def showEvent(self, event):
        super().showEvent(event)
        self.place_note()

    # ---- drops: only files Zygote's own folder view drags; Explorer and the desktop are refused with a line in the Log ----------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PATHS_FORMAT) or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        data = event.mimeData()
        if data.hasFormat(PATHS_FORMAT):
            self.pathsDropped.emit(bytes(data.data(PATHS_FORMAT)).decode('utf-8').split('\n'))
        else:
            self.dropRefused.emit('Not opened: only files dragged from the folder view open here (not from Explorer).')
        event.acceptProposedAction()

    def views(self):
        return [self.widget(index) for index in range(self.count())]

    def paths(self):
        return [view.path for view in self.views()]

    def view_of(self, path):
        """The tab of a file: the same path, or the same file reached another way (the debugger prints real paths: a mapped drive can come back as its network name)."""
        same = next((view for view in self.views() if os.path.normcase(view.path) == os.path.normcase(str(path))), None)
        if same is not None:
            return same
        for view in self.views():
            try:
                if os.path.samefile(view.path, str(path)):
                    return view
            except OSError:
                continue
        return None

    def label_tabs(self):
        for index, label in enumerate(tab_names(self.paths())):
            self.setTabText(index, label)
            self.setTabToolTip(index, self.widget(index).path)

    def open_file(self, path, text, breakpoints):
        """The tab of a file (made when it is not open yet); it is shown."""
        view = self.view_of(path)
        if view is None:
            view = CodeView(path, text, breakpoints)
            view.breakpointClicked.connect(lambda line, v=view: self.breakpointToggled.emit(v.path, line))
            self.addTab(view, '')
            self.label_tabs()
            self.watch(view)
        else:
            view.set_breakpoints(breakpoints)
            self.reload_view(view)                                  # a file dragged here again shows what is on disk now
        self.setCurrentWidget(view)
        return view

    # ---- the tabs follow the disk: a file written by anything (VFlow's Save, an export, an editor) shows at once -------------------
    def watch(self, view):
        """Watch the file and its folder (a file replaced by a new one, or deleted and written again, is seen through its folder)."""
        wanted = [view.path, os.path.dirname(view.path)]
        known = set(self.watcher.files()) | set(self.watcher.directories())
        fresh = [one for one in wanted if one not in known and os.path.exists(one)]
        if fresh:
            self.watcher.addPaths(fresh)

    def reload_view(self, view):
        """Read the file again when the disk differs from what the tab shows. True when the text changed."""
        stamp = disk_stamp(view.path)
        if stamp is None:
            return False                                            # gone for now: the tab keeps its text (a rewrite may be on its way)
        if stamp == view.stamp:
            return False
        text = read_source(view.path)
        view.stamp = stamp
        return text is not None and view.reload_text(text)

    def refresh(self, _changed=''):
        """Something watched changed: every tab is checked against the disk, and the watches are made again (a replaced file loses its watch)."""
        for view in self.views():
            self.watch(view)
            if self.reload_view(view):
                self.fileReloaded.emit(view.path)

    def show_stop(self, path, line):
        """The debugger stopped at path:line: that file's tab is shown with the arrow there, and the old arrow is gone."""
        for view in self.views():
            view.set_current(0)
        view = self.view_of(path)
        if view is not None:
            self.setCurrentWidget(view)
            view.set_current(line)
        return view

    def clear_stop(self):
        for view in self.views():
            view.set_current(0)

    def close_all(self):
        while self.count():
            self.close_tab(0)

    def close_paths(self, paths):
        """Close the tab of every file that is one of these paths or lies inside one of them (the file was thrown away or renamed)."""
        gone = [os.path.normcase(os.path.abspath(str(path))) for path in paths]
        closed = []
        for index in reversed(range(self.count())):
            here = os.path.normcase(os.path.abspath(self.widget(index).path))
            if any(here == one or here.startswith(one + os.sep) for one in gone):
                closed.append(self.widget(index).path)
                self.close_tab(index)
        return closed

    def close_tab(self, index):
        gone = self.widget(index).path
        if gone in self.watcher.files():
            self.watcher.removePath(gone)
        self.widget(index).deleteLater()
        self.removeTab(index)
        self.label_tabs()
        if self.count() == 0:
            self.emptied.emit()
