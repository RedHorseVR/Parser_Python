"""The Project starter agent: reads the file list of a messy project and proposes where each file goes in Zygote's layout.
It only PROPOSES (old path => new path); nothing is moved here. No window code: the panel shows what this builds, and a test can run it with a stand-in model.
The model sees the files in small groups (a small model answers a short list well and a long one badly), always with the same layout text."""
import os
import shutil
from pathlib import Path, PurePosixPath

from functional import core

SKIP_FOLDERS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env', '.zygote', '.idea', '.vscode', '.claude', '.github'}
SCAN_LIMIT = 3000                                           # more files than this: the list is cut and the panel says so
GROUP_SIZE = 30                                             # files per question to the model
ARROW = '=>'
CODE_SUFFIXES = ('.py', '.pyw')
# What the rules decide without asking the model: the layout folder for each kind of file. A folder that holds any Python goes into app/ WHOLE (its
# notes and data stay with its code, so the imports and the relative paths keep working); another folder goes where ALL its files agree.
KIND_FOLDERS = {
    '.py': 'app/', '.pyw': 'app/', '.ui': 'app/',
    '.md': 'app_tree/notes/', '.txt': 'app_tree/notes/', '.rst': 'app_tree/notes/', '.xmind': 'app_tree/notes/', '.pptx': 'app_tree/notes/', '.docx': 'app_tree/notes/',
    '.bat': 'app_tree/bat/', '.cmd': 'app_tree/bat/', '.ps1': 'app_tree/bat/', '.sh': 'app_tree/bat/',
    '.png': 'app_tree/assets/', '.jpg': 'app_tree/assets/', '.jpeg': 'app_tree/assets/', '.gif': 'app_tree/assets/', '.ico': 'app_tree/assets/',
    '.svg': 'app_tree/assets/', '.bmp': 'app_tree/assets/', '.zip': 'app_tree/assets/',
    '.vfc': 'app_tree/architecture/',
    '.url': '.zygote/config/', '.lnk': '.zygote/config/', '.json': '.zygote/config/', '.ini': '.zygote/config/', '.cfg': '.zygote/config/',
    '.toml': '.zygote/config/', '.yaml': '.zygote/config/', '.yml': '.zygote/config/',
}

# Where things go. The part before the first space of each line is a real destination folder; the checker uses the same list.
LAYOUT = [
    ('app/', 'the program: ALL its Python code, kept together so the imports between files still work; files the code opens by name (.ui, small data files) go next to it'),
    ('app/data/', 'data files the program ships with that are not opened by name from the code (json, csv, databases)'),
    ('app_tree/notes/', 'documents: design notes, release notes, readme texts, pins'),
    ('app_tree/bat/', '.bat and .cmd launchers and scripts'),
    ('app_tree/tests/', 'tests and test data'),
    ('app_tree/assets/', 'icons, pictures, fonts, sounds'),
    ('app_tree/help/', 'the help of the program'),
    ('.zygote/config/', 'settings files and requirements'),
    ('app_tree/tools/', 'helper programs and scripts used to build or check the project'),
    ('app_tree/architecture/', 'diagrams of the code (.vfc flowcharts and similar)'),
]
ROOTS = tuple(folder for folder, _ in LAYOUT)


def scan(folder):
    """The files under folder as paths relative to it (with / between names), sorted, and True when the list was cut at SCAN_LIMIT."""
    found = []
    for here, names, files in os.walk(folder):
        names[:] = sorted(name for name in names if name not in SKIP_FOLDERS)
        if os.path.normpath(here) != os.path.normpath(folder) and '.git' in files + os.listdir(here):       # another repository inside (a submodule): its files are not ours to move
            names[:] = []
            continue
        for name in sorted(files):
            found.append(PurePosixPath(os.path.relpath(os.path.join(here, name), folder).replace(os.sep, '/')).as_posix())
            if len(found) >= SCAN_LIMIT:
                return sorted(found), True
    return sorted(found), False


KEEP_AT_TOP = {'.gitignore', '.gitmodules', '.gitattributes', 'license', 'license.md', 'license.txt', 'readme', 'readme.md', 'setup.bat', 'start_here.md', 'claude.md'}


def in_place(path):
    """True for a file that already sits in the layout (under app/ or .zygote/), or that must stay at the project's top (git files, the launcher,
    Setup.bat, the license and readme): it is left alone."""
    if path.startswith(ROOTS):
        return True
    return '/' not in path and (path.lower() in KEEP_AT_TOP or core.is_live_launcher_name(path))


def unit_of(path):
    """The top-level item a file belongs to: its first folder, or the file itself when it is at the top."""
    return path.split('/')[0]


