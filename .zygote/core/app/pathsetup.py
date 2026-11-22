"""The `zygote` command: Setup puts it on the user's PATH, and a Zygote that was moved puts it back (standard library only; runs before the environment exists).

The command is the folder .zygote\\bin of one Zygote (zygote.cmd on Windows, zygote on Linux). It holds NO path: it finds its own folder when it runs.
The PATH entry is the one place where Zygote's location is written, because the PATH is how a computer finds a command. Nothing else stores it.

    add(root)    Setup: put root's .zygote\\bin on the user's PATH (Windows: the user's Environment key; Linux: a link in ~/.local/bin).
    heal(root)   Every start: when the PATH names a Zygote folder that is no longer there (the folder was moved) and this one is not on the PATH yet,
                 replace the stale entry with this one. Returns the sentence for the Log, or None when nothing was stale. A second live copy is never taken over.
"""
import os
import sys
from pathlib import Path

BIN = Path('.zygote') / 'bin'
WINDOWS = os.name == 'nt'
COMMAND = 'zygote.cmd' if WINDOWS else 'zygote'
REOPEN = 'Close and reopen any terminal that is open: it still has the old PATH.'


def bin_dir(root):
    return Path(root) / BIN


# ---- the user's PATH -------------------------------------------------------------------------------------------------------------------
def read_path():
    """The user's own PATH, as a list of folders (Windows: HKCU\\Environment\\Path, not the system part)."""
    if not WINDOWS:
        return [str(link_file().parent)] if link_file().is_symlink() or link_file().exists() else []
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
        try:
            text, _ = winreg.QueryValueEx(key, 'Path')
        except FileNotFoundError:
            text = ''
    return [part for part in text.split(';') if part]


def write_path(entries):
    if not WINDOWS:
        raise RuntimeError('The PATH of a Linux user is not written as a list; Linux uses a link (see add and heal).')
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, 'Path', 0, winreg.REG_EXPAND_SZ, ';'.join(entries))
    result = ctypes.c_long()                                  # tell the running Windows that the environment changed (new terminals see it)
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, 'Environment', 2, 5000, ctypes.byref(result))


def link_file():
    return Path.home() / '.local' / 'bin' / 'zygote'


def same(first, second):
    return os.path.normcase(os.path.normpath(str(first))) == os.path.normcase(os.path.normpath(str(second)))


def is_zygote_bin(entry):
    """An entry that looks like the command folder of some Zygote (whether or not it still exists)."""
    parts = Path(entry).parts
    return len(parts) >= 2 and parts[-2:] == ('.zygote', 'bin')


# ---- add and heal ----------------------------------------------------------------------------------------------------------------------
def add(root):
    """Put root's command on the PATH. Returns the sentence that says so. Raises when root has no command file."""
    folder = bin_dir(root)
    if not (folder / COMMAND).is_file():
        raise RuntimeError(f'{folder / COMMAND} is missing; this is not a complete Zygote folder.')
    if not WINDOWS:
        return add_link(folder)
    entries = read_path()
    kept = [entry for entry in entries if not same(entry, folder) and not (is_zygote_bin(entry) and not (Path(entry) / COMMAND).is_file())]
    write_path(kept + [str(folder)])
    return f'The command "zygote" now starts the Zygote in {Path(root)}. {REOPEN}'


def add_link(folder):
    link = link_file()
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to((folder / COMMAND).resolve())
    return f'The command "zygote" now starts the Zygote in {folder.parent.parent}. (It is a link at {link}; ~/.local/bin must be on your PATH.) {REOPEN}'


def heal(root):
    """The move check, at every start. Returns the sentence for the Log when a stale entry was replaced, else None (nothing stale, or no command at all:
    Setup is what adds the command the first time, and a second Zygote that is still there is left alone)."""
    folder = bin_dir(root)
    if not (folder / COMMAND).is_file():
        return None
    if not WINDOWS:
        link = link_file()
        if link.is_symlink() and not link.exists():
            link.unlink()
            return add_link(folder).replace('now starts', 'was moved; now starts', 1)
        return None
    entries = read_path()
    if any(same(entry, folder) for entry in entries):
        return None
    stale = [entry for entry in entries if is_zygote_bin(entry) and not (Path(entry) / COMMAND).is_file()]
    if not stale:
        return None
    write_path([entry for entry in entries if entry not in stale] + [str(folder)])
    return f'Zygote was moved: the command "zygote" pointed at {stale[0]}. It now points at {Path(root)}. {REOPEN}'


def registry_entries():
    """Windows: the folders of the system PATH and of the user's PATH as Windows holds them now (a program installed after this program started is in them
    and not in its own PATH). Empty on other systems."""
    if not WINDOWS:
        return []
    import winreg
    found = []
    for hive, name in ((winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'), (winreg.HKEY_CURRENT_USER, 'Environment')):
        try:
            with winreg.OpenKey(hive, name) as key:
                text, _ = winreg.QueryValueEx(key, 'Path')
        except OSError:
            continue
        found += [os.path.expandvars(part) for part in text.split(';') if part]
    return found


def find_command():
    """Where the PATH finds `zygote` right now (a folder), or None. Used by Setup's report."""
    import shutil
    found = shutil.which('zygote')
    return Path(found).resolve().parents[2] if found else None


def separate_copy_notice(root, found=None):
    """The sentence for the Log when the `zygote` command starts a DIFFERENT Zygote than this one (a test copy that a self-extracting package unpacked beside the
    real one), else None. `found` is where the command points (tests hand it in; a library lookup, no process). Nothing is changed."""
    found = find_command() if found is None else found
    if found is None or same(found, root):
        return None
    return (f'This Zygote ({Path(root)}) is a separate copy: the zygote command still starts the one in {Path(found)}. '
            f'When the test is over, delete this folder; to make this one the real Zygote instead, run Setup.bat in it.')


if __name__ == '__main__':
    print(heal(Path(__file__).resolve().parents[1]) or 'Nothing to heal.', file=sys.stderr)
