"""Zygote starts without a console window (pythonw), so an error would vanish. This writes every uncaught error to
.zygote\\logs\\zygote_error.log (text: the date, then the traceback) and shows it in a message box when it can.
Standard library only, and imported first by main.py so that even a failing import is recorded."""
import datetime
import sys
import traceback
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / '.zygote' / 'logs' / 'zygote_error.log'


def version():
    """The running Zygote's version: first line of .zygote\\VERSION.txt (this file only reads it, so it works even when everything else failed)."""
    path = LOG.parents[1] / 'VERSION.txt'
    try:
        return path.read_text(encoding='utf-8').strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return '?'


def error_title():
    """The title of every error pop-up: Zygote, its version and the date and time it happened."""
    return f'Zygote {version()} \u2014 {datetime.datetime.now():%Y-%m-%d %H:%M:%S}'


def write(text):
    """Append one report to the log. Returns the log path."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    with open(LOG, 'a', encoding='utf-8') as out:
        out.write(f'--- {stamp} {version()}\n{text}\n')
    return LOG


def hook(kind, error, trace):
    """sys.excepthook: log the error, show it, and (when there is a console) print it as Python would."""
    text = ''.join(traceback.format_exception(kind, error, trace))
    path = write(text)
    sys.__excepthook__(kind, error, trace)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, error_title(), f'Zygote hit an error. It is also written to\n{path}\n\n{text[-1500:]}')
    except Exception:                                         # nothing more can be done here; the log already has it
        pass


def install():
    sys.excepthook = hook
