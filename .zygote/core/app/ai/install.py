"""Installing Ollama from the AI panel (Windows). The panel downloads Ollama's own installer (ai\\download.py) from the one address below, after the
person said Yes, and starts it: ONE process, the installer, which shows its own window. Nothing else is started here, Zygote never starts Ollama, and
nothing runs again by itself. On another system the person is told to use the command on ollama.com in the Ollama console."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from functional.core import ZygoteError

OLLAMA_URL = 'https://ollama.com/download/OllamaSetup.exe'
INSTALLER = 'OllamaSetup.exe'


def can_install():
    return os.name == 'nt'


def installer_path():
    return Path(tempfile.gettempdir()) / INSTALLER


def remove_old_installer():
    """A finished or abandoned download of an earlier press is deleted before the next one."""
    try:
        installer_path().unlink(missing_ok=True)
    except OSError:
        pass                                                 # still running from an earlier press: the new download then fails loudly


def start_installer(path, starter=subprocess.Popen):
    if not can_install():
        raise ZygoteError('Ollama\'s installer runs on Windows only. On this system install Ollama with the command on https://ollama.com/download '
                          '(the Ollama console of this panel can run it).')
    return starter([str(path)])


def is_installed():
    """True when Ollama's program is on this computer: on the PATH (after the entries installed since Zygote started were added), or where its installer puts it."""
    from functional import core
    core.refresh_path()
    if shutil.which('ollama'):
        return True
    local = os.environ.get('LOCALAPPDATA')
    return bool(local) and (Path(local) / 'Programs' / 'Ollama' / 'ollama.exe').is_file()
