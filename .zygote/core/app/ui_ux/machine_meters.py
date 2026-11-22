"""The computer's meters as one piece: CPU memory bar, GPU memory bar, and the GPU and CPU load meters. Starts reading only while it is shown (one
timer, library calls only). The AI panel has its own copy of this wiring because it also colours the GPU bar per loaded model; folding the two
into this one is pinned."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ai import gpu, system
from functional import core
from ui_ux.meters import OTHER, LoadMeter, SegmentBar

TICK_MS = 1000


class MachineMeters(QWidget):
    def __init__(self, parent=None, top=None):
        """top: an optional widget (such as the model box) shown above the bars, inside the same column."""
        super().__init__(parent)
        self.cpu = system.CpuMeter()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        bars = QVBoxLayout()
        if top is not None:
            bars.addWidget(top)
        self.cpu_label = QLabel('CPU memory')
        self.cpu_bar = SegmentBar()
        self.gpu_names = QLabel()
        self.memory = SegmentBar()
        for widget in (self.cpu_label, self.cpu_bar, self.gpu_names, self.memory):
            bars.addWidget(widget)
        row.addLayout(bars, 1)
        self.gpu_meter = LoadMeter('GPU')
        self.cpu_meter = LoadMeter('CPU')
        row.addWidget(self.gpu_meter)
        row.addWidget(self.cpu_meter)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)     # taller windows give the height to the text areas, never to the meters
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)

    def showEvent(self, event):
        super().showEvent(event)
        self.cpu.before = None
        self.timer.start()
        self.tick()

    def hideEvent(self, event):
        super().hideEvent(event)
        if not event.spontaneous():
            self.timer.stop()

    def tick(self):
        try:
            cards = gpu.local_gpus()
        except core.ZygoteError as error:
            self.gpu_names.setText(f'GPU: {error}')
            self.gpu_meter.set_percent(None)
            self.memory.set_parts([], 0, 'memory unknown')
        else:
            total, used = sum(card['total_mib'] for card in cards), sum(card['used_mib'] for card in cards)
            self.gpu_names.setText('GPU: ' + (', '.join(card['name'] for card in cards) or 'no GPU found'))
            self.gpu_meter.set_percent(max((card['load'] for card in cards), default=None))
            if total:
                self.memory.set_parts([(used, OTHER)], total, f'GPU memory: {used / 1024:.1f} of {total / 1024:.1f} GB used ({used * 100 // total}%)')
            else:
                self.memory.set_parts([], 0, 'memory unknown')
        try:
            total, used = system.memory_mib()
            self.cpu_label.setText('CPU memory')
            self.cpu_bar.set_parts([(used, '#3a7bd5')], total, f'CPU memory: {used / 1024:.1f} of {total / 1024:.1f} GB used ({used * 100 // total}%)')
            self.cpu_meter.set_percent(self.cpu.percent())
        except core.ZygoteError as error:
            self.cpu_label.setText(f'CPU memory: {error}')
            self.cpu_bar.set_parts([], 0, '')
            self.cpu_meter.set_percent(None)
