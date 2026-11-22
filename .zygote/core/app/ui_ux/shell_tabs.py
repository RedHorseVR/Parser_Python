"""The pieces of the shell tabs in the bottom panel: the tab bar that paints a shell's colour pair, the page a shell lives on, the box that
renames a tab in place, and the tab widget that holds them. No process is started here: a shell starts only when the window's code calls
`ShellPage.show_view(...)` from a button press (the plus tab, or the Start button of a tab brought back on opening a project)."""
import functools

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget

from functional import core

PLUS = 'plus'                                                      # the tab data of the "+" tab that makes the next shell


class RenameEdit(QLineEdit):
    """The box over a tab's name: Enter or leaving it keeps the new name, Escape cancels."""
    accepted_text = Signal(str)
    cancelled = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.done = False

    def finish(self, keep):
        if self.done:
            return
        self.done = True
        if keep and self.text().strip():
            self.accepted_text.emit(self.text().strip())
        else:
            self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.finish(False)
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finish(True)
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.finish(True)


class ShellTabBar(QTabBar):
    """A tab bar whose shell tabs show their colour pair (background and text chosen together, so the name always reads). A tab's data is the
    index of its colour pair (a whole number), PLUS for the "+" tab, nothing for Log and Console."""
    rename_wanted = Signal(int)                                    # a click on the name of the tab that was already the shown one
    menu_wanted = Signal(int, QPoint)                              # right-click on a shell tab (index, where on screen)
    tear_wanted = Signal(int, QPoint)                              # a shell tab was dragged off the bar (index, where on screen)
    tear_moved = Signal(QPoint)                                    # the torn tab is carried (the mouse is still down)
    tear_dropped = Signal(QPoint)                                  # the mouse was let go: the torn tab is put down here
    TEAR_DISTANCE = 40                                             # pixels outside the bar before a drag counts as tearing the tab away

    def __init__(self):
        super().__init__()
        self.press = None
        self.dragging = None                                       # the shell tab the left button went down on (the one that may be torn away)
        self.tearing = False                                       # a tab is being carried (the mouse is still down)
        self.drop_hint = False                                     # a shell window is over the bar: it will go back in when let go

    def is_shell(self, index):
        data = self.tabData(index)
        return isinstance(data, int) and not isinstance(data, bool)

    def mousePressEvent(self, event):
        index = self.tabAt(event.position().toPoint())
        self.press = index if (event.button() == Qt.LeftButton and index == self.currentIndex() and self.is_shell(index)) else None
        self.dragging = index if (event.button() == Qt.LeftButton and self.is_shell(index)) else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.tearing:
            self.tear_moved.emit(event.globalPosition().toPoint())
            return
        if self.dragging is not None and event.buttons() & Qt.LeftButton:
            position = event.position().toPoint()
            if not self.rect().adjusted(0, -self.TEAR_DISTANCE, 0, self.TEAR_DISTANCE).contains(position):
                index, self.dragging, self.press = self.dragging, None, None
                self.tearing = True
                self.tear_wanted.emit(index, event.globalPosition().toPoint())
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.dragging = None
        if self.tearing:
            self.tearing = False
            self.tear_dropped.emit(event.globalPosition().toPoint())
            return
        index = self.tabAt(event.position().toPoint())
        wanted = self.press is not None and index == self.press
        self.press = None
        super().mouseReleaseEvent(event)
        if wanted:
            self.rename_wanted.emit(index)

    def contextMenuEvent(self, event):
        index = self.tabAt(event.pos())
        if self.is_shell(index):
            self.menu_wanted.emit(index, event.globalPos())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        for index in range(self.count()):
            if not self.is_shell(index):
                continue
            back, text = core.TAB_COLORS[self.tabData(index)]
            rect = self.tabRect(index).adjusted(1, 1, -1, 0)
            painter.fillRect(rect, QColor(back))
            painter.setPen(QColor(text))
            font = painter.font()
            font.setBold(True)                                     # bold everywhere: plain text was hard to read on some colours
            painter.setFont(font)
            painter.drawText(rect.adjusted(8, 0, -24, 0), int(Qt.AlignVCenter | Qt.AlignLeft | Qt.TextSingleLine), self.tabText(index))
            if index == self.currentIndex():
                painter.fillRect(QRect(rect.left(), rect.bottom() - 2, rect.width(), 3), QColor(text))
        if self.drop_hint:                                         # a shell window is over the bar: this is where it goes
            painter.setPen(QPen(QColor('#ffc94d'), 4))
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))
        painter.end()


class ShellPage(QWidget):
    """One shell's page: black like the terminal. Before its shell has started (a tab brought back on opening a project) it shows a Start button."""
    start_wanted = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName('consolepage')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.view = None
        self.look = None                                           # (background, text) of the tab's colour pair
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.start_button = QPushButton('Start shell')
        self.start_button.setToolTip('Start a command prompt in this tab, in the project folder')
        self.start_button.clicked.connect(self.start_wanted)
        self.layout_box.addWidget(self.start_button, 0, Qt.AlignCenter)

    def set_look(self, background, text):
        """The page and its terminal take the tab's colours, so the shell you are in is plain to see."""
        self.look = (background, text)
        self.setStyleSheet(f'#consolepage {{ background: {background}; }}')
        if self.view is not None:
            self.view.set_colors(background, text)

    def show_view(self, view):
        """The terminal takes the page; the Start button goes."""
        self.view = view
        if self.look is not None:
            view.set_colors(*self.look)
        self.start_button.hide()
        self.layout_box.addWidget(view)

    def drop_view(self):
        """The shell could not start: the terminal goes and the Start button is back."""
        self.view.setParent(None)
        self.view.deleteLater()
        self.view = None
        self.start_button.show()

    def is_running(self):
        return self.view is not None and self.view.is_running()


