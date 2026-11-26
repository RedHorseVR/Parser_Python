"""The header: where the title block (name, version, last change), the date and the program icon sit on the toolbar.

They are children of the toolbar, not toolbar entries, so the toolbar can never hide them. The icon stays at the top right with the date above it.
The title block sits in the middle of the free space; when the window is small it slides left, and when it would touch the Run buttons it goes
under them. The text is never cut with dots."""
from PySide6.QtCore import QEvent, QObject


class HeaderPlace(QObject):
    GAP = 10          # space between the block and its neighbours, in pixels

    def __init__(self, bar, title, date, icon):
        super().__init__(bar)
        self.bar = bar
        self.title = title
        self.date = date
        self.icon = icon
        self.busy = False                               # place() moves things that send events back to it
        for widget in (title, date, icon):
            widget.setParent(bar)
            widget.show()
        bar.installEventFilter(self)
        title.installEventFilter(self)                  # the restart note appearing changes the block's height
        self.place()

    def eventFilter(self, watched, event):
        if self.busy:
            return False
        if watched is self.title and event.type() == QEvent.LayoutRequest:
            self.place()
        elif watched is self.bar and event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest, QEvent.ActionChanged):
            self.place()
        return False

    def buttons_right(self):
        """The right edge of the last visible button, and the height of the button row."""
        right, height = 0, 0
        for action in self.bar.actions():
            if action.isVisible():
                rect = self.bar.actionGeometry(action)
                right = max(right, rect.right())
                cell = self.bar.widgetForAction(action)
                height = max(height, cell.sizeHint().height() + rect.top() if cell is not None else 0)
        return right, height

    def place(self):
        self.busy = True
        try:
            self.place_all()
        finally:
            self.busy = False

    def place_all(self):
        bar = self.bar
        title_w, title_h = self.title.sizeHint().width(), self.title.sizeHint().height()
        self.title.resize(title_w, title_h)
        date_h = self.date.sizeHint().height()
        icon_w, icon_h = self.icon.width(), self.icon.height()
        icon_x = bar.width() - icon_w
        date_w = max(icon_w, self.date.sizeHint().width() + 4)          # the whole date, whatever the screen scaling; its right edge is the icon's
        self.date.setGeometry(bar.width() - date_w, 0, date_w, date_h)
        self.icon.move(icon_x, date_h)
        buttons_right, buttons_h = self.buttons_right()
        free_left = buttons_right + self.GAP
        free_right = min(icon_x, bar.width() - date_w) - self.GAP
        wanted = max(title_h, date_h + icon_h)
        x = free_left + (free_right - free_left - title_w) // 2
        y = 0
        if x < free_left:                                       # too small for the middle: slide left
            x = max(self.GAP // 2, free_right - title_w)
        if x < free_left:                                       # still touches the Run buttons: go under them
            y = buttons_h + 2
            wanted = max(wanted, y + title_h)
        self.title.move(x, y)
        self.title.raise_()
        if bar.minimumHeight() != wanted or bar.maximumHeight() != wanted:
            bar.setFixedHeight(wanted)
