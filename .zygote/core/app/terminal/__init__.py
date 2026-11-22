"""The terminal module: ONE contract (`view.TerminalView`) and one adapter per terminal package. The window only knows the contract,
so a different terminal component is swapped in by adding a module here and one line below (see README.md).

Nothing in this module starts anything by itself: a program starts only when the window's Run (or Commit) button calls `start`."""
import importlib
import os

from functional.core import ZygoteError

ADAPTERS = {'termqt': 'terminal.termqt_view'}              # name -> module that holds the adapter class `View`
DEFAULT_ADAPTER = 'termqt'


def make_terminal(name=DEFAULT_ADAPTER, parent=None):
    """A terminal view from the named adapter. Raises (loudly) when the adapter or its package is missing: there is no fallback."""
    if name not in ADAPTERS:
        raise ZygoteError(f'Unknown terminal adapter "{name}". Known: {", ".join(sorted(ADAPTERS))}.')
    os.environ.setdefault('QT_API', 'pyside6')              # qtpy (used by termqt) must pick the Qt that Zygote runs on
    try:
        module = importlib.import_module(ADAPTERS[name])
    except ImportError as error:
        raise ZygoteError(f'The terminal package for "{name}" is not installed in the Zygote environment ({error}). '
                          f'Run app_tree\\bat\\RUN.bat once: it installs what .zygote\\config\\requirements.txt lists.') from error
    return module.View(parent)
