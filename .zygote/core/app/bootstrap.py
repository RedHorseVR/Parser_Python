"""Zygote bootstrap: build the project's own Python environment (.zygote\\env\\) from .zygote\\config\\requirements.txt.

Runs before the environment exists, so it uses the standard library only. app_tree\\bat\\RUN.bat runs it first, then starts the app with
the environment's Python. The environment is rebuilt only when it is missing or when requirements.txt changed; then a small
window says "Building the environment, please wait" until it is done. What was installed is recorded as data inside
env\\INSTALLED.json (the requirements hash, the date, the Python version). Any failure stops loudly: there is no fallback.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import shutil
import threading
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOYED = (ROOT / 'deploy.json').is_file()                 # a folder Deploy made: its start script built the environment in .venv (the folder's own data says what it is)
ENV = ROOT / '.venv' if DEPLOYED else ROOT / '.zygote' / 'env'
REQUIREMENTS = ROOT / '.zygote' / 'config' / 'requirements.txt'
RECORD = ENV / 'INSTALLED.json'


def env_moved_reason():
    """None when the environment's Python exists and the Python it was made from is still on this computer; else the plain reason it cannot be used
    (an environment copied from another computer names the Python of that computer). A folder that was only moved or renamed keeps its environment:
    the Python of an environment finds its files from where it sits."""
    if not env_python().is_file():
        return 'The environment has no Python of its own yet.'
    config = ENV / 'pyvenv.cfg'
    if config.is_file():
        for line in config.read_text(encoding='utf-8').splitlines():
            if line.split('=')[0].strip() == 'home':
                if not Path(line.split('=', 1)[1].strip()).is_dir():
                    return f'The Python this environment was made from is not on this computer ({line.split("=", 1)[1].strip()}).'
    return None


def env_python():
    return ENV / ('Scripts' if os.name == 'nt' else 'bin') / ('python.exe' if os.name == 'nt' else 'python')


def fix_hint():
    """What to do about a missing or old environment: a deployed folder builds it from its start file; the development folder from RUN.bat."""
    return 'Start it with start.bat (or the shortcut) in this folder: that builds the environment.' if DEPLOYED else 'Run app_tree\\bat\\RUN.bat once.'


def stale_reason():
    """None when the environment matches requirements.txt; otherwise the plain sentence that says what to do.
    main.py asks this at start-up, because a shortcut starts the app without the bootstrap."""
    if not RECORD.is_file():
        return f'The environment was never built ({RECORD} is missing). {fix_hint()}'
    moved = env_moved_reason()
    if moved:
        return f'{moved} {fix_hint()}'
    if recorded_hash() != requirements_hash():
        return f'config\\requirements.txt changed since the environment was built. {fix_hint()}'
    return None


def requirements_hash():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def recorded_hash():
    if not RECORD.is_file():
        return None
    return json.loads(RECORD.read_text(encoding='utf-8')).get('requirements_sha256')


class Build:
    """The work of making env\\: create it if needed, install the requirements, record what was done.
    It runs in a worker thread; `output` and `error` are read by the status window."""

    def __init__(self, want):
        self.want = want
        self.output = []
        self.error = None

    def run(self):
        try:
            self.build()
        except Exception as error:                      # shown in the window, then raised again by the caller
            self.error = error

    def run_quietly(self, command):
        """Run one child (ensurepip, pip) and show its lines in the status window. On Windows the child gets NO console window of its own: a Setup that runs
        without a console (pythonw) would otherwise see a big python.exe console open over the status window for every child. The one subprocess of the build."""
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for line in process.stdout:
            self.output.append(line.rstrip())
        if process.wait() != 0:
            raise RuntimeError(f'{" ".join(command[1:4])} failed')

    def build(self):
        moved = env_moved_reason()
        if moved:
            self.output.append(f'Building the Python environment in {ENV}')
            if ENV.exists():
                for child in ENV.iterdir():                      # only the generated environment is cleared; never the folder's README
                    if child.name != 'README.md':
                        shutil.rmtree(child) if child.is_dir() else child.unlink()
            venv.EnvBuilder(with_pip=False).create(ENV)          # pip is put in by run_quietly below, not by venv: venv's own child would open a console window
            self.run_quietly([str(env_python()), '-m', 'ensurepip', '--upgrade', '--default-pip'])
        self.output.append(f'Installing from {REQUIREMENTS}')
        self.run_quietly([str(env_python()), '-m', 'pip', 'install', '-r', str(REQUIREMENTS)])
        RECORD.write_text(json.dumps({
            'requirements_sha256': self.want,
            'installed': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'python': sys.version.split()[0],
        }, indent=2) + '\n', encoding='utf-8')


def set_icon(window):
    """Zygote's icon on a window of the build (Windows: the .ico; elsewhere the .png). A missing icon never stops the build."""
    import tkinter
    icons = ROOT / 'app_tree' / 'assets' / 'icons'
    try:
        if os.name == 'nt' and (icons / 'zygote.ico').is_file():
            window.iconbitmap(str(icons / 'zygote.ico'))
        elif (icons / 'zygote.png').is_file():
            window.picture = tkinter.PhotoImage(file=str(icons / 'zygote.png'))
            window.iconphoto(True, window.picture)
    except tkinter.TclError:
        pass


class StatusWindow:
    """A small window that says the environment is being built, until the worker thread is done."""

    def __init__(self, build):
        import tkinter
        from tkinter import ttk
        self.tkinter = tkinter
        self.build = build
        self.root = tkinter.Tk()
        self.root.title('Zygote')
        self.root.resizable(False, False)
        set_icon(self.root)
        tkinter.Label(self.root, text='Building the environment, please wait…', font=('Segoe UI', 14, 'bold')).pack(padx=30, pady=(24, 4))
        tkinter.Label(self.root, text='The first run on a computer takes a few minutes.\nThis window closes by itself.').pack(padx=30)
        bar = ttk.Progressbar(self.root, mode='indeterminate', length=360)
        bar.pack(padx=30, pady=(14, 6))
        bar.start(12)
        self.status = tkinter.Label(self.root, text='', fg='#666666', width=60, anchor='w')
        self.status.pack(padx=30, pady=(0, 20))
        self.worker = threading.Thread(target=build.run, daemon=True)

    def poll(self):                                      # reads the thread's state; starts nothing
        if self.build.output:
            self.status.config(text=self.build.output[-1][:70])
        if self.worker.is_alive():
            self.root.after(200, self.poll)
        else:
            self.root.destroy()

    def show(self):
        """Run the build behind the window. Raises the build's error, after showing it, if it failed."""
        self.worker.start()
        self.root.after(200, self.poll)
        self.root.mainloop()
        self.worker.join()
        if self.build.error is not None:
            from tkinter import messagebox
            tail = '\n'.join(self.build.output[-12:])
            root = self.tkinter.Tk()
            root.withdraw()
            messagebox.showerror('Zygote', f'Building the environment failed:\n{self.build.error}\n\n{tail}')
            root.destroy()
            self.build.error.shown = True                       # the caller must not show it a second time
            raise self.build.error


def main():
    want = requirements_hash()
    if env_moved_reason() is None and recorded_hash() == want:
        return 0
    StatusWindow(Build(want)).show()
    return 0


if __name__ == '__main__':
    sys.exit(main())
