"""Ctrl + mouse wheel zoom for a panel. One class does it; each kind of panel only says what else grows with the text.

Each panel has its own filter, so zooming one panel never zooms another."""
from PySide6.QtCore import QEvent, QObject, QSize, Qt


class ZoomFilter(QObject):
    SMALLEST = 6
    LARGEST = 40

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        view.viewport().installEventFilter(self)
        self.resized(self.current_size())                     # the first look follows the text size too

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            self.step(1 if event.angleDelta().y() > 0 else -1)
            return True                                       # the wheel zoomed; it does not also scroll
        return False

    def current_size(self):
        size = self.view.font().pointSizeF()
        return size if size > 0 else 9.0

    def step(self, direction):
        self.set_size(self.current_size() + direction)

    def set_size(self, size):
        """Put the panel at this text size (kept between the smallest and the largest); what follows the text follows."""
        font = self.view.font()
        size = min(self.LARGEST, max(self.SMALLEST, float(size)))
        font.setPointSizeF(size)
        self.view.setFont(font)
        self.resized(size)

    def resized(self, size):
        """What else follows the text size. Nothing, by default."""


class TreeZoomFilter(ZoomFilter):
    def resized(self, size):
        icon = int(size * 1.7)
        self.view.setIconSize(QSize(icon, icon))


class IconZoomFilter(ZoomFilter):
    def resized(self, size):
        icon = int(size * 4)                                  # big enough to match the text
        self.view.setIconSize(QSize(icon, icon))
        self.view.setGridSize(QSize(max(icon + 24, int(size * 8.5)), icon + int(size * 3.4)))   # snug: the icon, then the name
        self.view.setSpacing(2)
