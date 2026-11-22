"""Adapter: the `termqt` terminal widget (a Qt terminal emulator in Python) behind the TerminalView contract.
termqt draws the screen and turns keys into terminal input; the program side is OUR `pty_io` (termqt's own Windows process layer
uses the older winpty backend and has no working folder, so it is not used)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QScrollBar

from functional.core import ZygoteError
from terminal.pty_io import make_pty
from terminal.view import TerminalView


def make_screen_class():
    """termqt's Terminal with one repair: after the window is dragged taller, the screen is taller than the lines termqt holds, and a
    program's "erase the screen" (IPython sends it at every prompt) then indexes lines that do not exist (IndexError, mutex left locked).
    Before every chunk of program output the buffer is topped up with blank lines to cover the whole screen and the cursor is kept on it."""
    from termqt import Terminal

    class Screen(Terminal):
        theme = None                                                       # (background, text) colours, or None = termqt's own
        reports_left = 0                                                   # cursor-position answers the shell may still get (see report_cursor_pos)
        dropped_reports = 0

        def report_cursor_pos(self):
            """The shell's console host asks "where is the cursor?" when it starts. termqt answers every time, and an answer to a question that
            was not waiting arrives in the shell as typed text (the stray characters after clicking into, or moving, a shell tab). Only the
            first few questions after a start are answered; the rest are counted and dropped."""
            if self.reports_left > 0:
                self.reports_left -= 1
                super().report_cursor_pos()
            else:
                self.dropped_reports += 1

        def refit(self):
            """After the screen moved (a tab shown, a window docked): take the size it has now and draw all of it again."""
            self.resize(self.width(), self.height())
            self._paint_buffer()
            self.update()

        def cover_screen(self):
            self._buffer_lock.lock()
            need = self._buffer_display_offset + self.col_len
            while len(self._buffer) < need:
                self._buffer.append([None for _ in range(self.row_len)])
                self._line_wrapped_flags.append(False)
            self._buffer_lock.unlock()

        def clear_all(self):
            """Clear: an empty screen and no scroll-back, drawn at once (termqt's own clear_buffer neither redraws nor resets the scroll position)."""
            self._buffer_lock.lock()
            self.clear_buffer()
            self._buffer_display_offset = 0
            self.update_scroll_position()
            self._buffer_lock.unlock()
            self.set_cursor_position(0, 0)
            self._paint_buffer()
            self.update()

        def set_theme(self, background, text):
            """Show the screen in a colour pair. termqt paints white on black; at display time grey levels are mapped between the pair (black
            -> background, white -> text, anti-aliasing in between), so cursor, selection and old text follow too."""
            self.theme = (QColor(background), QColor(text))
            palette = self.palette()
            palette.setColor(QPalette.Window, self.theme[0])
            self.setPalette(palette)
            self.update()

        def themed_canvas(self):
            back, text = self.theme
            image = self._canvas.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
            dark = QImage(image)
            dark.invertPixels()                                            # 1 - level: how much of the background shows
            for picture, color in ((image, text), (dark, back)):
                painter = QPainter(picture)
                painter.setCompositionMode(QPainter.CompositionMode_Multiply)
                painter.fillRect(picture.rect(), color)
                painter.end()
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode_Plus)
            painter.drawImage(0, 0, dark)
            painter.end()
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(self._canvas.devicePixelRatio())
            return pixmap

        def paintEvent(self, event):
            if self.theme is None:
                super().paintEvent(event)
                return
            self._painter_lock.lock()
            painter = QPainter(self)
            painter.drawPixmap(int(self._padding / 2), int(self._padding / 2), self.themed_canvas())
            painter.end()
            self._painter_lock.unlock()

        def begin_below_text(self, gap=1):
            """A new program starts under what is printed: the cursor goes to the first column, `gap` blank lines below the last line that has
            text, whatever the window did in between (stop, resize). Without this the cursor stayed where the old program left it."""
            self.cover_screen()
            last = -1
            for at, row in enumerate(self._buffer):
                if any(cell is not None and cell.char.strip() for cell in row):
                    last = at
            self.set_cursor_position(0, last + 1 + gap if last >= 0 else 0)
            self._paint_buffer()
            self.update()

        FONT_SIZES = (6, 40)

        def zoom(self, steps):
            """Ctrl + wheel: the text gets bigger or smaller (the number of rows and columns follows the window)."""
            size = min(max(self.font_size + steps, self.FONT_SIZES[0]), self.FONT_SIZES[1])
            if size == self.font_size:
                return
            self.font_size = size
            self.set_font()
            self.resize(self.width(), self.height())
            self._paint_buffer()
            self.update()

        def wheelEvent(self, event):
            if event.modifiers() & Qt.ControlModifier:
                self.zoom(1 if event.angleDelta().y() > 0 else -1)
                event.accept()
                return
            super().wheelEvent(event)

        def _map_pixel_to_cell(self, pos):
            """termqt can map a mouse position to a cell that is not on the screen (dragging a selection past the last line or column) and then
            indexes it (IndexError). The cell is kept on the screen."""
            cell = super()._map_pixel_to_cell(pos)
            row = min(max(cell.y, 0), len(self._buffer) - 1)
            return type(cell)(min(max(cell.x, 0), self.row_len - 1), row)

        def _stdout(self, string):
            self.cover_screen()
            super()._stdout(string)

    return Screen


