"""A toast: a small message that appears over the window, stays about two seconds and goes away by itself. It takes no click and no focus.

DOCTRINE Part 4, written exception (Z 2.14.9): the one-shot timer that closes it. It starts and stops nothing but the message itself."""
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel


class Toast(QLabel):
    SECONDS = 3.5          # the one time every toast stays (a result must be readable)
    WARNING_SECONDS = 5.0  # the red toast (something the person must act on) stays longer
    MARGIN = 24            # free space kept at both sides of the window
    MINIMUM_HELD = 1.0     # a held toast (Updating) is seen at least this long before the next toast replaces it

    def __init__(self, window, text, hold=False, warning=False):
        """hold = True: it stays until closed (the "Updating" toast of a ZIP drop: the next toast, or the end of the work, replaces it). The one-shot timer is the only timer."""
        super().__init__(text, window)
        self.closed = False
        self.held = hold
        self.born = time.monotonic()
        self.setObjectName('toast')                                  # its look is in ui_ux\theme.py
        self.setProperty('kind', 'warning' if warning else 'plain')  # the red kind: the theme's error colour
        self.seconds = self.WARNING_SECONDS if warning else self.SECONDS
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)                                       # a long text wraps; the toast never grows wider than the window
        self.setMaximumWidth(max(60, window.width() - self.MARGIN))
        self.adjustSize()
        if self.width() > self.maximumWidth():
            self.resize(self.maximumWidth(), self.heightForWidth(self.maximumWidth()))
        elif self.sizeHint().width() > self.maximumWidth():
            self.resize(self.maximumWidth(), self.heightForWidth(self.maximumWidth()))
        self.move((window.width() - self.width()) // 2, (window.height() - self.height()) // 2)      # the middle of the window: the version line stays readable
        self.show()
        self.raise_()
        if hold:
            return
        self.timer = QTimer(self)                                    # owned by the toast: it goes with the window, never fires into a deleted object
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.close_toast)
        self.timer.start(int(self.seconds * 1000))

    def seen_for(self):
        """Seconds since it appeared."""
        return time.monotonic() - self.born

    def timer_started(self):
        """True for a toast that closes by itself (the end toast), False for one that is held."""
        return hasattr(self, 'timer')

    def close_toast(self):
        if self.closed:
            return
        self.closed = True
        self.hide()
        self.deleteLater()
