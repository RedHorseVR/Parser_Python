"""The window that ends Setup: what was done, what is new, a button for the help, and closing it starts Zygote (standard library only).

It is the one window of the install. It carries Zygote's icon like every window Zygote owns. Its wine background is a TRIAL (2026-11-13): it belongs to
this window only, so Luis can judge it before any other window changes; the colors are the four constants below and nowhere else.
Closing the window (the button or the X) is the user's own action, and it starts the IDE: that is the one process this module starts.
When Zygote is already open (`running`) closing starts nothing; the user who wants a second one presses Start another.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

BACKGROUND = '#5b1d33'      # wine (trial)
FOREGROUND = '#f6ecef'
MUTED = '#d9bcc6'
BUTTON = '#7a2a47'

NEWS_LIMIT = 5              # the lines of "what is new": the first bullets of the release notes, shortened
NEWS_WIDTH = 96


def ide_command(root):
    """The command that starts Zygote on its own folder (the environment's windowless Python), as a list. Nothing is run here."""
    root = Path(root)
    python = root / '.zygote' / 'env' / ('Scripts' if os.name == 'nt' else 'bin') / ('pythonw.exe' if os.name == 'nt' else 'python')
    return [str(python), str(root / 'app' / 'main.py'), '--project', str(root)]


def whats_new(root):
    """(the version, the short lines) read from this Zygote's own release notes: app_tree\\notes\\RELEASE_NOTES_<VERSION>.md. No notes: no lines."""
    root = Path(root)
    version = (root / '.zygote' / 'VERSION.txt').read_text(encoding='utf-8').strip()
    notes = root / 'app_tree' / 'notes' / f'RELEASE_NOTES_{version}.md'
    lines = []
    if notes.is_file():
        for raw in notes.read_text(encoding='utf-8').splitlines():
            if raw.startswith('- '):
                text = re.sub(r'[*`]', '', raw[2:]).replace('\\', '').strip()
                text = re.sub(r'\s+', ' ', text)
                lines.append(text if len(text) <= NEWS_WIDTH else text[:NEWS_WIDTH - 1].rstrip() + '…')
            if len(lines) == NEWS_LIMIT:
                break
    return version, lines


def help_file(root):
    """The README the button opens: Zygote's own help page, or None when this folder has none."""
    page = Path(root) / 'app_tree' / 'help' / 'zygote.html'
    return page if page.is_file() else None


def open_file(path):
    if os.name == 'nt':
        os.startfile(str(path))
    else:
        subprocess.Popen(['xdg-open', str(path)])


class Welcome:
    """What the window says and does. `tk` is the tkinter module (a stand-in in tests); `starter` runs the IDE command; `opener` opens the help page."""

    def __init__(self, root, did, tk=None, starter=subprocess.Popen, opener=open_file, running=False):
        self.root = Path(root)
        self.did = list(did)
        self.tk = tk
        self.starter = starter
        self.opener = opener
        self.running = running                                  # this Zygote is already open: closing starts no second one
        self.started = False
        self.version, self.news = whats_new(self.root)

    def start_ide(self):
        """Closing the window: start Zygote once, then end. A second close does nothing more."""
        if self.started:
            return None
        self.started = True
        process = self.starter(ide_command(self.root), cwd=str(self.root))
        if self.window is not None:
            self.window.destroy()
        return process

    def close(self):
        """The X and the Close button: start Zygote unless it is already open (then only end)."""
        if self.running:
            self.window.destroy()
            return None
        return self.start_ide()

    def read_help(self):
        page = help_file(self.root)
        if page is not None:
            self.opener(page)

    window = None

    def icon(self, window):
        icons = self.root / 'app_tree' / 'assets' / 'icons'
        try:
            if os.name == 'nt' and (icons / 'zygote.ico').is_file():
                window.iconbitmap(str(icons / 'zygote.ico'))
            elif (icons / 'zygote.png').is_file():
                self.picture = self.tk.PhotoImage(file=str(icons / 'zygote.png'))
                window.iconphoto(True, self.picture)
        except self.tk.TclError:
            pass                                                # a missing icon is not worth stopping the install for

    def label(self, text, size=10, bold=False, color=FOREGROUND, pad=(0, 0)):
        self.tk.Label(self.window, text=text, bg=BACKGROUND, fg=color, anchor='w', justify='left',
                      font=('Segoe UI', size, 'bold' if bold else 'normal')).pack(fill='x', padx=28, pady=pad)

    def show(self):
        """Build the window and wait for it to be closed. Returns when it is."""
        tk = self.tk
        self.window = tk.Tk()
        self.window.title('Zygote')
        self.window.configure(bg=BACKGROUND)
        self.window.resizable(False, False)
        self.icon(self.window)
        self.label('Zygote appears healthy' if self.running else 'Zygote is ready', 18, True, pad=(24, 6))
        if self.running:
            self.label('Zygote is already open, so no second one was started.', 10, color=MUTED, pad=(0, 6))
        for line in self.did:
            self.label('•  ' + line, 10, pad=(1, 0))
        if self.news:
            self.label(f'What is new in {self.version}', 11, True, MUTED, pad=(16, 2))
            for line in self.news:
                self.label('•  ' + line, 10, pad=(1, 0))
        buttons = tk.Frame(self.window, bg=BACKGROUND)
        buttons.pack(fill='x', padx=28, pady=(20, 22))
        if help_file(self.root) is not None:
            tk.Button(buttons, text='README', command=self.read_help, bg=BUTTON, fg=FOREGROUND, relief='flat', padx=16, pady=5).pack(side='left')
        if self.running:
            tk.Button(buttons, text='Close', command=self.close, bg=BUTTON, fg=FOREGROUND, relief='flat', padx=16, pady=5).pack(side='right')
            tk.Button(buttons, text='Start another Zygote', command=self.start_ide, bg=BUTTON, fg=FOREGROUND, relief='flat', padx=16, pady=5).pack(side='right', padx=8)
        else:
            tk.Button(buttons, text='Start Zygote', command=self.start_ide, bg=BUTTON, fg=FOREGROUND, relief='flat', padx=16, pady=5).pack(side='right')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.mainloop()
