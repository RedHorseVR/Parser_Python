"""The three small buttons over the folder view: a folder (shows it in the file manager) and a small picture of a console window each for the two command lines.
Left-click opens the window in the folder shown; right-click opens it as administrator."""
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton

LOOKS = {'cmd': ('#0c0c0c', '#cccccc', '>_'), 'powershell': ('#012456', '#ffffff', 'PS>')}


class CliIcon:
    @classmethod
    def make(cls, kind):
        background, text, prompt = LOOKS[kind]
        pixmap = QPixmap(48, 36)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor('#808080'))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(QRect(1, 1, 46, 34), 3, 3)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#d0d0d0'))
        painter.drawRect(QRect(2, 2, 44, 6))                         # the title bar of the little window
        painter.setPen(QColor(text))
        font = QFont('Consolas')
        font.setBold(True)
        font.setPixelSize(15)
        painter.setFont(font)
        painter.drawText(QRect(4, 10, 40, 24), Qt.AlignLeft | Qt.AlignVCenter, prompt)
        painter.end()
        return QIcon(pixmap)


class FolderIcon:
    @classmethod
    def make(cls):
        pixmap = QPixmap(48, 36)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor('#a88a1e'))
        painter.setBrush(QColor('#e8c547'))
        painter.drawRoundedRect(QRect(4, 6, 18, 8), 3, 3)             # the tab
        painter.drawRoundedRect(QRect(4, 10, 40, 22), 3, 3)           # the folder
        painter.end()
        return QIcon(pixmap)


class FolderButton(QPushButton):
    """A small folder: shows the folder in view in the system's file manager."""

    def __init__(self, tip):
        super().__init__()
        self.setIcon(FolderIcon.make())
        self.setIconSize(QSize(32, 24))
        self.setFixedSize(46, 30)
        self.setToolTip(tip)


class CliButton(QPushButton):
    admin_requested = Signal()

    def __init__(self, kind, tip):
        super().__init__()
        self.kind = kind
        self.setIcon(CliIcon.make(kind))
        self.setIconSize(QSize(32, 24))
        self.setFixedSize(46, 30)
        self.setToolTip(tip)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.admin_requested.emit()
            event.accept()
        else:
            super().mousePressEvent(event)