class View(TerminalView):
    _ended = Signal(int)                                            # the read thread reports here; Qt delivers it in the window's thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self.screen = make_screen_class()(200, 80, font_size=11)
        self.screen.stdin_callback = self.to_program
        self.setFocusProxy(self.screen)                              # focusing the view (the window does) puts the cursor in the shell
        self.screen.resize_callback = self.resized
        self.scroll_bar = QScrollBar(Qt.Vertical)                   # termqt keeps it in step with the screen (scroll-back, wheel, drag)
        self.screen.connect_scroll_bar(self.scroll_bar)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.screen, 1)
        layout.addWidget(self.scroll_bar)
        self.io = None
        self._ended.connect(self.program_ended)

    def size(self):
        """(rows, columns) the screen shows now. termqt calls the length of a row `row_len` (= columns) and of a column `col_len` (= rows)."""
        return max(self.screen.col_len, 1), max(self.screen.row_len, 1)

    def start(self, command, cwd):
        if self.is_running():
            raise ZygoteError('A program is already running in the console. Stop it first.')
        rows, cols = self.size()
        io = make_pty(command, cwd, rows, cols)
        io.stdout_callback = self.got_output
        io.terminated_callback = self._ended.emit
        self.screen.reports_left = 2
        self.screen.begin_below_text()                               # what the earlier runs printed stays (scroll back, or press Clear); a blank line sets this run apart
        io.spawn()                                                   # raises, loudly, when the program cannot start
        self.io = io
        self.screen.setFocus()
        self.started.emit()

    def got_output(self, data):
        """From the read thread: draw it, and tell whoever listens (the signal reaches them in the window's thread)."""
        self.screen.stdout(data)
        self.output.emit(data.decode('utf-8', 'replace') if isinstance(data, bytes) else data)

    def to_program(self, data):
        if self.io is not None:
            self.io.write(data)

    def resized(self, rows, cols):
        if self.io is not None and self.io.is_alive():              # an ended program has no screen size to tell (its pty is closed)
            self.io.resize(rows, cols)

    def send_text(self, text):
        self.to_program(text.encode('utf-8'))

    def stop(self, force=False):
        if self.io is not None and self.io.is_alive():
            self.io.terminate(force)

    def program_ended(self, code):
        self.finished.emit(code)

    def is_running(self):
        return self.io is not None and self.io.is_alive()

    def is_busy(self):
        """A program of its own runs in the shell (it is asked about before the tab closes). When that cannot be told, it counts as busy."""
        if not self.is_running():
            return False
        try:
            return self.io.has_children()
        except (ZygoteError, AttributeError, OSError):
            return True

    def refit(self):
        self.screen.refit()

    def set_colors(self, background, text):
        self.screen.set_theme(background, text)

    def clear_view(self):
        self.screen.clear_all()

    def screen_text(self):
        """The text of the screen, one line per row, trailing blanks cut. Reads termqt's buffer (this adapter is the only place that knows it)."""
        lines = []
        for row in list(self.screen._buffer):
            lines.append(''.join((cell.char if cell is not None else ' ') for cell in row).rstrip())
        while lines and not lines[-1]:
            lines.pop()
        return '\n'.join(lines)
