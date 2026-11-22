"""Reads the Git state of the project (functional.git_marks) on one background thread, so the window never waits on the disk. One reading at a time: a new
ask while one runs is remembered and done after it. It starts only when the window asks (opening or reloading a project, the end of a commit): no timer,
no watching, no process."""
import threading

from PySide6.QtCore import QObject, Signal

from functional import git_marks


class MarksScout(QObject):
    ready = Signal(object)                                     # (project text, {path: 'ok' | 'bad'}) or (project text, None) when the index could not be read
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lock = threading.Lock()
        self.running = False
        self.again = None

    def ask(self, project):
        """Read the project's state now, or right after the reading that is running."""
        with self.lock:
            if self.running:
                self.again = project
                return
            self.running = True
        threading.Thread(target=self.work, args=(project,), daemon=True).start()

    def work(self, project):
        while project is not None:
            try:
                answer = (str(project), git_marks.states(project))
            except (OSError, ValueError) as error:
                self.failed.emit(f'The Git marks could not be read: {error}')
                answer = (str(project), None)
            self.ready.emit(answer)
            with self.lock:
                project, self.again = self.again, None
                if project is None:
                    self.running = False
