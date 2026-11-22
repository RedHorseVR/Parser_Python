"""Zygote entry point.

    .zygote\\env\\Scripts\\pythonw.exe app\\main.py [--project <folder>]

With --project (what a project's own shortcut passes) that folder is opened. Without it the window opens and asks for a
project folder: drop it, pick it, or press "Open in current folder" (the folder Zygote was started from), then confirm.
A folder Zygote already recorded a name for (the start folder first) opens without asking. Nothing else is chosen for the user.
"""
import argparse
import functools
import sys
from pathlib import Path

import crashlog
crashlog.install()                                            # first, so that even a failing import below is written to .zygote\logs\zygote_error.log

import bootstrap
import pathsetup
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QApplication, QSplashScreen

from functional import core
from ui_ux.instance import BARE, InstanceGuard
from ui_ux.main_window import MainWindow
from ui_ux.theme import Theme


SPLASH_CAP_MS = 30000                                         # the splash never stays longer than this


class Splash(QSplashScreen):
    """The start-up window: a click on it dismisses it (the window behind is already there)."""
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()


def make_splash():
    """The window that shows at once while Zygote builds and finds its place: the icon, the name, a line saying what is happening."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    colors = Theme.colors()
    pixmap = QPixmap(420, 220)
    pixmap.fill(QColor(colors['window']))
    painter = QPainter(pixmap)
    painter.setPen(QColor(colors['frame']))
    painter.drawRect(0, 0, pixmap.width() - 1, pixmap.height() - 1)
    icon = QIcon(str(core.ICON_FILE)).pixmap(96, 96)
    if not icon.isNull():
        painter.drawPixmap(30, 62, icon)
    big = QFont()
    big.setPointSize(26)
    big.setBold(True)
    painter.setFont(big)
    painter.setPen(QColor(colors['bright']))
    painter.drawText(150, 110, 'Zygote')
    small = QFont()
    small.setPointSize(10)
    painter.setFont(small)
    painter.setPen(QColor(colors['text']))
    painter.drawText(152, 140, f'{core.tool_version()}  ·  opening…')
    painter.end()
    return Splash(pixmap, Qt.WindowStaysOnTopHint)


def end_splash(window, splash, why):
    """The splash goes (once). When it goes before the working space is in, the Log says what was still loading."""
    if not splash.isVisible():
        return
    splash.close()
    pending = window.still_loading()
    if pending:
        window.say(f'Start-up screen closed ({why}); still loading: {", ".join(pending)}.')


def show_window(window, splash):
    """The window shows at once, behind the splash. The splash waits for the working space only (the project folder in the folder view and
    the project tree); a click on it or 30 seconds end it sooner."""
    window.show()
    splash.raise_()
    if not window.still_loading():
        splash.close()
        return
    window.working_space_ready.connect(splash.close)
    splash.clicked.connect(functools.partial(end_splash, window, splash, 'clicked'))
    QTimer.singleShot(SPLASH_CAP_MS, functools.partial(end_splash, window, splash, f'{SPLASH_CAP_MS // 1000} s passed'))


def open_then_show(window, splash, folder):
    """Open the project while the window is still hidden (its saved place and bars are put back first), then show it, before any question."""
    try:
        window.open_project(folder, functools.partial(show_window, window, splash))
    finally:
        if not window.isVisible():
            show_window(window, splash)                           # a project that fails to open still gets its window, with the error on it


def heal_command():
    """The move check: when the `zygote` command on the PATH points at a Zygote folder that is gone, point it here. The sentence for the Log, or None.
    A failure is shown in the Log too; Zygote itself starts from where it sits and does not need the command."""
    import pathsetup
    try:
        return pathsetup.heal(core.ZYGOTE_ROOT)
    except OSError as error:
        return f'The command "zygote" could not be repaired: {error}'


def main(argv):
    problem = bootstrap.stale_reason()
    if problem:
        raise RuntimeError(problem)                               # fail loud (crash log + message box): a shortcut skips the bootstrap
    parser = argparse.ArgumentParser(prog='Zygote', description='Floating project window: version, run, commit, drop a build ZIP.')
    parser.add_argument('--project', help='folder of the project to open')
    parser.add_argument(core.UPDATED_SWITCH, action='store_true', help='this start follows an update (the old Zygote passes it on; nothing is written to disk)')
    args = parser.parse_args(argv)
    app = QApplication([sys.argv[0]])
    wanted = core.clean_path(args.project) if args.project else BARE
    if InstanceGuard.ask_running(wanted):                     # one window per project (and one bare Zygote): the one that runs is brought to the front
        return 0
    Theme.apply(app)                                          # the look belongs to the project: it is applied when a project is opened
    splash = make_splash()
    splash.show()
    app.processEvents()                                       # the splash is on the screen before the window is built
    window = MainWindow(Path.cwd())
    window.hold_instance(wanted)
    healed = heal_command()
    if healed:
        window.say(healed)                                    # a moved Zygote repaired the `zygote` command: said loudly, in the Log
    copy = pathsetup.separate_copy_notice(core.ZYGOTE_ROOT)
    if copy:
        window.say(copy)                                      # a test copy next to the real Zygote: said once, in the Log
    if args.project:
        window.guarded(functools.partial(open_then_show, window, splash, args.project))
        QTimer.singleShot(0, window, functools.partial(window.guarded, window.offer_core_update))      # a project behind the installed Zygote is offered the update, once per start
    else:
        show_window(window, splash)
        QTimer.singleShot(0, lambda: window.guarded(window.start_here))
    if args.updated:
        QTimer.singleShot(0, window, functools.partial(window.show_toast, 'Update complete'))      # once, when the window is up
    return app.exec()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
