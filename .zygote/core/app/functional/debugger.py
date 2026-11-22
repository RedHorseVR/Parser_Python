"""Stepping through a program: plain Python, no Qt (so the same code can serve a web front later).

A LANGUAGE BUNDLE is a folder with a bundle.json, in the project's app_tree\\language\\<name>. The code never lists languages: whatever bundle the
project has decides which files it owns and how its debugger is started and driven. Zygote carries a shelf of bundles in
app_tree\\assets\\language; a bundle gets into a project only when the person asks (Debug > Language bundle…).

BREAKPOINTS live in the bundle's own folder, mirroring the project's tree like unit tests mirror code:
    app_tree\\language\\python\\breakpoints\\app\\ui_ux\\main_window.py.json   =   {"fingerprint": "<sha1 of the file>", "lines": [12, 40]}
A file that changed since its breakpoints were set loses them (the lines would be wrong); the caller says so."""
import hashlib
import json
import re
import shutil
from pathlib import Path

from functional import core
from functional.core import ZygoteError

LANGUAGE = 'language'
SHELF = core.zpath(core.ZYGOTE_ROOT, 'assets', LANGUAGE)
DEBUGGER_KEYS = ('program', 'start', 'prompt', 'position', 'step_over', 'step_into', 'continue', 'set_breakpoint', 'clear_breakpoint', 'finished', 'quit')
JUMP = re.compile(r'\x1b\[\d*;?\d*[Hf]')                              # a terminal that redraws its screen moves the cursor instead of ending a line
ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07')          # colour and cursor codes a terminal program prints


class Bundle:
    """One language bundle, read from its bundle.json (a wrong file stops loudly, naming the file and the key)."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.file = self.folder / 'bundle.json'
        try:
            data = json.loads(self.file.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise ZygoteError(f'The language bundle {self.file} cannot be read ({error}).') from error
        self.name = self.need(data, 'name')
        self.extensions = [ext.lower() for ext in self.need(data, 'extensions')]
        self.debugger = self.need(data, 'debugger')
        for key in DEBUGGER_KEYS:
            self.need(self.debugger, key)
        self.position = re.compile(self.debugger['position'], re.MULTILINE)
        if not {'file', 'line'} <= set(self.position.groupindex):
            raise ZygoteError(f'{self.file}: debugger "position" must have the groups (?P<file>…) and (?P<line>…).')

    def need(self, data, key):
        if key not in data:
            raise ZygoteError(f'{self.file}: the key "{key}" is missing.')
        return data[key]

    def owns(self, path):
        return Path(path).suffix.lower() in self.extensions

    def start_words(self, project, entry, args):
        """The program that debugs, with its start words ("{entry}" and "{args}" filled in): nothing is started."""
        words = [core.find_runner(project, self.debugger['program'])]
        for word in self.debugger['start']:
            if word == '{args}':
                words += core.split_words(args)
            else:
                words.append(word.replace('{entry}', str(entry)))
        return words

    def text(self, key, **fields):
        """What a debugger button types (without the Enter), for example "b C:\\p\\Z.py:12"."""
        return self.debugger[key].format(**fields)


def bundles(project):
    """The bundles this project has (one per folder of app_tree\\language that holds a bundle.json), by folder name."""
    root = core.zpath(project, LANGUAGE)
    if not root.is_dir():
        return []
    return [Bundle(folder) for folder in sorted(root.iterdir()) if (folder / 'bundle.json').is_file()]


def bundle_for(project, path):
    """The bundle that owns this file, or None."""
    return next((bundle for bundle in bundles(project) if bundle.owns(path)), None)


def shelf_names():
    return sorted(folder.name for folder in SHELF.iterdir() if (folder / 'bundle.json').is_file()) if SHELF.is_dir() else []


def add_from_shelf(project, name):
    """Copy a bundle of Zygote's shelf into the project. An existing one is never replaced."""
    if name not in shelf_names():
        raise ZygoteError(f'Zygote has no language bundle "{name}" on its shelf (it has: {", ".join(shelf_names()) or "none"}).')
    target = core.zpath(project, LANGUAGE, name)
    if target.exists():
        raise ZygoteError(f'{target} already exists: the bundle is not replaced.')
    shutil.copytree(SHELF / name, target)
    return target