def unit_destination(files):
    """The layout folder the rules choose for one top-level item (all its files), or None when the rules cannot tell (the model is asked then)."""
    if any(path.lower().endswith(CODE_SUFFIXES) for path in files):
        return 'app/'
    folders = {KIND_FOLDERS.get(PurePosixPath(path).suffix.lower()) for path in files}
    return folders.pop() if len(folders) == 1 and None not in folders else None


def groups(files, size=GROUP_SIZE):
    return [files[start:start + size] for start in range(0, len(files), size)]


def overview(files):
    """A few lines on the whole project, so every group is judged with the same picture: the top-level folders and the kinds of file."""
    top, kinds = {}, {}
    for path in files:
        first = path.split('/')[0] if '/' in path else '(top level)'
        top[first] = top.get(first, 0) + 1
        kind = PurePosixPath(path).suffix.lower() or '(no extension)'
        kinds[kind] = kinds.get(kind, 0) + 1
    where = ', '.join(f'{name}: {count}' for name, count in sorted(top.items(), key=lambda item: -item[1])[:25])
    what = ', '.join(f'{kind}: {count}' for kind, count in sorted(kinds.items(), key=lambda item: -item[1])[:15])
    return f'The project has {len(files)} files. By folder: {where}. By kind: {what}.'


def unit_line(name, files):
    if files == [name]:
        return f'{name}  (file)'
    kinds = {}
    for path in files:
        kind = PurePosixPath(path).suffix.lower() or 'no extension'
        kinds[kind] = kinds.get(kind, 0) + 1
    return f'{name}  (folder, {len(files)} files: ' + ', '.join(f'{kind} {count}' for kind, count in sorted(kinds.items(), key=lambda item: -item[1])[:6]) + ')'


def build_prompt(overview_text, lines, goal=''):
    layout = '\n'.join(f'{folder}  = {use}' for folder, use in LAYOUT)
    extra = f'\nWhat the person says about this project: {goal}\n' if goal.strip() else ''
    return (f'You sort the top-level items (files and folders) of a software project into the folder layout of a new project. A folder moves as ONE piece, '
            f'with everything in it.\n\nThe layout (the only places an item may go):\n{layout}\n\n'
            f'{overview_text}{extra}\n'
            f'Answer with one line per item, exactly like this:\nname {ARROW} app_tree/notes/\n'
            f'Copy the item name exactly as written below, and give the layout folder it goes into (ending with a slash). Use every item once. '
            f'No other text, no explanations.\n\nItems:\n' + '\n'.join(lines) + '\n')


def clean(line):
    line = line.strip().strip('`').strip()
    while line[:2] in ('- ', '* ') or (line[:1].isdigit() and '. ' in line[:5]):
        line = line.split(' ', 1)[1].strip()
    return line.strip('`').strip()


class Plan:
    """The proposal as it grows: moves {old: new} (file by file), problems (lines or moves that were refused, each with the reason) and the files nobody placed.
    The files are grouped in units, the top-level items: the rules and the model decide per unit, so a folder never ends up split in two places."""

    def __init__(self, files):
        self.files = list(files)
        self.known = set(files)
        self.moves = {}
        self.problems = []
        self.units = {}
        for path in self.files:
            if not in_place(path):
                self.units.setdefault(unit_of(path), []).append(path)

    def place_unit(self, unit, folder):
        """Every file of the unit goes to folder + its own path. Each move goes through the same checks as any other."""
        for path in self.units[unit]:
            self.add_reply([path], f'{path} {ARROW} {folder}{path}')

    def place_by_rule(self):
        for unit, files in self.units.items():
            folder = unit_destination(files)
            if folder:
                self.place_unit(unit, folder)

    def to_ask(self):
        """The units the rules could not decide: the model is asked about these."""
        return [unit for unit, files in self.units.items() if unit_destination(files) is None]

    def unit_lines(self, names):
        return [unit_line(name, self.units[name]) for name in names]

    def add_unit_reply(self, group, reply):
        """The model's lines for a group of units: `name => folder/`. A line that breaks a rule is a problem, never repaired."""
        inside = set(group)
        for raw in (reply or '').splitlines():
            line = clean(raw)
            if ARROW not in line:
                if line:
                    self.problems.append(f'not a move: {line[:80]}')
                continue
            name, folder = (part.strip().strip('`"\' ') for part in line.split(ARROW, 1))
            folder = folder if folder.endswith('/') else folder + '/'
            if name not in inside:
                self.problems.append(f'{name} {ARROW} {folder}: that is not one of the items asked about')
            elif any(path in self.moves for path in self.units[name]):
                self.problems.append(f'{name} {ARROW} {folder}: this item was already placed')
            elif not folder.startswith(ROOTS):
                self.problems.append(f'{name} {ARROW} {folder}: the folder is not in the layout')
            else:
                self.place_unit(name, folder)

    def add_reply(self, group, reply):
        """Take move lines `old/path => new/path` for files of group. A line that breaks a rule is a problem, never repaired."""
        inside = set(group)
        for raw in (reply or '').splitlines():
            line = clean(raw)
            if ARROW not in line:
                if line:
                    self.problems.append(f'not a move: {line[:80]}')
                continue
            old, new = (part.strip().strip('`"\' ') for part in line.split(ARROW, 1))
            reason = self.refuse(old, new, inside)
            if reason:
                self.problems.append(f'{old} {ARROW} {new}: {reason}')
            else:
                self.moves[old] = new

    def refuse(self, old, new, inside):
        if old not in inside:
            return 'the old path is not one of the files asked about'
        if old in self.moves:
            return 'this file was already placed'
        if not new or new.startswith('/') or ':' in new or '..' in new.split('/'):
            return 'the new path is not inside the project'
        if not new.startswith(ROOTS):
            return 'the new folder is not in the layout'
        if PurePosixPath(new).name != PurePosixPath(old).name:
            return 'the file name was changed; only the folder may change'
        if new in self.moves.values():
            return 'another file already goes to that path'
        if new in self.known and new != old and new not in self.moves:
            return 'a different file is already at that path'
        return None

    def unplaced(self):
        return [path for path in self.files if path not in self.moves and not in_place(path)]


