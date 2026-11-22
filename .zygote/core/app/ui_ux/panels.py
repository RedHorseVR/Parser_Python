"""A panel with a title bar across its top: the name of what the panel shows. The bar is styled by the theme (#panelheader).
Widgets can be centered in the bar (the sort and view lists over the icon view)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class PictureButton(QLabel):
    """A picture that acts as a button: a left click emits `clicked`. (It looks like a picture, so its tooltip says what it does.)
    With accept_files(), files dropped on it (from Zygote's own folder view or from Explorer) are sent in `filesDropped`, and a dotted line round the
    picture says it takes drops."""
    clicked = Signal()
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.takes_files = False
        self.edge = 0                                              # the width at the right that is only margin (the dotted line stays round the picture)

    def accept_files(self, edge=0):
        self.takes_files = True
        self.edge = edge
        self.setAcceptDrops(True)

    @staticmethod
    def dropped_paths(data):
        """The local files of a drag, from Zygote's own views (their own list) or from Explorer (file links)."""
        from ui_ux.lazy_model import PATHS_FORMAT
        if data.hasFormat(PATHS_FORMAT):
            return [path for path in bytes(data.data(PATHS_FORMAT)).decode('utf-8').split('\n') if path]
        return [url.toLocalFile() for url in data.urls() if url.isLocalFile()] if data.hasUrls() else []

    def dragEnterEvent(self, event):
        if self.takes_files and self.dropped_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self.dropped_paths(event.mimeData()) if self.takes_files else []
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
        else:
            event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.takes_files and self.pixmap() is not None and not self.pixmap().isNull():
            from PySide6.QtGui import QColor, QPainter, QPen
            from ui_ux.theme import Theme
            painter = QPainter(self)
            pen = QPen(QColor(Theme.colors()['frame']), 2, Qt.DotLine)
            painter.setPen(pen)
            painter.drawRoundedRect(1, 1, max(self.width() - self.edge - 2, 4), self.height() - 2, 10, 10)
            painter.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class TitledPanel(QWidget):
    def __init__(self, title, body):
        super().__init__()
        self.title = QLabel(title)
        self.title.setObjectName('paneltitle')
        self.header = QWidget()
        self.header.setObjectName('panelheader')
        self.row = QHBoxLayout(self.header)
        self.row.setContentsMargins(0, 0, 6, 0)
        self.row.addWidget(self.title)
        self.row.addStretch(1)
        self.row.addStretch(1)
        self.body = body
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(body, 1)

    def set_title_widget(self, widget):
        """Put another widget (the clickable path) where the title label was; it takes the free room of the bar."""
        self.row.replaceWidget(self.title, widget)
        self.title.hide()
        self.title = widget
        self.row.setStretchFactor(widget, 100)

    def add_left_widget(self, widget):
        """Place a widget at the left end of the bar, before the title."""
        self.row.insertWidget(0, widget)

    def add_right_widget(self, widget):
        """Place a widget at the right end of the bar."""
        self.row.addWidget(widget)

    def add_center_widget(self, widget):
        """Place a widget in the middle of the bar, after the ones already there."""
        self.row.insertWidget(self.row.count() - 1, widget)
