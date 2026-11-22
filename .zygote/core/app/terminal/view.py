"""The terminal contract. An adapter (one module per terminal package) subclasses `TerminalView` and fills in the methods.

    start(command, cwd)   run the command (a list of words) in the terminal, in the folder cwd; one program per call
    send_text(text)       type text into the running program (as if typed; the caller adds the Enter)
    stop(force=False)     end the running program (a second call forces it; force=True forces at once)
    clear_view()          empty what is shown; never touches any saved log
    screen_text()         the text on the screen now (what a person would read): lets a search, a test or later an MCP tool read it
    is_running()          True while the program lives
    is_busy()             True while a program runs INSIDE the shell (False: idle at its prompt). When it cannot be told: True.
    set_colors(back, text)  show the screen in these two '#rrggbb' colours (optional: a terminal that cannot do it keeps its own)

Signals: `started()` after the program began; `finished(int)` with its exit code (-1 when the code is unknown) after it ended;
`output(str)` with what the program printed (every chunk, in the window's thread): the debugger reads where the program stopped from it."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class TerminalView(QWidget):
    started = Signal()
    finished = Signal(int)
    output = Signal(str)

    def start(self, command, cwd):
        raise NotImplementedError('a terminal adapter must define start')

    def send_text(self, text):
        raise NotImplementedError('a terminal adapter must define send_text')

    def stop(self, force=False):
        raise NotImplementedError('a terminal adapter must define stop')

    def clear_view(self):
        raise NotImplementedError('a terminal adapter must define clear_view')

    def screen_text(self):
        raise NotImplementedError('a terminal adapter must define screen_text')

    def is_running(self):
        raise NotImplementedError('a terminal adapter must define is_running')

    def is_busy(self):
        return self.is_running()

    def set_colors(self, background, text):
        pass

    def refit(self):
        pass