class StarterRun:
    """Asks the model one group at a time (each answer starts the next question). progress(done_groups, total_groups, text) after every answer;
    finished(plan, error) at the end (error None when all groups were asked). stop() ends it after the answer in flight. `ollama` is ai.ollama.Ollama."""

    def __init__(self, ollama, model, files, progress, finished, goal=''):
        self.ollama, self.model, self.files, self.goal = ollama, model, files, goal
        self.progress, self.finished = progress, finished
        self.plan = Plan(files)
        self.plan.place_by_rule()
        self.asked = self.plan.to_ask()
        self.pending = groups(self.asked)
        self.total = len(self.pending)
        self.stopped = False
        self.index = 0

    def start(self):
        if not self.files:
            self.finished(self.plan, 'There are no files to place.')
            return
        if not self.pending:                                # the rules placed everything that needed placing
            self.finished(self.plan, None)
            return
        self.ask()

    def stop(self):
        self.stopped = True

    def ask(self):
        group = self.pending[self.index]
        self.progress(self.index, self.total, f'Asking {self.model} about items {self.index * GROUP_SIZE + 1} to {self.index * GROUP_SIZE + len(group)} of {len(self.asked)}…')
        self.ollama.generate(self.model, build_prompt(overview(self.files), self.plan.unit_lines(group), self.goal), lambda ok, data: self.answered(group, ok, data),
                             options={'temperature': 0, 'num_ctx': 8192}, keep_alive=-1)

    def answered(self, group, ok, data):
        if not ok:
            self.finished(self.plan, f'{self.model} did not answer: {data}')
            return
        reply = data.get('response', '') if isinstance(data, dict) else ''
        self.plan.add_unit_reply(group, reply)
        self.index += 1
        self.progress(self.index, self.total, f'{len(self.plan.moves)} files placed so far')
        if self.stopped:
            self.finished(self.plan, 'Stopped.')
        elif self.index >= self.total:
            self.finished(self.plan, None)
        else:
            self.ask()


def apply(folder, moves):
    """Do the chosen moves under folder. NEVER overwrites: a move whose file is gone, or whose new path is taken, is skipped with the reason.
    Returns {'done': [[old, new]], 'dirs': [folders this made, relative], 'skipped': [[old, reason]]}; 'done' and 'dirs' are what undo() needs."""
    root = Path(folder).resolve()
    result = {'done': [], 'dirs': [], 'skipped': []}
    for old, new in moves:
        source, target = (root / old), (root / new)
        if root not in target.resolve().parents or root not in source.resolve().parents:
            result['skipped'].append([old, 'a path is outside the folder'])
        elif not source.is_file():
            result['skipped'].append([old, 'the file is not there any more'])
        elif target.exists():
            result['skipped'].append([old, 'something is already at the new path'])
        else:
            for parent in reversed([p for p in target.parents if root in p.parents and not p.exists()]):
                result['dirs'].append(parent.relative_to(root).as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            result['done'].append([old, new])
    result['tidied'] = tidy(root, [old for old, _ in result['done']])
    return result


def tidy(root, olds):
    """Take away the folders the moved files came from when nothing else is in them (a folder that holds only __pycache__ counts as empty: it is
    rebuilt by Python when needed). Folders that were not donors are never touched. Returns the relative folders removed, deepest first."""
    donors = set()
    for old in olds:
        parent = PurePosixPath(old).parent
        while str(parent) != '.':
            donors.add(parent.as_posix())
            parent = parent.parent
    removed = []
    for name in sorted(donors, key=lambda text: text.count('/'), reverse=True):
        folder = root / name
        if not folder.is_dir():
            continue
        rest = [entry for entry in folder.iterdir() if not (entry.name == '__pycache__' and entry.is_dir())]
        if rest:
            continue
        shutil.rmtree(folder)
        removed.append(name)
    return removed


def undo(folder, journal):
    """Put back what apply() moved (newest first) and take away the folders it made if they are empty. Returns {'restored': [old], 'skipped': [[old, reason]]}."""
    root = Path(folder).resolve()
    result = {'restored': [], 'skipped': []}
    for old, new in reversed(journal['done']):
        source, target = root / old, root / new
        if not target.is_file():
            result['skipped'].append([old, 'the moved file is not at the new path'])
        elif source.exists():
            result['skipped'].append([old, 'something is at the old path'])
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(source))
            result['restored'].append(old)
    for name in sorted(journal['dirs'], key=len, reverse=True):
        try:
            (root / name).rmdir()
        except OSError:
            pass                                            # not empty: something else lives there, leave it
    return result