def fingerprint(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


class Breakpoints:
    """The breakpoints of one bundle in one project. Only the project's own files can have them."""

    def __init__(self, project, bundle):
        self.project = Path(project)
        self.root = bundle.folder / 'breakpoints'
        self.dropped = []                                           # (file, how many) of the breakpoints dropped because the file changed: the caller says so

    def store(self, path):
        try:
            rel = Path(path).resolve().relative_to(self.project.resolve())
        except ValueError as error:
            raise ZygoteError(f'{path} is not in the project: breakpoints are kept for the project\'s own files.') from error
        return self.root / (rel.as_posix() + '.json')

    def read(self, path):
        """(lines, dropped): the breakpoint lines of a file, and how many were dropped because the file changed since they were set."""
        entry = self.store(path)
        if not entry.is_file():
            return [], 0
        try:
            data = json.loads(entry.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise ZygoteError(f'The breakpoint file {entry} cannot be read ({error}).') from error
        if not Path(path).is_file() or data.get('fingerprint') != fingerprint(path):
            entry.unlink()
            self.dropped.append((str(path), len(data.get('lines', []))))
            return [], len(data.get('lines', []))
        return sorted(data.get('lines', [])), 0

    def write(self, path, lines):
        entry = self.store(path)
        if not lines:
            if entry.is_file():
                entry.unlink()
            return
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(json.dumps({'fingerprint': fingerprint(path), 'lines': sorted(lines)}, indent=1) + '\n', encoding='utf-8')

    def toggle(self, path, line):
        """Set the breakpoint of a line, or clear it when it is set. Returns True when it is set now."""
        lines, _ = self.read(path)
        on = line not in lines
        self.write(path, sorted(set(lines) | {line}) if on else [one for one in lines if one != line])
        return on

    def everything(self):
        """{absolute path: [lines]} of every file that has breakpoints (stale files are dropped as they are read)."""
        found = {}
        for entry in sorted(self.root.rglob('*.json')) if self.root.is_dir() else []:
            source = self.project / entry.relative_to(self.root).as_posix()[:-len('.json')]
            lines, _ = self.read(source)
            if lines:
                found[str(source)] = lines
        return found

    def clear(self):
        """Remove every breakpoint. Returns {path: [lines]} of what was removed."""
        removed = self.everything()
        for path in removed:
            self.write(path, [])
        return removed

    def orphans(self):
        """The breakpoint files whose source file is not in the project any more (reported, never deleted by Zygote on its own)."""
        found = []
        for entry in sorted(self.root.rglob('*.json')) if self.root.is_dir() else []:
            source = self.project / entry.relative_to(self.root).as_posix()[:-len('.json')]
            if not source.is_file():
                found.append(source)
        return found


class PositionReader:
    """Reads a debugger's own output: when it shows its prompt it has stopped, and the last "file, line" printed before the prompt is where."""

    TAIL = 20000                                                    # characters kept while no prompt was seen yet

    def __init__(self, bundle):
        self.bundle = bundle
        self.pending = ''
        self.finished = False                                       # the debugger said the program ended (it waits at its prompt, ready to start over)
        self.positions = []                                         # every position read in the output before the latest prompt
        self.last = ''                                              # what was read before the latest prompt (for the Log when no position was found in it)

    def seen(self):
        """The end of what has been read and not yet used, printable (control characters shown): the diagnostic put into the Log."""
        return repr((self.pending or self.last)[-240:])

    def reset(self):
        self.pending = ''
        self.finished = False

    def feed(self, text):
        """Give it what the program printed. Returns None while the program is still running, else (path or None, line or None) of the stop."""
        self.pending = (self.pending + ANSI.sub('', JUMP.sub('\n', text)).replace('\r', '').replace('\x07', '').replace('\x00', ''))[-self.TAIL:]
        if self.bundle.debugger['finished'] in self.pending:
            self.finished = True
        if not self.pending.rstrip().endswith(self.bundle.debugger['prompt']):
            return None
        stops = list(self.bundle.position.finditer(self.pending))
        self.last, self.pending = self.pending, ''
        self.positions = [(stop.group('file'), int(stop.group('line'))) for stop in stops]
        if not stops:
            return None, None
        return stops[-1].group('file'), int(stops[-1].group('line'))
