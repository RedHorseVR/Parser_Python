"""One Zygote window per project, and one bare Zygote. Starting a second one only brings the first to the front.
The way it is told is a message: every window listens on a local socket named after its project (QLocalServer: a named pipe on Windows, a socket on Linux),
and a second start connects, says "raise" and ends. No file, no process, no title-bar search. The socket belongs to the window: it is gone when the window is."""
import os

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from functional import instance_name
from functional.instance_name import BARE
CONNECT_MS = 400


def allow_foreground():
    """Windows lets only the program the person just clicked put a window in front: the second start passes that right on to the first."""
    if os.name != 'nt':
        return
    import ctypes
    ctypes.windll.user32.AllowSetForegroundWindow(-1)


def bring_to_front(window):
    """Show a window again (also when minimized) and put it in front."""
    if window.isMinimized():
        window.showNormal()
    window.show()
    window.raise_()
    window.activateWindow()
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.SetForegroundWindow(int(window.winId()))


FLASH_MS = 350


def flash(window):
    """One quick flash of the window (it dims and comes back) and a blink of its taskbar button: "I am here". The animation belongs to the window and ends by itself."""
    from PySide6.QtWidgets import QApplication
    animation = QPropertyAnimation(window, b'windowOpacity', window)
    animation.setDuration(FLASH_MS)
    animation.setKeyValueAt(0.0, 1.0)
    animation.setKeyValueAt(0.4, 0.45)
    animation.setKeyValueAt(1.0, 1.0)
    animation.setEasingCurve(QEasingCurve.InOutQuad)
    animation.start(QPropertyAnimation.DeleteWhenStopped)
    QApplication.alert(window, 1500)
    return animation


class InstanceGuard(QObject):
    """The one listener of a project (or of the bare Zygote)."""
    raised = Signal()                                              # a second start asked this window to come forward
    ai_requested = Signal()                                        # a program of the project (ai.interface.set_model) asked for the AI panel

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.name = self.name_for(key)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.connection)

    @staticmethod
    def name_for(key):
        """The socket name of a project folder (any spelling of the same folder gives the same name) or of the bare Zygote."""
        return instance_name.name_for(key)

    @staticmethod
    def is_running(key):
        """True when a window holds this project. Nothing is sent: the window is not asked to do anything."""
        socket = QLocalSocket()
        socket.connectToServer(InstanceGuard.name_for(key))
        found = socket.waitForConnected(CONNECT_MS)
        if found:
            socket.disconnectFromServer()
        return found

    @staticmethod
    def ask_running(key):
        """True when a window already holds this project: it was told to come forward. False: nobody does."""
        socket = QLocalSocket()
        socket.connectToServer(InstanceGuard.name_for(key))
        if not socket.waitForConnected(CONNECT_MS):
            return False
        allow_foreground()
        socket.write(b'raise\n')
        socket.waitForBytesWritten(CONNECT_MS)
        socket.disconnectFromServer()
        return True

    def claim(self):
        """Listen under the name. A leftover name that nobody answers (a crash on Linux) is removed first. False when it could not be taken."""
        if self.server.listen(self.name):
            return True
        QLocalServer.removeServer(self.name)
        return self.server.listen(self.name)

    def release(self):
        self.server.close()

    def connection(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.waitForReadyRead(CONNECT_MS)
            message = bytes(socket.readAll()).strip()
            socket.disconnectFromServer()
            socket.deleteLater()
            if message == b'ai':
                self.ai_requested.emit()
            else:
                self.raised.emit()