def summarize(done):
    """The high-level story of a Go, not file by file: '14 .md files -> .zygote/notes'. done: [[old, new]]. Biggest groups first."""
    counts = {}
    for old, new in done:
        folder = new.rsplit('/', 1)[0] if '/' in new else ''
        kind = PurePosixPath(old).suffix.lower() or 'files without extension'
        counts[(kind, folder)] = counts.get((kind, folder), 0) + 1
    lines = [f'{count} {kind} file{"s" if count != 1 else ""} -> {folder}' for (kind, folder), count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    return lines[:14] + ([f'and {len(lines) - 14} smaller groups'] if len(lines) > 14 else [])


def moved_word(word, moved):
    """One word of a command line: when it names a file that moved, the word for the new place (same quotes, same kind of slash). Else the word."""
    quote = word[0] if len(word) > 1 and word[0] == word[-1] and word[0] in '"\'' else ''
    bare = word.strip('"\'')
    key = bare.replace('\\', '/')
    key = key[2:] if key.startswith('./') else key
    if key not in moved:
        return word
    new = moved[key].replace('/', '\\') if '\\' in bare else moved[key]
    return f'{quote}{new}{quote}'


def move_arguments(text, moved):
    """The command line arguments with every path that moved changed to its new place (a word that names nothing that moved is left as it was)."""
    import shlex
    lexer = shlex.shlex(text or '', posix=False)
    lexer.whitespace_split = True
    return ' '.join(moved_word(word, moved) for word in lexer)


def move_entries(project, folder, done):
    """After a Go in the project's own folder: an entry point that moved is changed to its new place, and so is every path in the command line
    arguments that moved (a different entry point or argument is never touched). Returns {mode: {'entry': [old, new], 'args': [old, new]}} of what
    changed (for the undo); a mode that changed nothing is not in it."""
    if Path(folder).resolve() != Path(project).resolve():
        return {}
    moved = {old: new for old, new in done}
    changed = {}
    for mode in core.RUN_MODES:
        saved = core.run_settings(project, mode)
        entry = moved.get(saved['entry'], saved['entry'])
        args = move_arguments(saved['args'], moved)
        if entry != saved['entry'] or args != saved['args']:
            core.set_run_settings(project, mode, saved['runner'], entry, args)
            changed[mode] = {key: [before, after] for key, before, after in (('entry', saved['entry'], entry), ('args', saved['args'], args)) if before != after}
    return changed


def restore_entries(project, changed):
    for mode, parts in changed.items():
        saved = core.run_settings(project, mode)
        entry = parts['entry'][0] if 'entry' in parts and saved['entry'] == parts['entry'][1] else saved['entry']
        args = parts['args'][0] if 'args' in parts and saved['args'] == parts['args'][1] else saved['args']
        core.set_run_settings(project, mode, saved['runner'], entry, args)


JOURNAL_KEY = 'starter_undo'                                # the last Go, kept in the project's record so Undo works after a restart


def read_journal(project):
    return core.load_state(project).get(JOURNAL_KEY)


def write_journal(project, journal):
    state = core.load_state(project)
    if journal is None:
        state.pop(JOURNAL_KEY, None)
    else:
        state[JOURNAL_KEY] = journal
    core.save_state(project, state)


def undo_last(project):
    """Put back everything the last Go did (files, their new folders, the entry point). Returns undo()'s result, or None when there is nothing to undo."""
    journal = read_journal(project)
    if journal is None:
        return None
    result = undo(journal['folder'], journal)
    restore_entries(project, journal.get('entries', {}))
    write_journal(project, None)
    return result
