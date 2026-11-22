"""Is this Zygote already open? One question, the same on every system: `open_check().is_open(root)`.

Windows asks the list of open windows: a Zygote window's title ends with "Zygote <version>" (the version of the Zygote that runs it), so a window that
ends that way, with this folder's VERSION.txt version, means this version of Zygote is open. Linux asks the running programs instead (a window has no
title without a window-system tool): a program whose command line runs <root>/app/main.py means this Zygote is open.
Both read only; no file, no marker and no new process (doctrine: Paths and Setup). The two classes have the same methods, so a package or a
bigger set of utilities can replace them later without the callers changing. Standard library only (Setup runs on the system Python).
"""
import ctypes
import os
from pathlib import Path

WINDOWS = os.name == 'nt'                               # patchable, like pathsetup.WINDOWS


def tool_version(root):
    """First line of <root>\\.zygote\\VERSION.txt, or '' when there is none."""
    path = Path(root) / '.zygote' / 'VERSION.txt'
    lines = path.read_text(encoding='utf-8').strip().splitlines() if path.is_file() else []
    return lines[0].strip() if lines else ''


def title_is_zygote(title, version):
    """True for the window titles Zygote gives itself: '<project>, version <v> — Zygote <version>' or, with no project, 'Zygote <version>'."""
    return bool(version) and (title == f'Zygote {version}' or title.endswith(f' Zygote {version}'))


class OpenCheck:
    """The interface: is this Zygote (the one in `root`) open now?"""

    def is_open(self, root):
        raise NotImplementedError


class WindowsOpenCheck(OpenCheck):
    """The open windows of Windows, by their titles. `user32` is the Windows library (a stand-in in tests)."""

    def __init__(self, user32=None):
        self.user32 = user32
        self.found = []

    def library(self):
        return self.user32 if self.user32 is not None else ctypes.windll.user32

    def visit(self, handle, _unused):
        """Called once per top-level window by EnumWindows: remember the title of a visible window."""
        user32 = self.library()
        if user32.IsWindowVisible(handle):
            size = user32.GetWindowTextLengthW(handle)
            if size:
                buffer = ctypes.create_unicode_buffer(size + 1)
                user32.GetWindowTextW(handle, buffer, size + 1)
                self.found.append(buffer.value)
        return True

    def titles(self):
        self.found = []
        kind = getattr(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE)
        callback = kind(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(self.visit)
        self.library().EnumWindows(callback, 0)
        return list(self.found)

    def is_open(self, root):
        version = tool_version(root)
        return any(title_is_zygote(title, version) for title in self.titles())


class LinuxOpenCheck(OpenCheck):
    """The running programs of Linux (/proc, one command line each). `proc` is the folder of them (a stand-in folder in tests)."""

    def __init__(self, proc='/proc'):
        self.proc = Path(proc)

    def command_lines(self):
        """The arguments of every running program that can be read (others are skipped: they ended, or are not ours)."""
        lines = []
        for entry in self.proc.iterdir():
            if entry.name.isdigit():
                try:
                    lines.append([part for part in (entry / 'cmdline').read_bytes().decode('utf-8', 'replace').split('\0') if part])
                except OSError:
                    continue
        return lines

    def is_open(self, root):
        main = str(Path(root).resolve() / 'app' / 'main.py')
        for arguments in self.command_lines():
            for argument in arguments[1:3]:                       # the script is the first or second word: python main.py, or python -u main.py
                if argument.endswith('main.py') and str(Path(argument).resolve()) == main:
                    return True
        return False


def open_check():
    return WindowsOpenCheck() if WINDOWS else LinuxOpenCheck()
