# terminal

One contract (`view.py`: `TerminalView`) and one adapter per terminal package. The Console tab of the window talks only to the contract.

- `__init__.py`: `ADAPTERS` (name -> module) and `make_terminal()`.
- `view.py`: the contract (start, send_text, stop, clear_view, screen_text, is_running; signals started, finished).
- `pty_io.py`: the program behind a pseudo-terminal (ConPTY via pywinpty on Windows, the standard pty elsewhere). No Qt.
- `termqt_view.py`: the adapter for the `termqt` widget (LGPL-2.1).

To swap the terminal component: add a module with a class `View(TerminalView)`, add one line to `ADAPTERS`, change `DEFAULT_ADAPTER`.
Nothing here starts a program by itself; only the window's buttons call `start`. This folder is code, written by hand.
