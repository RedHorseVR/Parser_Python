"""The restart note in the header: when the files on disk are another version than the program running, a bold line says so with a Restart button (the person's press).
Nothing restarts by itself because of this note. The token counters will share this space later."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class RestartNote(QWidget):
    restartClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('restartnote')                          # its look is in ui_ux\theme.py
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 8, 2)
        self.text = QLabel()
        self.text.setObjectName('restarttext')
        self.button = QPushButton('Restart now')
        self.button.setToolTip('Close Zygote and start it again on this project: the whole program is loaded again from the files on disk.')
        self.button.clicked.connect(self.restartClicked.emit)
        row.addStretch(1)
        row.addWidget(self.text)
        row.addWidget(self.button)
        row.addStretch(1)
        self.hide()

    def show_for(self, running, disk):
        """Show the note when the two versions differ, hide it when they are the same."""
        if running == disk:
            self.hide()
            return
        self.text.setText(f'PLEASE RESTART ZYGOTE: this window runs {running}, the files are {disk}.')
        self.show()
