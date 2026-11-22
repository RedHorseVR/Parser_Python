"""The picture drop target of the AI panel's test area: drop a picture file on it, paste one (Ctrl+V or right-click > Paste picture), or use the
sample picture it starts with. It only holds the picture; the panel sends it when the chosen model can see."""
import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLabel, QMenu

IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')
LONGEST_SIDE = 1568                                       # bigger pictures are scaled down before they are sent (models do not use more)


def sample_image():
    """A small made-up picture: a box, an arrow and a stick figure, with a word. Something simple to ask "what is this?" about."""
    image = QImage(320, 240, QImage.Format_ARGB32)
    image.fill(QColor('#ffffff'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor('#1f3f8f'), 4))
    painter.drawRect(QRectF(30, 40, 90, 60))
    painter.drawLine(QPointF(120, 70), QPointF(190, 70))
    painter.drawLine(QPointF(190, 70), QPointF(175, 58))
    painter.drawLine(QPointF(190, 70), QPointF(175, 82))
    painter.setPen(QPen(QColor('#a02020'), 4))
    painter.drawEllipse(QPointF(250, 60), 18, 18)
    painter.drawLine(QPointF(250, 78), QPointF(250, 140))
    painter.drawLine(QPointF(250, 95), QPointF(222, 118))
    painter.drawLine(QPointF(250, 95), QPointF(278, 118))
    painter.drawLine(QPointF(250, 140), QPointF(228, 190))
    painter.drawLine(QPointF(250, 140), QPointF(272, 190))
    painter.setPen(QColor('#222222'))
    painter.drawText(QRectF(30, 40, 90, 60), int(Qt.AlignCenter), 'input')
    painter.drawText(QRectF(30, 200, 260, 24), int(Qt.AlignLeft), 'sample picture')
    painter.end()
    return image


class ImageDrop(QLabel):
    """Shows the picture; a grey frame says the chosen model cannot use it (the picture stays, and is still there for the next vision model)."""

    def __init__(self):
        super().__init__()
        self.image = None
        self.setFixedSize(230, 170)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.active = True
        self.set_image(sample_image())
        self.show_frame()

    def set_image(self, image):
        self.image = image
        self.setPixmap(self.pixmap_for(image))

    def pixmap_for(self, image):
        from PySide6.QtGui import QPixmap
        return QPixmap.fromImage(image).scaled(self.width() - 8, self.height() - 8, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def set_active(self, active):
        self.active = active
        self.show_frame()
        self.setToolTip('Drop a picture here, or paste one (Ctrl+V). It is sent with the question to a model that can see.' if active else
                        'The chosen model cannot see pictures: the picture stays here for the next vision model.')

    def show_frame(self):
        color = '#7ccf7c' if self.active else '#555555'
        self.setStyleSheet(f'QLabel {{ border: 2px dashed {color}; background: #262626; }}')

    def png_base64(self):
        """The picture as base64 PNG (what Ollama takes in `images`), scaled down when very large. None when there is no picture."""
        if self.image is None:
            return None
        image = self.image
        if max(image.width(), image.height()) > LONGEST_SIDE:
            image = image.scaled(LONGEST_SIDE, LONGEST_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, 'PNG')
        return base64.b64encode(bytes(data)).decode('ascii')

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasImage() or any(url.toLocalFile().lower().endswith(IMAGE_SUFFIXES) for url in mime.urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        mime = event.mimeData()
        for url in mime.urls():
            image = QImage(url.toLocalFile())
            if not image.isNull():
                self.set_image(image)
                event.acceptProposedAction()
                return
        if mime.hasImage():
            self.set_image(QImage(mime.imageData()))
            event.acceptProposedAction()

    def paste(self):
        image = QApplication.clipboard().image()
        if not image.isNull():
            self.set_image(image)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_V and event.modifiers() & Qt.ControlModifier:
            self.paste()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('Paste picture').setData('paste')
        menu.addAction('Use the sample picture').setData('sample')
        chosen = menu.exec(event.globalPos())
        if chosen is not None and chosen.data() == 'paste':
            self.paste()
        elif chosen is not None:
            self.set_image(sample_image())
