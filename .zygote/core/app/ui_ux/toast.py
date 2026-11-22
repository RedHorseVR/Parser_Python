"""A toast: a small message that appears over the window, stays about two seconds and goes away by itself. It takes no click and no focus.

DOCTRINE Part 4, written exception (Z 2.14.9): the one-shot timer that closes it. It starts and stops nothing but the message itself."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel


class Toast(QLabel):
    SECONDS = 2.0

    def __init__(self, window, text):
        super().__init__(text, window)
        self.setObjectName('toast')                                  # its look is in ui_ux\theme.py, one rule
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignCenter)
        self.adjustSize()
        self.move((window.width() - self.width()) // 2, (window.height() - self.height()) // 2)      # the middle of the window: the version line stays readable
        self.show()
        self.raise_()
        self.timer = QTimer(self)                                    # owned by the toast: it goes with the window, never fires into a deleted object
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.close_toast)
        self.timer.start(int(self.SECONDS * 1000))

    def close_toast(self):
        self.hide()
        self.deleteLater()