class TabGhost(QLabel):
    """The tab as it is carried while the mouse is down: a small coloured label that follows the pointer."""

    def __init__(self, name, look):
        super().__init__(name, None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setStyleSheet(f'QLabel {{ background: {look[0]}; color: {look[1]}; font-weight: bold; padding: 4px 14px; border: 2px solid #ffffff; }}')
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.adjustSize()

    def carry_to(self, where):
        self.move(where - QPoint(self.width() // 2, self.height() // 2))


class ShellWindow(QWidget):
    """A shell page torn away from the tabs: a window of its own with the same colours. The shell inside keeps running. Dropping the window
    back on the tab bar (let go of the title bar over it) or minimizing it puts the page back among the tabs; closing it ends the shell."""
    dock_wanted = Signal()
    close_wanted = Signal()
    released = Signal(QPoint)                                      # the title bar was let go of (where the cursor is on screen)
    carried = Signal(QPoint)                                       # the window is being moved (where the cursor is on screen)

    def __init__(self, page, name, look):
        super().__init__(None, Qt.Window)
        self.page = page
        self.setWindowTitle(name)
        self.setStyleSheet(f'ShellWindow {{ background: {look[0]}; }}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(page)
        page.show()
        self.resize(760, 420)

    def event(self, event):
        if event.type() == QEvent.NonClientAreaMouseButtonRelease:
            self.released.emit(QCursor.pos())
        elif event.type() == QEvent.WindowStateChange and self.isMinimized():
            self.setWindowState(Qt.WindowNoState)                  # minimizing puts the shell back among the tabs, like dropping it there
            self.dock_wanted.emit()
        return super().event(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.carried.emit(QCursor.pos())

    def closeEvent(self, event):
        event.ignore()                                             # the window goes through the main window: it ends the shell like the tab's X
        self.close_wanted.emit()


class BottomTabs(QTabWidget):
    """Log, Console, the shells, and a "+" tab at the end that makes the next shell."""

    def __init__(self):
        super().__init__()
        self.tab_bar = ShellTabBar()
        self.setTabBar(self.tab_bar)
        self.plus_page = QWidget()
        self.rename_box = None

    def add_plus(self):
        index = self.addTab(self.plus_page, '+')
        self.tab_bar.setTabData(index, PLUS)
        self.setTabToolTip(index, f'New shell: a command prompt in its own tab (up to {core.SHELL_LIMIT})')
        self.tab_bar.setTabButton(index, QTabBar.RightSide, None)

    def shell_pages(self):
        return [self.widget(at) for at in range(self.count()) if isinstance(self.widget(at), ShellPage)]

    def add_shell_page(self, page, name, color, close_button):
        """Put a shell page before the "+" tab, in its colour pair, with its close button."""
        index = self.insertTab(self.indexOf(self.plus_page), page, name)
        self.set_color(page, color)
        self.tab_bar.setTabButton(index, QTabBar.RightSide, close_button)
        return index

    def set_color(self, page, color):
        index = self.indexOf(page)
        self.tab_bar.setTabData(index, color)
        page.set_look(*core.TAB_COLORS[color])
        button = self.tab_bar.tabButton(index, QTabBar.RightSide)
        if button is not None:
            button.setStyleSheet(f'QToolButton {{ color: {core.TAB_COLORS[color][1]}; background: transparent; border: none; font-weight: bold; }}')
        self.tab_bar.update()

    def take_shell_page(self, page):
        """Take a shell page out of the tabs without ending it (it goes to a window of its own). Returns (name, colour)."""
        index = self.indexOf(page)
        name, color = self.tabText(index), self.tab_bar.tabData(index)
        self.removeTab(index)
        return name, color

    def remove_shell_page(self, page):
        self.removeTab(self.indexOf(page))
        page.deleteLater()

    def rename_in_place(self, index):
        """A box over the tab's name. Enter keeps the new name, Escape cancels."""
        self.cancel_rename()
        box = RenameEdit(self.tab_bar)
        box.setText(self.tabText(index))
        box.setGeometry(self.tab_bar.tabRect(index).adjusted(2, 2, -26, -2))
        box.accepted_text.connect(functools.partial(self.set_name, self.widget(index)))
        box.accepted_text.connect(box.deleteLater)
        box.cancelled.connect(box.deleteLater)
        box.selectAll()
        box.show()
        box.setFocus()
        self.rename_box = box

    def cancel_rename(self):
        if self.rename_box is not None:
            try:
                self.rename_box.finish(False)
            except RuntimeError:
                pass                                               # the box was already gone
            self.rename_box = None

    def set_name(self, page, text):
        index = self.indexOf(page)
        if index >= 0:
            self.setTabText(index, text)
            self.tab_bar.update()


def close_button():
    """The small X of a shell tab (its look comes with the tab's colours)."""
    button = QToolButton()
    button.setText('✕')
    button.setAutoRaise(True)
    button.setToolTip('Close this shell tab (asks first when a shell is still running in it)')
    button.setCursor(Qt.ArrowCursor)
    return button
