"""The LED-strip meters of the AI panel: a horizontal bar made of segments in colours (one colour per loaded model), and a small vertical
load meter. They only draw what they are given; nothing here reads the computer."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

OFF = QColor('#2a2a2a')
OTHER = '#7a7a7a'                                           # memory used by something that is not a model of the panel


class SegmentBar(QWidget):
    """parts: [(amount, '#rrggbb'), …] in order, drawn as segments out of `total`; the text is written over the strip."""
    SEGMENTS = 60

    def __init__(self):
        super().__init__()
        self.parts, self.total, self.text = [], 0, ''
        self.setMinimumHeight(22)
        self.setMinimumWidth(200)

    def set_parts(self, parts, total, text):
        self.parts, self.total, self.text = list(parts), total, text
        self.update()

    def segment_colors(self):
        """One colour (or None = off) per segment, from the parts, so that the lit segments add up to the used share."""
        colors = [None] * self.SEGMENTS
        if not self.total:
            return colors
        at, used = 0, 0
        for amount, color in self.parts:
            used += amount
            end = min(self.SEGMENTS, round(used / self.total * self.SEGMENTS))
            for number in range(at, end):
                colors[number] = color
            at = max(at, end)
        return colors

    def paintEvent(self, event):
        painter = QPainter(self)
        width = self.width() / self.SEGMENTS
        for number, color in enumerate(self.segment_colors()):
            painter.fillRect(QRectF(number * width + 1, 1, max(width - 2, 1), self.height() - 2), QColor(color) if color else OFF)
        painter.setPen(QColor('#000000'))
        for shift in (-1, 1):                               # a dark edge so the white text reads on any segment colour
            painter.drawText(QRectF(shift, 0, self.width(), self.height()), int(Qt.AlignCenter), self.text)
            painter.drawText(QRectF(0, shift, self.width(), self.height()), int(Qt.AlignCenter), self.text)
        painter.setPen(QColor('#ffffff'))
        painter.drawText(QRectF(0, 0, self.width(), self.height()), int(Qt.AlignCenter), self.text)
        painter.end()


class LoadMeter(QWidget):
    """A vertical strip: percent 0..100 (None = not known, shown as ?), with its name underneath."""
    SEGMENTS = 20

    def __init__(self, name):
        super().__init__()
        self.name, self.percent = name, None
        self.setMinimumSize(34, 60)

    def set_percent(self, percent):
        self.percent = percent
        self.update()

    @staticmethod
    def color_for(number, total):
        share = number / total
        return QColor('#2e9e44') if share < 0.6 else (QColor('#e0a800') if share < 0.85 else QColor('#d03a2f'))

    def paintEvent(self, event):
        painter = QPainter(self)
        label = 14 * 2
        height = (self.height() - label) / self.SEGMENTS
        lit = 0 if self.percent is None else round(self.percent / 100 * self.SEGMENTS)
        for number in range(self.SEGMENTS):
            top = (self.SEGMENTS - 1 - number) * height
            painter.fillRect(QRectF(4, top + 1, self.width() - 8, max(height - 2, 1)),
                             self.color_for(number, self.SEGMENTS) if number < lit else OFF)
        painter.setPen(QColor('#dddddd'))
        painter.drawText(QRectF(0, self.height() - label, self.width(), 14), int(Qt.AlignCenter), self.name)
        painter.drawText(QRectF(0, self.height() - 14, self.width(), 14), int(Qt.AlignCenter), '?' if self.percent is None else f'{self.percent}%')
        painter.end()
