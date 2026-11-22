"""Commit runs in a process of its own, apart from the Console: the program under test keeps running while TortoiseGit commits (Stop is never asked).
One QProcess per press, no window, the output in the Log, and the end of the process is a Qt signal (no timer, no polling). Its input is closed at once, so a
`pause` in the batch file (a failure it wants the person to read) returns instead of waiting for a key nobody can press: the lines it printed are in the Log."""
from PySide6.QtCore import QObject, QProcess, Signal


class CommitRunner(QObject):
    line = Signal(str)                                              # one line of the program's output
    finished = Signal(int)                                          # the exit code (-1 when it could not start or crashed)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_failed)
        self.rest = ''

    def is_running(self):
        return self.process.state() != QProcess.NotRunning

    def start(self, command, folder):
        """Start one program in folder. False (and nothing started) while the last one still runs."""
        if self.is_running():
            return False
        self.rest = ''
        self.process.setWorkingDirectory(str(folder))
        self.process.start(str(command[0]), [str(word) for word in command[1:]])
        self.process.closeWriteChannel()
        return True

    def read_output(self):
        self.rest += bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        *lines, self.rest = self.rest.replace('\r\n', '\n').split('\n')
        for text in lines:
            if text.strip():
                self.line.emit(text)

    def process_finished(self, code, status):
        self.read_output()
        if self.rest.strip():
            self.line.emit(self.rest)
        self.rest = ''
        self.finished.emit(code if status == QProcess.NormalExit else -1)

    def process_failed(self, error):
        if error == QProcess.FailedToStart:
            self.finished.emit(-1)
