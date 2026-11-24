"""Zygote core: everything the window does that is not drawing. Standard library only (the shortcut needs pywin32), so it
is fully testable.

Jobs: read a project's version and remember when it changed; take in a dropped build ZIP (with an undo snapshot);
make a ZIP of the project; keep the project's name; rename its folder; stamp a shortcut; hand a file to Windows.
Every failure raises ZygoteError with a plain message; nothing is recovered silently.
"""
import colorsys
import datetime
import json
import os
import random
import ctypes
import re
import filecmp
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath

# Z 2.0: a project is its own code (app\), its made ZIPs (zip\), START_HERE.md, and a hidden .zygote\ folder that holds
# everything else Zygote keeps for it. .zygote is to Zygote what .git is to Git: the structure is fixed, the content is the project's.
DOT = '.zygote'
# Z 2.15: what is NOT machine state lives in the app tree, next to app: architecture, assets, bat, help, language, notes, setup, tests, tools, utils. It changes
# slower than the code and belongs to the project. .zygote keeps only the machine's side (bin, config, core, credentials, env, logs, user and the version).
TREE = 'app_tree'
TREE_FOLDERS = ('architecture', 'assets', 'bat', 'help', 'language', 'notes', 'setup', 'tests', 'tools', 'utils')


def zpath(root, *parts):
    """The ONE place that knows where a Zygote folder lives: <root>/app_tree/<name> for the app-tree folders, else <root>/.zygote/<name> .
    `root` is a project or Zygote's own folder; `parts` begin with the folder's name (a '/' inside a part is fine)."""
    names = [name for part in parts for name in str(part).replace('\\', '/').split('/') if name]
    base = TREE if names and names[0] in TREE_FOLDERS else DOT
    return Path(root) / base / Path(*names) if names else Path(root) / base


def zrel(*parts):
    """The same place as a path relative to the project, with forward slashes ('app_tree/bat/COMMIT.bat')."""
    return zpath('', *parts).as_posix().lstrip('/')
# These paths (relative to the project, with forward slashes) belong to the machine, not to a build. A build ZIP never writes
# into them and a project ZIP leaves them out (the user and credentials folders only on request).
SACRED = ('.git', 'zip', '.zygote/user', '.zygote/credentials', '.zygote/logs', '.zygote/env')
PRIVATE = ('.zygote/user', '.zygote/credentials')       # the ones a person may deliberately carry to another machine
NEVER_ZIPPED = ('.git', 'zip', 'deploy', '.zygote/logs', '.zygote/env', 'app_tree/tools/c/build')    # (__pycache__ is left out wherever it is)
ZYGOTE_ROOT = Path(__file__).resolve().parents[2]
ICON_FILE = zpath(ZYGOTE_ROOT, 'assets', 'icons', 'zygote.ico')
SOURCE_ICON = zpath(ZYGOTE_ROOT, 'assets', 'icons', 'source.png')            # the picture of the app folder (the main code); data: replace the file to change it
BRICKS_ICON = zpath(ZYGOTE_ROOT, 'assets', 'icons', 'bricks.png')            # the picture of the Libs folder (coloured bricks: the core modules a program is built from)
EXTRAS_ICON = zpath(ZYGOTE_ROOT, 'assets', 'icons', 'extras.png')            # the picture of the extras folder (the falling blocks)
START_HERE_ICON = zpath(ZYGOTE_ROOT, 'assets', 'icons', 'start_here.png')    # the picture of START_HERE.md (a brain over a book, blue, see-through)
DEPLOY_ICON = zpath(ZYGOTE_ROOT, 'assets', 'icons', 'deploy.png')            # the picture of the deploy folder (the rocket; see functional/deploy.py)
APP_TREE_ICON = zpath(ZYGOTE_ROOT, 'assets', 'icons', 'app_tree.png')      # the picture of the app_tree folder in the Workbench (data: replace the file to change it)
UI_PICTURES = zpath(ZYGOTE_ROOT, 'assets', 'ui')            # the pictures of Zygote's own buttons and rows (recycle_bin.png, up_folder.png): swap the file, no rebuild
NOTEPAD = 'notepad.exe'                      # "Open as text" always uses Notepad
VERSION_PLACES = ('.zygote/VERSION.txt', 'VERSION.txt')   # a folder from before Z 2.0 (or a foreign one) keeps it at the root; both are read


class ZygoteError(Exception):
    pass


class LockedFiles(ZygoteError):
    """An update could not start because files it replaces are in use or read-only; `.files` names them (the message says what to do)."""

    def __init__(self, message, files):
        super().__init__(message)
        self.files = list(files)


def under(rel, folder):
    """True when the relative path `rel` is `folder` itself or lies inside it (case-insensitive, like Windows)."""
    rel, folder = rel.lower(), folder.lower()
    return rel == folder or rel.startswith(folder + '/')


def is_sacred(rel):
    return any(under(rel, name) for name in SACRED)


def is_nested_git(rel):
    """True for a .git at any depth below the top (a nested repo or a submodule's pointer file): repo machinery of this computer, never written by a drop."""
    parts = rel.split('/')
    return '.git' in parts[:-1] or (len(parts) > 1 and parts[-1] == '.git')


# The project's own copy of Zygote and its settings: blue like the sacred folders (shown first, never copied, renamed or thrown away), but a build ZIP may still
# write into them (only Update writes the core; nothing else is blocked).
FROZEN = ('.zygote/core', '.zygote/config', '.zygote/bin')


def is_protected_file(rel):
    """True for a blue FILE at the project's top (START_HERE.md): shown with the blue folders, cannot be thrown away, but a build ZIP may replace it."""
    return bool(rel) and rel.lower() in [name.lower() for name in PROTECTED_FILES]


def is_blue(rel):
    """True for a path shown in blue: the sacred ones, the frozen ones, and the .zygote folder itself (it holds only blue things and Zygote's two version files)."""
    return rel == DOT or is_sacred(rel) or any(under(rel, name) for name in FROZEN)


def now():
    return datetime.datetime.now().astimezone()


# ---- the project's own record: TWO files. What belongs to the PROJECT travels with it (.zygote\config\project.json: name, icon, run settings, entry point, look, deploy settings,
# the agents' saved prompts). What belongs to THIS COMPUTER stays out of every ZIP (.zygote\user\zygote.json: window place, zoom, layout, shells, console choice, git program...).
# One rule: files in user never travel, files in config always do.
PROJECT_KEYS = ('name', 'icon', 'run', 'entry', 'theme', 'outer_color', 'deploy', 'ai_prompts', 'license')


def state_path(project):
    """The computer's own record of the project (never in a ZIP)."""
    return Path(project) / DOT / 'user' / 'zygote.json'


def project_state_path(project):
    """The record that travels with the project (in every ZIP)."""
    return Path(project) / DOT / 'config' / 'project.json'


def read_record(path):
    if not path.is_file():
        return {}
    try:
        found = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise ZygoteError(f'{path} is not readable ({error}). Fix or remove it.') from error
    if not isinstance(found, dict):
        raise ZygoteError(f'{path} must hold one JSON object.')
    return found


def load_state(project):
    """Both records as one. An older project still keeps its project keys in the computer's file: they are read from there until the next save moves them (the project's own file wins)."""
    state = read_record(state_path(project))
    state.update(read_record(project_state_path(project)))
    return state


def save_state(project, state):
    """The project's keys go to the file that travels, the rest to the computer's file; a project key left over in the computer's file is removed (moved, not copied)."""
    mine = {key: value for key, value in state.items() if key in PROJECT_KEYS}
    ours = {key: value for key, value in state.items() if key not in PROJECT_KEYS}
    path, travelling = state_path(project), project_state_path(project)
    if mine or travelling.is_file():
        travelling.parent.mkdir(parents=True, exist_ok=True)
        travelling.write_text(json.dumps(mine, indent=2) + '\n', encoding='utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ours, indent=2) + '\n', encoding='utf-8')


def run_settings_missing(project):
    """The sentence to say when a project has code in app\\ and no run settings saved at all (a project rebuilt from a copy that lost them), else ''. Zygote itself is exempt."""
    project = Path(project)
    state = load_state(project)
    if clean_path(project) == ZYGOTE_ROOT or state.get('run') or state.get('entry') or not any(project.glob('app/*.py')):
        return ''
    return ('Run settings missing: this project has code in app\\ but no runner or entry point is saved. Open Project > Settings… > Run and choose them '
            '(they are kept in .zygote\\config\\project.json and travel with the project).')


def settings_path():
    return ZYGOTE_ROOT / DOT / 'user' / 'settings.json'


def load_settings():
    """This computer's own settings for Zygote (kept in Zygote's .zygote\\user\\ folder, which no build ZIP touches)."""
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise ZygoteError(f'{path} is damaged ({error}). Fix or delete it.') from error


def save_setting(key, value):
    settings = load_settings()
    settings[key] = value
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')


def is_known_project(folder):
    """True when Zygote has already recorded a confirmed name for this folder (its record holds a name)."""
    return bool(load_state(folder).get('name'))


def project_name(project):
    return load_state(project).get('name') or Path(project).name


def set_project_name(project, name):
    name = name.strip()
    if not name:
        raise ZygoteError('The project name is empty.')
    state = load_state(project)
    state['name'] = name
    save_state(project, state)


def read_version(project):
    """First line of VERSION.txt, or None when the project has none (the window then shows "?")."""
    path = next((Path(project) / rel for rel in VERSION_PLACES if (Path(project) / rel).is_file()), None)
    if path is None:
        return None
    lines = path.read_text(encoding='utf-8').strip().splitlines()
    return lines[0].strip() if lines else None


def track_version(project):
    """The current version and the moment Zygote first saw it. The moment is recorded inside the record when the
    version differs from the one recorded last time (never read from a file's modified time). (None, None) if no version."""
    version = read_version(project)
    state = load_state(project)
    if version is not None and state.get('version') != version:
        state['version'] = version
        state['version_since'] = now().isoformat(timespec='seconds')
        save_state(project, state)
    return version, state.get('version_since') if version is not None else None


def version_direction(before, after):
    """'forward', 'back' or 'changed' for two versions like Z_1.1.3 and Z_1.1.4 (compared by their numbers)."""
    one, two = (tuple(int(n) for n in re.findall(r'\d+', v or '')) for v in (before, after))
    if not one or not two or one == two:
        return 'changed'
    return 'forward' if two > one else 'back'


# ---- assets: a dropped file of a known type goes to its own folder under .zygote\assets ---------------------------------------------------
ASSET_FOLDERS = {'.ico': 'icons', '.png': 'icons', '.icns': 'icons'}       # file type -> its folder in .zygote\assets (icons are the first type; more are added here)


def asset_folder(path):
    """The folder name under .zygote\assets for a dropped file, or None when its type is not an asset type Zygote knows."""
    return ASSET_FOLDERS.get(Path(path).suffix.lower())


def asset_destination(project, path):
    """Where a dropped asset would be copied: <project>\\app_tree\\assets\\<its folder>\\<its name>. Raises for a type that has no folder."""
    folder = asset_folder(path)
    if folder is None:
        raise ZygoteError(f'{Path(path).name}: Zygote takes a ZIP (a build) or an asset of these types: {", ".join(sorted(ASSET_FOLDERS))}.')
    return zpath(clean_path(project), 'assets', folder, Path(path).name)


def add_asset(project, path):
    """Copy a dropped file into its asset folder. The caller has already asked about an existing file of that name. Returns the new path."""
    path = Path(path)
    if not path.is_file():
        raise ZygoteError(f'{path} is not a file.')
    dest = asset_destination(project, path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)
    return dest


def own_code_changed(project, rels):
    """True when the project is this very Zygote and any of the files touched lives under app\\ (Zygote runs old code until restarted)."""
    return Path(project).resolve() == ZYGOTE_ROOT and any(rel.startswith('app/') for rel in rels)


def version_name(version):
    """The part before the last underscore: Z_1.0.0 -> Z."""
    return version.rsplit('_', 1)[0] if version and '_' in version else version


def has_git(folder):
    return (Path(folder) / '.git').exists()


def clean_path(path):
    """The absolute path with every '.' and '..' folded away (RUN.bat hands over ...\\app_tree\\bat\\..\\.., which must read as the project folder).
    Symbolic links and mapped drives are left as they are (Path.resolve would turn R: into a network name)."""
    return Path(os.path.normpath(os.path.abspath(str(path))))


# ---- renaming a project folder ---------------------------------------------------------------------------------
def check_folder_name(name):
    if not name or name != name.strip() or name.endswith('.') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
        raise ZygoteError(f'"{name}" cannot be a folder name on Windows (no < > : " / \\ | ? *, no dot or space at the end).')


def check_project_name(name, rename):
    """The one check of a project name (and, when the folder is renamed too, of the folder name). Raises ZygoteError."""
    if not name:
        raise ZygoteError('Give the project a name.')
    if rename:
        check_folder_name(name)


def notify_shell(folder):
    """Tell Windows that a folder changed, so icon marks (TortoiseGit) are asked for again. An API call in this process, not a new process.
    Returns False where there is no Windows shell (nothing to tell)."""
    if not hasattr(ctypes, 'windll'):
        return False
    ctypes.windll.shell32.SHChangeNotify(0x00001000, 0x0005, os.path.normpath(str(folder)), None)       # SHCNE_UPDATEDIR, SHCNF_PATHW
    return True


def rename_folder(project, new_name):
    """Rename the project's folder (same parent). Returns the new path. The caller releases anything holding the folder."""
    project = Path(project)
    check_folder_name(new_name)
    target = project.with_name(new_name)
    if target == project:
        return project
    if target.exists():
        raise ZygoteError(f'A folder named "{new_name}" already exists next to {project.name}.')
    try:
        project.rename(target)
    except OSError as error:
        raise ZygoteError(f'Windows would not rename {project} to "{new_name}": {error}') from error
    return target


# ---- build ZIPs ------------------------------------------------------------------------------------------------
def inspect_zip(zip_path):
    """Check a dropped ZIP and say what it would do. Writes nothing.

    Returns {'version', 'strip', 'write': [(member, relative path)], 'skipped': [relative path]}.
    A build ZIP carries VERSION.txt at its root, or inside one single top folder (which is then stripped).
    """
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise ZygoteError(f'Not a ZIP file: {zip_path.name}')
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            raise ZygoteError(f'{zip_path.name} is damaged (first bad entry: {bad})')
        members = [i for i in zf.infolist() if not i.is_dir()]
        for info in members:
            parts = PurePosixPath(info.filename.replace('\\', '/')).parts
            if info.filename.startswith(('/', '\\')) or '..' in parts or (parts and ':' in parts[0]):
                raise ZygoteError(f'{zip_path.name} holds an unsafe path: {info.filename}')
        names = [i.filename.replace('\\', '/') for i in members]
        if any(place in names for place in VERSION_PLACES):
            strip = ''
        else:
            tops = {n.split('/', 1)[0] for n in names if '/' in n}
            if len(tops) != 1 or any('/' not in n for n in names) or not any(f'{next(iter(tops))}/{place}' in names for place in VERSION_PLACES):
                raise ZygoteError(f'{zip_path.name} is not a build ZIP: it has no VERSION.txt at its root (or in .zygote\\).')
            strip = next(iter(tops)) + '/'
        member = next(strip + place for place in VERSION_PLACES if strip + place in names)
        version = zf.read(member).decode('utf-8').strip().splitlines()
        if not version:
            raise ZygoteError(f'{zip_path.name}: VERSION.txt is empty')
        write, skipped = [], []
        for info in members:
            rel = info.filename.replace('\\', '/')[len(strip):]
            if is_sacred(rel) or is_nested_git(rel):
                skipped.append(rel)
            else:
                write.append((info.filename, rel))
    return {'version': version[0].strip(), 'strip': strip, 'write': write, 'skipped': skipped, 'names': [rel for _member, rel in write] + skipped}


# ---- the drop guard: a dropped build must be an update of THIS project (no mixing of projects) ----------------------------------------
ZYGOTE_SHAPE = ('app/ui_ux/main_window.py', 'app/bootstrap.py')           # files only Zygote's own program has (its build ZIPs carry them)


def plain_name(name):
    """A project name with case and punctuation taken away (VFLOW_ and VFlow both give vflow)."""
    return re.sub(r'[^a-z0-9]', '', (name or '').casefold())


def same_name(one, two):
    """True when two project names are the same name: case and punctuation do not count (VFLOW_ and VFlow are the same project)."""
    return bool(plain_name(one)) and plain_name(one) == plain_name(two)


def is_zygote_build(plan):
    """True when a ZIP's files are Zygote's own program (a build of Zygote), whatever its version says."""
    return any(shape in plan['names'] for shape in ZYGOTE_SHAPE)


def is_zygote_project(project):
    """True when the project folder is Zygote's own program (the installed one, or a copy of it)."""
    return any((Path(project) / shape).is_file() for shape in ZYGOTE_SHAPE)


def project_names(project):
    """The names this project goes by: the part before the number of its current version, the name in its record and its folder name."""
    version = read_version(project)
    return [name for name in (version_name(version) if version else None, load_state(project).get('name'), Path(project).name) if name]


def check_drop(project, plan):
    """Judge a dropped build before anything is unpacked. Returns {'verdict': 'refuse' | 'back' | 'unknown' | 'ok', 'text': words for the person}.
    refuse  = it is not an update of this project (another project's build, or Zygote's own program dropped on a project): never unpacked
    back    = the same project but an older version: asked first (the answer is No unless the person says Yes)
    unknown = the project has no version yet and the ZIP does not carry its name: asked first
    ok      = the same project, a newer (or the same) version."""
    new, old = plan['version'], read_version(project)
    mine = project_names(project)
    heading = "This project does not look like an update to what you're working on."
    if is_zygote_build(plan) and not is_zygote_project(project):
        return {'verdict': 'refuse', 'text': "This is Zygote itself, not an update of this project: start the new Zygote, then use File > Update project's Zygote…"}
    name = version_name(new)
    if any(same_name(name, known) for known in mine):
        if old and version_direction(old, new) == 'back':
            return {'verdict': 'back', 'text': f'This ZIP is OLDER.\n\nZIP: {new}\nPROJECT NOW: {old}\n\nUnpacking it goes BACK to the older version. Unpack it over the project anyway? '
                                                   '(Project > Revert project… can undo it afterwards.)'}
        return {'verdict': 'ok', 'text': ''}
    if old is None and not any(known for known in mine if known != Path(project).name):
        return {'verdict': 'unknown', 'text': f'This project has no version yet, and {new} does not carry its name. Unpack it over the project anyway?'}
    return {'verdict': 'refuse', 'wrong_name': name, 'right': find_right_project(project, plan),
            'text': f'This is the wrong project.\n\nThe ZIP is {new}; the project open here is {old or Path(project).name} (it goes by: {", ".join(sorted(set(mine)))}). '
                    'Nothing was unpacked and nothing was changed.'}


def find_right_project(project, plan):
    """The folder of the project a refused ZIP belongs to, looked for BESIDE the open project (in the same parent folder): a folder named like the ZIP's project, or one
    with a .zygote folder whose project goes by that name. None when there is none. Nothing outside that one folder is searched."""
    name = version_name(plan['version'])
    here = clean_path(project)
    if not name or not here.parent.is_dir():
        return None
    for folder in sorted(here.parent.iterdir(), key=lambda one: one.name.lower()):
        if folder == here or not folder.is_dir() or not (folder / DOT).is_dir():
            continue
        if same_name(folder.name, name) or any(same_name(known, name) for known in project_names(folder)):
            return folder
    return None


def new_project_name(plan):
    """The folder name for a build ZIP opened as a new project: the project's name from its version (PARSER_PYTHON_0.1.5 gives PARSER_PYTHON). Raises for Zygote's own build."""
    if is_zygote_build(plan):
        raise ZygoteError("This is Zygote itself, not a project: start the new Zygote, then use File > Update project's Zygote…")
    name = version_name(plan['version'])
    check_item_name(name)
    return name


def unpack_new_project(zip_path, parent):
    """Open a build ZIP as a NEW project: a folder named after the project is made inside `parent` and the ZIP is unpacked there (the same files an update would write; the
    .git and sacred folders of the ZIP are left out, as in an update). A folder of that name that is already there is never deleted: it is moved beside it to
    NAME_old_<date>_<time>. Returns (new folder, moved old folder or None). When the unpacking fails the old folder is put back and the error says so."""
    parent = Path(parent)
    if not parent.is_dir():
        raise ZygoteError(f'The folder {parent} is not there.')
    plan = inspect_zip(zip_path)
    name = new_project_name(plan)
    dest = parent / name
    old = None
    if dest.exists():
        stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
        old = parent / f'{name}_old_{stamp}'
        if old.exists():
            raise ZygoteError(f'{old.name} is there already. Try again in a moment.')
        try:
            shutil.move(str(dest), str(old))
        except OSError as error:
            raise ZygoteError(f'The old {name} folder could not be moved aside ({error}). Close whatever uses it (a window, a program), then try again. Nothing was unpacked.') from error
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member, rel in plan['write']:
                target = dest.joinpath(*rel.split('/'))
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
    except OSError as error:
        shutil.rmtree(dest, ignore_errors=True)
        if old is not None:
            shutil.move(str(old), str(dest))
        raise ZygoteError(f'Windows refused to write {error.filename or "a file"} ({error.strerror or error}). The new folder was removed'
                          + (' and the old one is back where it was.' if old is not None else '.')) from error
    return dest, old


def protected_folders(skipped):
    """The sacred folders that a drop did not overwrite, in SACRED order (.git first)."""
    return [name for name in SACRED if any(under(rel, name) for rel in skipped)]


def locked_files(project, plan):
    """Existing files of the project that the ZIP wants to replace but cannot be opened for writing right now."""
    found = []
    for _member, rel in plan['write']:
        target = Path(project).joinpath(*rel.split('/'))
        if target.is_file():
            try:
                with open(target, 'r+b'):
                    pass
            except OSError:
                found.append(rel)
    return found


def zip_folder(project):
    """The project's zip folder: made ZIPs sit loose in it, drop snapshots in zip\\undo\\. Sacred: a drop never writes here."""
    return Path(project) / 'zip'


def snapshot_dir(project):
    return zip_folder(project) / 'undo'


SNAPSHOT_NAME = re.compile(r'^undo_(\d{4,})\.zip$')


def next_snapshot_name(project):
    folder = snapshot_dir(project)
    numbers = [int(m.group(1)) for m in (SNAPSHOT_NAME.match(p.name) for p in folder.glob('*.zip')) if m] if folder.is_dir() else []
    return f'undo_{max(numbers, default=0) + 1:04d}.zip'


def write_snapshot(project, plan, zip_path, before):
    """Save every file the drop is about to replace into zip\\undo\\undo_NNNN.zip, with manifest.json (what was replaced,
    what is new, the versions, when). Written before the first project file is touched. Returns the snapshot file name."""
    project = Path(project)
    replaced, created = [], []
    name = next_snapshot_name(project)
    snapshot_dir(project).mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(snapshot_dir(project) / name, 'w', zipfile.ZIP_DEFLATED) as zf:
        for _member, rel in plan['write']:
            target = project.joinpath(*rel.split('/'))
            if target.is_file():
                zf.write(target, 'files/' + rel)
                replaced.append(rel)
            else:
                created.append(rel)
        zf.writestr('manifest.json', json.dumps({
            'zip': Path(zip_path).name, 'version_before': before, 'version_after': plan['version'],
            'saved': now().isoformat(timespec='seconds'), 'replaced': replaced, 'created': created}, indent=2) + '\n')
    return name


def read_snapshot(path):
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
    manifest['name'] = Path(path).name
    return manifest


def list_snapshots(project):
    """The drop snapshots in the zip folder, newest first. A snapshot that cannot be read raises: nothing is skipped quietly."""
    folder = snapshot_dir(project)
    if not folder.is_dir():
        return []
    found = sorted((p for p in folder.glob('*.zip') if SNAPSHOT_NAME.match(p.name)), key=lambda p: p.name, reverse=True)
    return [read_snapshot(p) for p in found]


class HeldFiles(ZygoteError):
    """A ZIP carries files the person locked, and Zygote cannot tell by itself that the copy is a stale one. `files` = [{'rel', 'tracked'}]: tracked False = no fingerprint of the last received copy."""

    def __init__(self, text, files):
        super().__init__(text)
        self.files = files


# ---- Locks: files and folders the person works on can be locked so a dropped ZIP does not replace them. The lock list and the fingerprints of what the drops delivered are
# kept in THIS computer's record (.zygote\user\zygote.json: `holds`, `received`), never in a ZIP.
HOLDS_KEY, RECEIVED_KEY = 'holds', 'received'


def held_list(project):
    return list(load_state(project).get(HOLDS_KEY, []))


def held_covering(held, rel):
    """The locked entry (a file, or a folder above it) that covers this project-relative path, else ''."""
    for entry in held:
        if rel == entry or rel.startswith(entry + '/'):
            return entry
    return ''


def can_hold(project, path):
    """Only what the person works on can be locked (green files and folders); never the project, app_tree itself, or anything of Zygote's own structure (yellow ones included)."""
    return bool(project_relative(project, path)) and is_working(project, path) and not is_yellow(project, path) and not is_app_tree(project, path)


def hold(project, path):
    """Lock a file or folder. Returns its project-relative path."""
    if not can_hold(project, path):
        raise ZygoteError(f'{Path(path).name} cannot be locked: only the files and folders you work on can (not Zygote\'s own, nor the project or app_tree themselves).')
    rel = project_relative(project, path)
    state = load_state(project)
    held = list(state.get(HOLDS_KEY, []))
    if rel not in held:
        held.append(rel)
    state[HOLDS_KEY] = sorted(held)
    save_state(project, state)
    return rel


def release(project, path):
    """Unlock what was locked itself. An item that is only inside a locked folder is unlocked by unlocking that folder (the error says which)."""
    rel = project_relative(project, path)
    state = load_state(project)
    held = list(state.get(HOLDS_KEY, []))
    if rel not in held:
        above = held_covering(held, rel)
        raise ZygoteError(f'{Path(path).name} is locked by the folder {above}: unlock that folder.' if above else f'{Path(path).name} is not locked.')
    held.remove(rel)
    state[HOLDS_KEY] = held
    save_state(project, state)
    return rel


def zip_fingerprints(zip_path, plan):
    """{relative path: 'crc-size'} of the files of a ZIP, read from its directory (no file is read). It only has to tell two copies of one file apart."""
    members = dict(plan['write'])
    with zipfile.ZipFile(zip_path) as zf:
        return {members[info.filename]: f'{info.CRC:08x}-{info.file_size}' for info in zf.infolist() if info.filename in members}


def forget_received(project, rels):
    state = load_state(project)
    got = dict(state.get(RECEIVED_KEY, {}))
    for rel in rels:
        got.pop(rel, None)
    state[RECEIVED_KEY] = got
    save_state(project, state)


def judge_holds(project, plan, zip_path):
    """What the drop may do with the files the person locked. Returns (kept, asked, writable):
    kept = locked files the ZIP carries as the stale copy it delivered before (not copied, nothing asked); asked = [{'rel', 'tracked'}] a locked file whose copy differs
    from the last one received, or with no fingerprint yet; writable = the plan's write list without the kept and the asked ones. A file that is not there yet,
    or whose bytes already match, is not touched by the lock."""
    state = load_state(project)
    held, got = state.get(HOLDS_KEY, []), state.get(RECEIVED_KEY, {})
    if not held:
        return [], [], list(plan['write'])
    fingerprints = zip_fingerprints(zip_path, plan)
    kept, asked, writable = [], [], []
    with zipfile.ZipFile(zip_path) as zf:
        for member, rel in plan['write']:
            target = Path(project).joinpath(*rel.split('/'))
            if not held_covering(held, rel) or not target.is_file():
                writable.append((member, rel))
            elif zf.read(member) == target.read_bytes():
                continue                                            # the same bytes: nothing to protect, nothing to write
            elif got.get(rel) == fingerprints[rel]:
                kept.append(rel)
            else:
                asked.append({'rel': rel, 'tracked': rel in got})
    return kept, asked, writable


CORE_REL = '.zygote/core'


def version_key(text):
    """The numbers of a version text as a tuple (Z_2.19.33 -> (2, 19, 33)), or None when it has none."""
    numbers = re.findall(r'\d+', text or '')
    return tuple(int(number) for number in numbers) if numbers else None


def guard_core(project, plan, zip_path):
    """A dropped ZIP never rolls the project's core back. Both versions come from the VERSION.txt inside each core (.zygote\\core). A ZIP core that is the same or newer goes in as
    before; one that is older, or whose version is missing or unreadable, is NOT written: the project keeps its own core. Returns (plan without those core files, note) where note is
    None (nothing to say) or {'zip': text or None, 'project': text, 'reason': 'older' | 'unreadable'}."""
    members = [(member, rel) for member, rel in plan['write'] if under(rel, CORE_REL)]
    mine = core_version(project)
    if not members or mine is None:
        return plan, None                                                    # no core in the ZIP, or the project has none yet: nothing to guard
    theirs = None
    for member, rel in members:
        if rel == CORE_REL + '/VERSION.txt':
            with zipfile.ZipFile(zip_path) as zf:
                theirs = zf.read(member).decode('utf-8', 'replace').strip()
    ours, other = version_key(mine), version_key(theirs)
    if other is not None and ours is not None and other >= ours:
        return plan, None
    reason = 'older' if other is not None and ours is not None else 'unreadable'
    kept = [(member, rel) for member, rel in plan['write'] if not under(rel, CORE_REL)]
    return dict(plan, write=kept, skipped=plan['skipped'] + [rel for _member, rel in members]), {'zip': theirs, 'project': mine, 'reason': reason}


def core_guard_sentence(note):
    """The one sentence the toast, the Log and the history all say when a drop's core was not taken."""
    if note['reason'] == 'older':
        return (f'This ZIP carries an old core ({note["zip"]}). Your project\'s core ({note["project"]}) was kept. '
                'Make ZIP and hand it back, so the next ZIP carries the new core.')
    return (f'This ZIP carries a core whose version could not be read ({note["zip"] or "no VERSION.txt"}). Your project\'s core ({note["project"]}) was kept. '
            'Make ZIP and hand it back, so the next ZIP carries a core that can be read.')


def install_zip(zip_path, project, allow=None):
    """Unpack a build ZIP over the project, replacing files in place. Sacred folders are never touched.

    Before the first file is written, every file about to be replaced is saved in a new snapshot in zip\\undo\\ (every drop
    keeps its own; none is deleted). revert_project() reads them back.

    Locked files are not replaced. `allow` = the locked files the person ticked to be replaced this once (None = nobody was asked yet: a locked file the ZIP
    really changes, or one with no fingerprint, raises HeldFiles so the caller can ask)."""
    project = Path(project)
    if not project.is_dir():
        raise ZygoteError(f'Project folder not found: {project}')
    plan = inspect_zip(zip_path)                       # everything is checked before anything is touched
    judged = check_drop(project, plan)
    if judged['verdict'] == 'refuse':
        raise ZygoteError(judged['text'])                # the guard sits here too, so no caller can unpack another project's build
    plan, core_note = guard_core(project, plan, zip_path)          # the core only moves forward: an older one in the ZIP is not written
    kept, asked, writable = judge_holds(project, plan, zip_path)
    if asked and allow is None:
        raise HeldFiles('These locked files are in the ZIP with a copy that is not the stale one (or Zygote has no fingerprint of the last copy):\n  ' +
                        '\n  '.join(one['rel'] for one in asked), asked)
    allowed = set(allow or ())
    overridden = [one['rel'] for one in asked if one['rel'] in allowed]
    kept = kept + [one['rel'] for one in asked if one['rel'] not in allowed]
    fingerprints = zip_fingerprints(zip_path, plan)
    everything = plan['write']
    plan = dict(plan, write=writable + [(m, r) for m, r in everything if r in overridden])
    locked = locked_files(project, plan)
    if locked:
        raise LockedFiles('These files are in use (or read-only) and cannot be replaced:\n  ' + '\n  '.join(locked) +
                          '\nClose whatever is using them (if it is Zygote itself, close Zygote and start it again), then drop the ZIP again.'
                          '\nNothing was changed.', locked)
    before = read_version(project)
    snapshot = write_snapshot(project, plan, zip_path, before)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member, rel in plan['write']:
                target = project.joinpath(*rel.split('/'))
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
    except OSError as error:                           # the pre-check missed one: put everything back, then say so
        revert_project(project, snapshot)
        raise ZygoteError(f'Windows refused to write {error.filename or "a file"} ({error.strerror or error}). '
                          'Everything was put back as it was. Close whatever uses that file, then drop the ZIP again.') from error
    state = load_state(project)                          # what this drop delivered, for the next one (all files: a file locked later already has its fingerprint)
    state[RECEIVED_KEY] = dict(state.get(RECEIVED_KEY, {}), **fingerprints)
    save_state(project, state)
    own_code = own_code_changed(project, [rel for _member, rel in plan['write']])
    return {'before': before, 'after': read_version(project), 'written': len(plan['write']), 'skipped': plan['skipped'],
            'restart_needed': own_code, 'snapshot': snapshot, 'files': [rel for _member, rel in plan['write']], 'kept': kept, 'overridden': overridden,
            'core_kept': core_note}


def remove_empty_parents(project, target):
    """After a file the drop made was removed: the folders above it that are now empty go too (only empty ones, never the project folder).
    A folder with anything in it, even one file, stays."""
    folder = Path(target).parent
    root = Path(project)
    while folder != root and root in folder.parents and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent


def revert_project(project, snapshot_name):
    """Put the project back as it was before the chosen drop. That undoes the chosen drop and every drop after it
    (newest first); their snapshots are used up. Older snapshots stay. Everything is checked before the first file changes."""
    project = Path(project)
    chosen = SNAPSHOT_NAME.match(snapshot_name)
    if not chosen:
        raise ZygoteError(f'Not a snapshot name: {snapshot_name}')
    wanted = [m for m in list_snapshots(project) if int(SNAPSHOT_NAME.match(m['name']).group(1)) >= int(chosen.group(1))]
    if not wanted or wanted[-1]['name'] != snapshot_name:
        raise ZygoteError(f'Snapshot {snapshot_name} was not found in {snapshot_dir(project)}. Nothing was changed.')
    for manifest in wanted:                            # newest first; check that every file is really in its snapshot
        with zipfile.ZipFile(snapshot_dir(project) / manifest['name']) as zf:
            have = set(zf.namelist())
        for rel in manifest['replaced']:
            if 'files/' + rel not in have:
                raise ZygoteError(f'Snapshot {manifest["name"]} is missing {rel}; nothing was changed.')
    restored, removed, touched = 0, 0, []
    for manifest in wanted:
        with zipfile.ZipFile(snapshot_dir(project) / manifest['name']) as zf:
            for rel in manifest['replaced']:
                target = project.joinpath(*rel.split('/'))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read('files/' + rel))
                restored += 1
        for rel in manifest['created']:
            target = project.joinpath(*rel.split('/'))
            if target.is_file():
                target.unlink()
                removed += 1
            remove_empty_parents(project, target)
        touched += manifest['replaced'] + manifest['created']
    forget_received(project, touched)                  # what those drops delivered is no longer what the project holds: a locked copy is asked about again
    for manifest in wanted:
        (snapshot_dir(project) / manifest['name']).unlink()
    if snapshot_dir(project).is_dir() and not any(snapshot_dir(project).iterdir()):
        snapshot_dir(project).rmdir()                  # the undo folder the drops made, empty now (the zip folder itself stays)
    return {'zips': [m['zip'] for m in wanted], 'drops': len(wanted), 'restored': restored, 'removed': removed,
            'version_before': wanted[-1]['version_before'], 'version_after': wanted[0]['version_after'],
            'restart_needed': own_code_changed(project, touched)}


def made_zip_path(project, include_private=False, include_user=None, include_credentials=None, now=None):
    """Where Make ZIP writes: zip\\<VERSION>.zip, named exactly as VERSION.txt (plus _WITH_PRIVATE when .zygote\\user or .zygote\\credentials goes in).
    Any project other than Zygote itself is named <project>_<MM-DD-HHMM>_<VERSION>.zip (VFlow_11-15-1033_Z_2.14.1.zip), so a ZIP says whose it is and when it was made.
    include_private = both; include_user / include_credentials choose each on its own. `now` is the clock (a test gives its own)."""
    include_user, include_credentials = private_choice(include_private, include_user, include_credentials)
    version = read_version(project)
    if not version:
        raise ZygoteError('This project has no version (VERSION.txt is missing or empty), so the ZIP cannot be named.')
    if Path(project).resolve() != ZYGOTE_ROOT:
        import datetime
        version = f'{project_name(project)}_{(now or datetime.datetime.now()).strftime("%m-%d-%H%M")}_{version}'
    return zip_folder(project) / (f'{version}_WITH_PRIVATE.zip' if include_user or include_credentials else f'{version}.zip')


def private_choice(include_private, include_user, include_credentials):
    """(user goes in, credentials go in): each box on its own, or both together by the older include_private."""
    return (include_private if include_user is None else include_user), (include_private if include_credentials is None else include_credentials)


def make_zip(project, dest, include_private=False, include_user=None, include_credentials=None, top=''):
    """ZIP the project's current state. The repo history, logs, environment and the zip folder are never included;
    .zygote\\user only when include_user (or include_private) is True, .zygote\\credentials only when include_credentials (or include_private) is True;
    shortcuts (.lnk) and the launcher (<project>_Zide.exe, and the older Launch Zygote.exe and Run project.exe) at the root are never included (they hold this computer's paths). `top` puts everything inside ONE
    folder of that name, so that extracting gives a single folder to drag out (a dropped ZIP strips it again). Returns the number of files."""
    include_user, include_credentials = private_choice(include_private, include_user, include_credentials)
    project, dest = Path(project), Path(dest).resolve()
    if not project.is_dir():
        raise ZygoteError(f'Project folder not found: {project}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    skip = list(NEVER_ZIPPED) + ([] if include_user else ['.zygote/user']) + ([] if include_credentials else ['.zygote/credentials'])
    count = 0
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
        for folder, dirs, files in os.walk(project):          # skipped folders are never entered (env\\ alone holds thousands of files)
            here = Path(folder).relative_to(project).as_posix()
            prefix = '' if here == '.' else here + '/'
            dirs[:] = sorted(d for d in dirs if d != '__pycache__' and not any(under(prefix + d, name) for name in skip))
            for name in sorted(files):
                path = Path(folder) / name
                if path.resolve() == dest or (not prefix and (name.lower().endswith('.lnk') or is_launcher_name(name))):
                    continue
                zf.write(path, (top + '/' if top else '') + prefix + name)
                count += 1
    return count


# ---- Windows handoffs ------------------------------------------------------------------------------------------
RUN_PLACES = ('app_tree/bat/RUN.bat', '.zygote/bat/RUN.bat', 'bat/RUN.bat', 'RUN.bat')     # Z 2.0 keeps it in .zygote\bat\; older folders have it in bat\ or at the root


def run_bat_in(folder):
    """The RUN.bat of a project folder, as a path relative to it (app_tree\\bat\\RUN.bat first)."""
    for rel in RUN_PLACES:
        if (Path(folder) / rel).is_file():
            return rel
    raise ZygoteError(f'No RUN.bat was found in {folder} (looked in app_tree\\bat\\, bat\\ and the root)')


def run_bat_path():
    """Zygote's own RUN.bat."""
    return ZYGOTE_ROOT / run_bat_in(ZYGOTE_ROOT)


def minimized_window():
    """Start-up information that opens a console minimized, so the batch file's window stays out of the way."""
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 7                                    # SW_SHOWMINNOACTIVE
    return info


UPDATED_SWITCH = '--updated'                        # the command line message "this start follows an update"


def is_legacy_layout(project):
    """True when the project still keeps the app-tree folders (assets, bat, notes ...) inside .zygote, the way Z 2.0 - 2.14 did. Zygote's own folder never is."""
    project = clean_path(project)
    return project != ZYGOTE_ROOT and any((project / DOT / name).is_dir() for name in TREE_FOLDERS)


def core_is_current(project):
    """True when the project's copy of Zygote, the Zygote on the disk and the Zygote running are all the same version, and the folders are where this Zygote
    keeps them: nothing to update."""
    return core_version(project) == installed_version() == RUNNING_VERSION and not is_legacy_layout(project)


def start_zygote(project, updated=False):
    """Start a Zygote window on a project through RUN.bat (so a changed requirements.txt is honored). One process per call, always from something the person did
    (Restart, a Yes to the update question, a project dropped on Zygote). The caller decides whether this Zygote closes after it.
    updated: adds the switch --updated, a message to the new Zygote (read once at its start, nothing is written to disk) so it says "Update complete".
    With the external console box ticked: `cmd.exe /k` in a visible console that stays open. Otherwise the batch file's window starts minimized and closes itself."""
    if not hasattr(subprocess, 'CREATE_NEW_CONSOLE'):
        raise ZygoteError('Starting a Zygote window needs Windows.')
    bat = str(run_bat_path())
    switch = [UPDATED_SWITCH] if updated else []
    if external_console(project):
        subprocess.Popen(['cmd.exe', '/k', bat, '--project', str(project)] + switch, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen([bat, '--project', str(project)] + switch, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=minimized_window())


def restart_zygote(project, updated=False):
    """Start a new Zygote on the same project; the caller closes this Zygote right after. Only ever called from a button (Restart, or Yes in the update question)."""
    start_zygote(project, updated)


def external_console(project):
    """Show external console output (sticky: kept on this computer in the project's .zygote\\user\\zygote.json). Off by default: every run goes to the
    Console tab inside Zygote. On: a run opens its own console window that stays open after the program ends. False when no project is open."""
    return bool(project) and bool(load_state(project).get('external_console', False))


def set_external_console(project, on):
    state = load_state(project)
    state['external_console'] = bool(on)
    save_state(project, state)


def ui_picture(name):
    """The path of one of Zygote's own pictures. Raises (loudly) when the file is missing."""
    path = UI_PICTURES / name
    if not path.is_file():
        raise ZygoteError(f'The picture {name} is missing from {UI_PICTURES}. Unpack the build ZIP again.')
    return path


EXTERNAL_TERMINALS = (('x-terminal-emulator', ['-e']), ('gnome-terminal', ['--']), ('konsole', ['-e']), ('xterm', ['-e']))     # Linux: the first one found


def external_console_command(words):
    """The words that open a console window for a program and keep it open after it ends: Windows `cmd.exe /k <program>`; Linux the system's
    terminal with a shell that waits for Enter. None when this system has no terminal Zygote knows."""
    if hasattr(subprocess, 'CREATE_NEW_CONSOLE'):
        return ['cmd.exe', '/k'] + [str(word) for word in words]
    import shlex
    for name, flag in EXTERNAL_TERMINALS:
        found = shutil.which(name)
        if found:
            wait = shlex.join(str(word) for word in words) + '; printf "\\nPress Enter to close "; read _'
            return [found] + flag + ['sh', '-c', wait]
    return None


def open_external_console(words, folder):
    """Start a program in an external console window that stays open (one process, from a button). Returns the command text, or None when
    there is no terminal to use (the caller then runs it in the Console tab)."""
    command = external_console_command(words)
    if command is None:
        return None
    flags = subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0
    subprocess.Popen(command, cwd=str(folder), creationflags=flags)
    return ' '.join(command)


def default_entry(project):
    """What Run starts when no entry point is typed: the project's own RUN.bat (path relative to the project), or '' when there is none or it is the placeholder."""
    try:
        rel = run_bat_in(project)
    except ZygoteError:
        return ''
    return '' if (Path(project) / rel).read_bytes() == (BASELINE / 'bat' / 'RUN.bat').read_bytes() else rel


LAYOUT_BARS = ('left', 'panes', 'rows')                 # the three drag bars of the window: between the trees, between trees and icons, above the bottom panel


def check_layout(layout):
    """The saved bar positions: {bar name: [two or more whole numbers, 0 or more]}. Raises ZygoteError for anything else (no silent default)."""
    if not isinstance(layout, dict):
        raise ZygoteError('The saved window layout is not a table of bar positions.')
    for name, sizes in layout.items():
        if name not in LAYOUT_BARS:
            raise ZygoteError(f'The saved window layout has an unknown bar: {name!r}.')
        if not (isinstance(sizes, list) and len(sizes) >= 2 and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in sizes)):
            raise ZygoteError(f'The saved position of the {name} bar is wrong: {sizes!r}.')
    return layout


def window_layout(project):
    """Where this project's drag bars were left (kept in the project's .zygote\\user\\zygote.json). {} when none were saved yet."""
    return check_layout(load_state(project).get('layout', {})) if project else {}


def set_window_layout(project, layout):
    """Remember the bar positions for this project. A project folder that is gone has nowhere to keep them: nothing is written."""
    check_layout(layout)
    if not Path(project).is_dir() or load_state(project).get('layout') == layout:
        return False
    state = load_state(project)
    state['layout'] = layout
    save_state(project, state)
    return True


WINDOW_KEYS = ('x', 'y', 'w', 'h')


def check_window(window):
    """The saved place of the window: {x, y, w, h: whole numbers (w, h > 0), maximized: true/false}. Raises ZygoteError for anything else."""
    if not (isinstance(window, dict) and set(window) == set(WINDOW_KEYS) | {'maximized'}):
        raise ZygoteError(f'The saved window place is wrong: {window!r}.')
    for key in WINDOW_KEYS:
        value = window[key]
        if not isinstance(value, int) or isinstance(value, bool) or (key in ('w', 'h') and value <= 0):
            raise ZygoteError(f'The saved window place has a wrong {key}: {value!r}.')
    if not isinstance(window['maximized'], bool):
        raise ZygoteError(f'The saved window place has a wrong maximized: {window["maximized"]!r}.')
    return window


def window_place(project):
    """Where this project's window was left (position, size, maximized), or None when it was never saved."""
    saved = load_state(project).get('window') if project else None
    return None if saved is None else check_window(saved)


ZOOM_PANELS = ('computer', 'tree', 'icons', 'details')


def zoom_levels(project):
    """The text size of each zoomable panel, as it was left ({} when none was kept). Raises when the record is not a size per panel."""
    found = load_state(project).get('zoom', {})
    if not isinstance(found, dict) or not all(key in ZOOM_PANELS and isinstance(size, (int, float)) and not isinstance(size, bool) and size > 0 for key, size in found.items()):
        raise ZygoteError(f'The zoom record in {state_path(project)} is not a text size for each of: {", ".join(ZOOM_PANELS)}.')
    return found


def set_zoom_levels(project, levels):
    """Keep the text size of each zoomable panel for this project. A project folder that is gone has nowhere to keep it: nothing is written."""
    if not Path(project).is_dir():
        return False
    state = load_state(project)
    if state.get('zoom') == levels:
        return False
    state['zoom'] = dict(levels)
    save_state(project, state)
    return True


def allow_adding(project):
    """Zygote's own switch: files may be added to Zygote itself by dropping them (off by default; kept on this computer)."""
    return bool(load_state(project).get('allow_adding', False))


def set_allow_adding(project, on):
    state = load_state(project)
    state['allow_adding'] = bool(on)
    save_state(project, state)


def set_window_place(project, window):
    """Remember the window place for this project. A project folder that is gone has nowhere to keep it: nothing is written."""
    check_window(window)
    if not Path(project).is_dir() or load_state(project).get('window') == window:
        return False
    state = load_state(project)
    state['window'] = window
    save_state(project, state)
    return True


# ---- Shell tabs (the Console panel: one tab per shell; names and colours are kept per project, the shells themselves never are) ------------
SHELL_LIMIT = 8
TAB_COLORS = (                                         # (background, text): a pair for each possible shell and one more (black), each readable (contrast >= 4.5)
    ('#2e7d32', '#ffffff'), ('#1565c0', '#ffffff'), ('#bf360c', '#ffffff'), ('#6a1b9a', '#ffffff'),
    ('#00695c', '#ffffff'), ('#f9a825', '#000000'), ('#c62828', '#ffffff'), ('#cfd8dc', '#000000'), ('#000000', '#ffffff'))
TAB_COLOR_NAMES = ('Green', 'Blue', 'Orange', 'Purple', 'Teal', 'Amber', 'Red', 'Grey', 'Black')


def relative_light(color):
    """How light a '#rrggbb' colour is, 0 (black) to 1 (white), by the WCAG formula."""
    parts = []
    for at in (1, 3, 5):
        value = int(color[at:at + 2], 16) / 255
        parts.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]


def contrast_ratio(first, second):
    """WCAG contrast of two '#rrggbb' colours: 1 (none) to 21 (black on white)."""
    high, low = sorted((relative_light(first), relative_light(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def next_tab_color(used):
    """The index of the first colour pair no open shell uses (the least used one when all eight are taken; black is only chosen by hand)."""
    counts = [list(used).count(at) for at in range(SHELL_LIMIT)]
    return counts.index(min(counts))


def check_shell_tabs(shells):
    """The saved shell tabs: a list of up to SHELL_LIMIT of {name: text, color: index of a colour pair}. Raises ZygoteError for anything else."""
    if not isinstance(shells, list) or len(shells) > SHELL_LIMIT:
        raise ZygoteError(f'The saved shell tabs are wrong: {shells!r}.')
    for shell in shells:
        if not (isinstance(shell, dict) and set(shell) == {'name', 'color'} and isinstance(shell['name'], str) and shell['name'].strip()
                and isinstance(shell['color'], int) and not isinstance(shell['color'], bool) and 0 <= shell['color'] < len(TAB_COLORS)):
            raise ZygoteError(f'A saved shell tab is wrong: {shell!r}.')
    return shells


def shell_tabs(project):
    """The shell tabs this project had when it was left (names and colours, in order). [] when there were none."""
    return check_shell_tabs(load_state(project).get('shells', [])) if project else []


def set_shell_tabs(project, shells):
    """Remember the shell tabs for this project. A project folder that is gone has nowhere to keep them: nothing is written."""
    check_shell_tabs(shells)
    if not Path(project).is_dir() or load_state(project).get('shells', []) == shells:
        return False
    state = load_state(project)
    state['shells'] = shells
    save_state(project, state)
    return True


def run_mode(project):
    """Which set of run settings Run uses: 'debug' or 'runtime' (chosen with the Debug / Runtime buttons of Project settings, kept per project).
    This is NOT the external console box: the two are separate settings."""
    mode = load_state(project).get('mode', 'runtime') if project else 'runtime'
    return check_mode(mode)


def set_run_mode(project, mode):
    state = load_state(project)
    state['mode'] = check_mode(mode)
    save_state(project, state)


def debug_command(path):
    """What Debug mode runs for a launcher: cmd.exe /k <the .bat>, so its window stays open after it ends and the output can be read."""
    return ['cmd.exe', '/k', str(path)]


def launch(project, name, debug=False):
    """Hand project\\<name> to Windows (a .bat opens its own console window; a folder opens in Explorer).
    One process per press of a button; Zygote does not track or stop it.
    With debug=True a .bat runs as `cmd.exe /k <bat>` in a new console, which stays open when the .bat ends. Returns the command text (debug) or None."""
    path = Path(project) / name
    if not path.exists():
        raise ZygoteError(f'{name} not found in {project}')
    if debug and path.suffix.lower() in ('.bat', '.cmd'):
        if not hasattr(subprocess, 'CREATE_NEW_CONSOLE'):
            raise ZygoteError('Debug mode starts launchers in a console window; that needs Windows.')
        command = debug_command(path)
        subprocess.Popen(command, cwd=str(project), creationflags=subprocess.CREATE_NEW_CONSOLE)
        return ' '.join(command)
    open_path(path)
    return None


def tool_version():
    """The version of the Zygote program that is running: first line of .zygote\\VERSION.txt in Zygote's own folder (never the open project's)."""
    path = ZYGOTE_ROOT / DOT / 'VERSION.txt'
    lines = path.read_text(encoding='utf-8').strip().splitlines() if path.is_file() else []
    return lines[0].strip() if lines else '?'


RUNNING_VERSION = tool_version()                    # the version this Zygote started with: its code is in memory, whatever the disk says now


def restart_pending():
    """True when the files on disk are another version than the program running (a new ZIP was dropped on Zygote while it runs)."""
    return tool_version() != RUNNING_VERSION


def running_title():
    """'Zygote Z_2.14.4', and when the disk holds another version: 'Zygote Z_2.14.4 (disk has Z_2.14.5: restart)'."""
    return f'Zygote {RUNNING_VERSION}' + (f' (disk has {tool_version()}: restart)' if restart_pending() else '')


def build_date():
    """When this build was made: the first line of .zygote\\BUILD.txt (written when the build is packed), or '?'. Read from the data, never from file dates."""
    path = ZYGOTE_ROOT / DOT / 'BUILD.txt'
    lines = path.read_text(encoding='utf-8').strip().splitlines() if path.is_file() else []
    return lines[0].strip() if lines else '?'


def file_manager_program():
    """The program that shows a folder on this system. The only place that knows which system this is."""
    if sys.platform == 'win32':
        return 'explorer.exe'
    if sys.platform == 'darwin':
        return 'open'
    if sys.platform.startswith('linux'):
        return 'xdg-open'
    raise ZygoteError(f'No file manager is known for the system {sys.platform}.')


def open_folder(folder):
    """Show a folder in the system's file manager. 1 process per call (the folder button, per press); Zygote does not wait for it."""
    if not folder or not Path(folder).is_dir():
        raise ZygoteError('No folder is shown yet. Click a folder first, then press the folder button.')
    subprocess.Popen([file_manager_program(), os.path.normpath(str(folder))])     # Explorer opens Documents when it is given C:/x/y (forward slashes)


def show_in_explorer(path):
    """Open an Explorer window on the file's folder with the file selected. 1 process per call (Make ZIP, per press)."""
    if not hasattr(subprocess, 'CREATE_NEW_CONSOLE'):
        raise ZygoteError(f'Showing {path} in Explorer needs Windows.')
    subprocess.Popen(['explorer.exe', f'/select,{path}'])


# ---- which program opens which kind of file (Settings > Tools; kept in this computer's settings) -------------------
TOOLS_DEFAULTS = zpath(ZYGOTE_ROOT, 'assets', 'tools_defaults.json')
WINDOWS_OWN = 'windows'                      # saved for a file type whose person chose "Windows' own choice" (so Zygote's default does not apply)
PROGRAM_FOLDERS = ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')


def file_extension(path):
    """The file type with its dot, lower case; a name that is only a dot-name (.gitignore) is a type itself."""
    name = Path(path).name.lower()
    if name.startswith('.') and name.count('.') == 1:
        return name
    return Path(path).suffix.lower()


def tool_groups():
    """The groups of Settings > Tools as written in assets/tools_defaults.json: [{'name', 'types', 'prefer', 'fallback'}]. A damaged file fails loud."""
    try:
        data = json.loads(Path(TOOLS_DEFAULTS).read_text(encoding='utf-8'))
        return [{'name': g['name'], 'types': [t.lower() for t in g['types']], 'prefer': g.get('prefer', ''), 'fallback': g.get('fallback', '')} for g in data['groups']]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ZygoteError(f'The tools defaults file cannot be read ({TOOLS_DEFAULTS}): {error}') from error


def split_types(text):
    """'.py, .md; .txt' -> ['.py', '.md', '.txt'] (commas, semicolons or spaces; a missing dot is added). Bad names fail loud."""
    types = []
    for word in re.split(r'[,;\s]+', text or ''):
        if word:
            word = word if word.startswith('.') else '.' + word
            if not re.fullmatch(r'\.[A-Za-z0-9_+-]+', word):
                raise ZygoteError(f'"{word}" is not a file type. Write it like .md or .txt')
            types.append(word.lower())
    return types


def find_program(name):
    """The full path of a program by its file name (notepad++.exe): the search path, then the usual program folders. None when it is not on this computer."""
    if Path(name).is_file():
        return str(name)
    found = shutil.which(name)
    if found:
        return found
    stem = Path(name).stem
    for variable in PROGRAM_FOLDERS:
        base = os.environ.get(variable)
        if base:
            for folder in sorted(Path(base).glob(f'{stem}*')) + sorted(Path(base).glob(f'Programs/{stem}*')):
                if (folder / name).is_file():
                    return str(folder / name)
    return None


def system_program(extension):
    """The program Windows has for a file type (its own file association, read in this process), else None."""
    if os.name != 'nt':
        return None
    size = ctypes.c_uint(520)
    buffer = ctypes.create_unicode_buffer(520)
    if ctypes.windll.shlwapi.AssocQueryStringW(0, 2, extension, None, buffer, ctypes.byref(size)) != 0:    # 2 = the executable
        return None
    return buffer.value or None


def registry_programs(extension):
    """The programs Windows lists as able to open a file type (its Open with list), as paths found on this computer. Empty off Windows."""
    if os.name != 'nt':
        return []
    import winreg
    found = []
    path = rf'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{extension}\OpenWithList'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            for index in range(winreg.QueryInfoKey(key)[1]):
                name, value, _ = winreg.EnumValue(key, index)
                if name != 'MRUList' and isinstance(value, str) and value.lower().endswith('.exe'):
                    program = find_program(value)
                    if program and program not in found:
                        found.append(program)
    except OSError:
        pass
    return found


def default_program(extension):
    """The program Zygote's defaults give a file type: the group's preferred program if it is on this computer, else the fallback, else None (Windows' own)."""
    for group in tool_groups():
        if extension in group['types']:
            for name in (group['prefer'], group['fallback']):
                found = find_program(name) if name else None
                if found:
                    return found
    return None


def program_for(path):
    """The program that opens this file: the person's choice, else Zygote's default for the type, else None (Windows' own)."""
    extension = file_extension(path) or '.txt'                 # a file with no file type (LICENSE) is text: it opens with the program chosen for .txt
    chosen = associations().get(extension)
    if chosen == WINDOWS_OWN:
        return None
    return chosen or default_program(extension)


def program_choices(extension):
    """The programs offered in the drop list of one file type: the defaults' programs, then Windows' own association and Open with list. No doubles."""
    choices = []
    for group in tool_groups():
        if extension in group['types']:
            for name in (group['prefer'], group['fallback']):
                found = find_program(name) if name else None
                if found:
                    choices.append(found)
    for found in [system_program(extension)] + registry_programs(extension):
        if found and found not in choices:
            choices.append(found)
    return choices


def associations():
    """{'.md': 'C:\\...\\Code.exe', ...}: the programs the person chose for file types. Others use Windows' own choice."""
    return dict(load_settings().get('tools', {}))


def check_association(extension, program):
    if not re.fullmatch(r'\.[A-Za-z0-9_+-]+', extension or ''):
        raise ZygoteError(f'"{extension}" is not a file type. Write it like .md or .txt')
    if program != WINDOWS_OWN and not Path(program).is_file():
        raise ZygoteError(f'The program was not found: {program}')


def save_associations(mapping):
    for extension, program in mapping.items():
        check_association(extension, program)
    save_setting('tools', dict(sorted(mapping.items())))


def set_association(extension, program):
    mapping = associations()
    mapping[extension.lower()] = program
    save_associations(mapping)


def remove_association(extension):
    mapping = associations()
    mapping.pop(extension.lower(), None)
    save_associations(mapping)


# ---- Command line tools (Tools menu): a name, a command with <file> and <folder>, and how it runs ---------------------------------------------------------------
DANGEROUS_COMMANDS = ('del', 'erase', 'rd', 'rmdir', 'move', 'ren', 'rename')       # a tool that starts with one of these may never touch a protected item
COMMAND_KEYS = ('name', 'command', 'console', 'keep_open')


def check_command_tool(tool):
    """One tool as it is saved: a name (it becomes a menu entry), a command, and the two ticks. A blank name or command is refused."""
    name, command = str(tool.get('name', '')).strip(), str(tool.get('command', '')).strip()
    if not name:
        raise ZygoteError('A command line tool needs a menu name.')
    if not command:
        raise ZygoteError(f'The tool "{name}" needs a command.')
    return {'name': name, 'command': command, 'console': bool(tool.get('console', True)), 'keep_open': bool(tool.get('keep_open', True))}


def command_tool_defaults():
    try:
        data = json.loads(Path(TOOLS_DEFAULTS).read_text(encoding='utf-8'))
        return [check_command_tool(one) for one in data['commands']]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ZygoteError(f'The tools defaults file cannot be read ({TOOLS_DEFAULTS}): {error}') from error


def command_tools():
    """The command line tools of this computer: what the person saved, else the starters (tree, dir) from the defaults file."""
    saved = load_settings().get('command_tools')
    return command_tool_defaults() if saved is None else [check_command_tool(one) for one in saved]


def save_command_tools(tools):
    checked = [check_command_tool(one) for one in tools]
    names = [one['name'].lower() for one in checked]
    for name in names:
        if names.count(name) > 1:
            raise ZygoteError(f'Two tools are called "{name}": every menu name is used once.')
    save_setting('command_tools', checked)
    return checked


def quoted_path(project, path):
    """A path as the command sees it: relative to the project root ('.' for the root itself), in the system's own slashes, in double quotes."""
    rel = project_relative(project, path)
    if rel is None:
        raise ZygoteError(f'{path} is outside the project: a tool works inside the project only.')
    text = rel.replace('/', os.sep) if rel else '.'
    return f'"{text}"' if re.search(r'[\s&()^%!;,=]', text) else text          # quotes only where the command line needs them (a plain relative path is safest bare)


def command_tool_line(project, command, file='', folder=''):
    """The command with <file> and <folder> filled in. <file> with no selected file: "select a file first". <folder> with no folder in view: the project root."""
    line = command
    if '<file>' in line:
        if not file:
            raise ZygoteError('Select a file first (this tool works on the selected file).')
        line = line.replace('<file>', quoted_path(project, file))
    if '<folder>' in line:
        line = line.replace('<folder>', quoted_path(project, folder or project))
    return line


def command_danger(project, line):
    """The warning text when the finished command line would delete, move or rename a protected item (the project itself, .zygote, .git, zip, START_HERE.md,
    the launcher, the app_tree folder, anything outside the project), else ''. Only the command's name is looked at: del, erase, rd, rmdir, move, ren, rename."""
    import shlex
    try:
        words = shlex.split(line, posix=False)
    except ValueError:
        words = line.split()
    if not words or Path(words[0].strip('"')).stem.lower() not in DANGEROUS_COMMANDS:
        return ''
    root = clean_path(project)
    for word in words[1:]:
        word = word.strip('"')
        if not word or word.startswith('/') and len(word) <= 3 or word.startswith('-'):
            continue                                                  # a switch such as /s or /q
        target = Path(os.path.normpath(root / word.replace('\\', '/')))
        if any(mark in word for mark in '*?'):
            target = target.parent                                    # a wildcard acts on what is in that folder
        rel = project_relative(root, target)
        if rel is None:
            return f'{words[0]} was stopped: {word} is outside the project.'
        if rel == '' and target != root / word.replace('\\', '/'):
            return f'{words[0]} was stopped: {word} at the project root could reach protected items (START_HERE.md, the launcher). Name the files, or work in a folder.'
        if rel == '' or not can_trash(root, target):
            return f'{words[0]} was stopped: {word} is protected (the project itself, .zygote, .git, zip, START_HERE.md, the launcher and the app tree folder cannot be deleted, moved or renamed).'
    return ''


def open_external_tool(line, folder, keep_open):
    """Run one command line in an external console window (one process, from a menu press). Windows: cmd.exe /k (stays open) or /c (closes), the line passed
    whole so its quotes arrive as typed. Other systems: the known terminal, which waits for Enter. Returns the command text, None when there is no terminal."""
    if hasattr(subprocess, 'CREATE_NEW_CONSOLE'):
        text = f'cmd.exe {"/k" if keep_open else "/c"} {line}'
        subprocess.Popen(text, cwd=str(folder), creationflags=subprocess.CREATE_NEW_CONSOLE)
        return text
    return open_external_console(['/bin/sh', '-c', line], folder)


def command_shell_words(line, keep_open=True):
    """The program and words that run one command line: Windows cmd.exe /c, other systems sh -c."""
    if hasattr(subprocess, 'CREATE_NEW_CONSOLE'):
        return ['cmd.exe', '/c', line]
    return ['/bin/sh', '-c', line]


def run_program(program, path):
    """Hand one file to one program. One process per call; Zygote does not wait for it or track it."""
    exe = program if Path(program).is_file() else shutil.which(program)
    if not exe:
        raise ZygoteError(f'The program "{program}" was not found. Pick another one in Settings > Tools.')
    subprocess.Popen([exe, str(path)])


def open_file(path):
    """Double-click: the program chosen for this file type, or else the one Windows has."""
    program = program_for(path)
    if program:
        run_program(program, path)
    else:
        open_path(path)


def open_as_text(path):
    run_program(NOTEPAD, path)


# ---- help (shown inside the window: no process, no browser) ----------------------------------------------------
def zygote_help_path():
    return zpath(ZYGOTE_ROOT, 'help', 'zygote.html')


def project_help_path(project):
    return zpath(project, 'help', 'README.md')


def read_help(path):
    path = Path(path)
    if not path.is_file():
        raise ZygoteError(f'The help page was not found: {path}')
    return path.read_text(encoding='utf-8')


# ---- command-line windows (DOCTRINE Part 4, item 6: one process per press of a CLI button) ---------------------------
CLI_PROGRAMS = {'cmd': 'cmd.exe', 'powershell': 'powershell.exe'}


def quote_for_powershell(text):
    return "'" + text.replace("'", "''") + "'"


def cli_admin_parameters(kind, folder):
    """The parameters that make an elevated window start in `folder`."""
    if kind == 'cmd':
        return f'/k cd /d "{folder}"'
    return f'-NoExit -Command "Set-Location -LiteralPath {quote_for_powershell(str(folder))}"'


ERROR_CANCELLED_CODE = 5          # what ShellExecute answers when the person presses No in the Windows permission window


def open_cli(kind, folder, admin=False):
    """Open a Command Prompt or PowerShell window in `folder`. One process per call; Zygote does not wait for it.
    With admin=True Windows asks for permission first (the person can say no).
    Returns True when the window was started, False when the person said No to the permission window (nothing is wrong then)."""
    if kind not in CLI_PROGRAMS:
        raise ZygoteError(f'Unknown command window: {kind}')
    if not folder or not Path(folder).is_dir():
        raise ZygoteError('No folder is shown yet. Click a folder first, then open the command window.')
    if not hasattr(ctypes, 'windll'):
        raise ZygoteError('Opening a command window needs Windows.')
    program = CLI_PROGRAMS[kind]
    if admin:
        code = ctypes.windll.shell32.ShellExecuteW(None, 'runas', program, cli_admin_parameters(kind, folder), str(folder), 1)
        if code == ERROR_CANCELLED_CODE:
            return False
        if code <= 32:
            raise ZygoteError(f'{program} was not started as administrator (Windows code {code}).')
    else:
        subprocess.Popen([program], cwd=str(folder), creationflags=subprocess.CREATE_NEW_CONSOLE)
    return True


def file_manager_label():
    """The wording of the menu item that shows a folder in the system's own file manager."""
    return 'Open in Explorer' if os.name == 'nt' else 'Open in file manager'


def plain_os_error(error):
    """One short sentence for an operating-system error (the long Windows text is not repeated)."""
    code = getattr(error, 'winerror', None)
    if code == 225:
        return 'Windows security stopped it (it looked like a virus). Allow it in Windows Security, or give the project another entry point.'
    if code == 1155 or code == 1156:
        return 'Windows has no program for this file type. Give the entry point a runner in Settings > Project settings.'
    return str(error.strerror or error)


def open_path(path):
    """Hand a file or folder to the system (Windows: its own program or Explorer; elsewhere: xdg-open, the default program or file manager)."""
    if not hasattr(os, 'startfile'):
        try:
            subprocess.Popen(['xdg-open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            raise ZygoteError(f'{path} was not opened: xdg-open is not available here ({error}).') from error
        return
    try:
        os.startfile(str(path))
    except OSError as error:
        raise ZygoteError(f'{Path(path).name} could not be opened: {plain_os_error(error)}') from error


def stamp_link(link, target, arguments, start_in, icon=None):
    """Write one .lnk (pywin32, in-process COM): target, arguments, start-in folder, the icon (Zygote's own when none is given), minimized."""
    try:
        import win32com.client
    except ImportError as error:
        raise ZygoteError('Making the shortcut needs Windows and the pywin32 package (.zygote\\config\\requirements.txt).') from error
    shortcut = win32com.client.Dispatch('WScript.Shell').CreateShortCut(str(link))
    shortcut.TargetPath = str(target)
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = str(start_in)             # "Start in": the project, which Zygote offers as the current folder
    shortcut.IconLocation = str(icon or ICON_FILE)
    shortcut.WindowStyle = 7                              # minimized
    shortcut.Save()
    return Path(link)


# ---- the launcher a project can carry: Launch Zygote.exe ----------------------------------------------------------------------------
# A hand-written C program (.zygote\tools\c\run_project.c) that finds the folder it sits in and starts the installed Zygote on that folder. Zygote
# compiles it with the compiler of its own environment (the `ziglang` package) and gives it the one absolute path, where Zygote is installed.
LAUNCHER_DIR = zpath(ZYGOTE_ROOT, 'tools', 'c')
LAUNCHER_C = LAUNCHER_DIR / 'run_project.c'
LAUNCHER_RC = LAUNCHER_DIR / 'run_project.rc'                 # the icon (Windows)
LAUNCHER_BUILD = LAUNCHER_DIR / 'build'
LAUNCHER_NAME = 'Launch Zygote.exe' if os.name == 'nt' else 'launch_zygote'     # the name of the program Zygote builds, and the name a project's launcher had before 2.14.9
LEGACY_LAUNCHERS = ('Run project.exe', 'run_project')          # the name before 2.13.9: still never zipped; an ordinary file otherwise, so it can be thrown away
LAUNCHER_NAMES = (LAUNCHER_NAME,) + LEGACY_LAUNCHERS
LAUNCHER_IS_SHORTCUT = os.name == 'nt'                         # Windows: the launcher is a shortcut (.lnk), not a compiled program (Defender called the compiled one a virus)
LAUNCHER_SUFFIX = '_Zide.lnk' if LAUNCHER_IS_SHORTCUT else '_zide'    # a project's launcher is named after the project: VFlow_Zide.lnk (several shortcuts stay apart)
LEGACY_SUFFIXES = ('_Zyde.exe', '_Zyde.lnk', '_zyde')    # the launchers of 2.14.9-2.14.21 (before the name Zide): never zipped, but no longer made, renamed or protected
COMPILE_SECONDS = 600


def launcher_name(project):
    """The name of the project's launcher at its root: the project's name (made safe for a file name) + _Zide.lnk, e.g. VFlow_Zide.lnk (Windows)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', project_name(project)).strip(' .') or 'Zygote'
    return name + LAUNCHER_SUFFIX


def is_live_launcher_name(name):
    """True for the names of a launcher in use: the project's own (<project>_Zide.exe) and the one it had before 2.14.9 (Launch Zygote.exe)."""
    name = str(name)
    return name.lower() == LAUNCHER_NAME.lower() or name.lower().endswith(LAUNCHER_SUFFIX.lower())


def is_launcher_name(name):
    """True for any name a launcher has had (also the older Run project.exe): never zipped. Only the live ones are protected, renamed or pinned at the top."""
    return is_live_launcher_name(name) or str(name) in LAUNCHER_NAMES or any(str(name).lower().endswith(old.lower()) for old in LEGACY_SUFFIXES)


def find_launchers(project):
    """The launchers in use sitting at the project's root, by any of their live names."""
    root = clean_path(project)
    try:
        return sorted(path for path in root.iterdir() if path.is_file() and is_live_launcher_name(path.name))
    except OSError:
        return []


def rename_launcher(project):
    """Give an existing launcher the project's name (Launch Zygote.exe, or the name before the project was renamed, becomes VFlow_Zide.exe). Only a rename:
    nothing is compiled and no content changes. Returns the sentence for the Log, or None when there is nothing to do. A second launcher that
    cannot take the name (the right name is already there) is named and left alone."""
    root, wanted = clean_path(project), launcher_name(project)
    others = [path for path in find_launchers(project) if path.name != wanted]
    if not others:
        return None
    if (root / wanted).exists():
        return f'{wanted} is already there; {", ".join(path.name for path in others)} was left as it is.'
    first = others[0]
    first.rename(root / wanted)
    return f'{first.name} is now {wanted}. A shortcut that pointed at the old name needs to be made again.'


def c_string(text):
    """A path as the inside of a C string literal."""
    return str(text).replace('\\', '\\\\').replace('"', '\\"')


LAUNCHER_FORMAT = b'ZYGOTE_LAUNCHER_FORMAT_3'                      # inside the program: it is the one that reads the pointer file


def launcher_is_current(path):
    """True when the launcher file exists and is the pointer-reading program (not an older one with an install path built in)."""
    path = Path(path)
    if LAUNCHER_IS_SHORTCUT and path.suffix.lower() == '.lnk':
        return path.is_file()
    return path.is_file() and LAUNCHER_FORMAT in path.read_bytes()


def run_compiler(command, out, what):
    """ONE compiler run (the ziglang package of .zygote\\env) for any of the checked-in C programs. Raises ZygoteError with the compiler's own words."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=COMPILE_SECONDS, creationflags=flags)     # stdin given: Zygote runs under pythonw, which has none, and Windows then says "[WinError 6] The handle is invalid"
    except subprocess.TimeoutExpired as error:
        raise ZygoteError(f'The compiler did not finish in {COMPILE_SECONDS} seconds.') from error
    if done.returncode != 0 or not out.is_file():
        raise ZygoteError(f'The {what} program was not built. The compiler (the ziglang package in .zygote\\env) said:\n{done.stdout}{done.stderr}'.strip())
    return out


def compile_launcher(out=None, target=None):
    """Compile run_project.c once (one compiler run) into app_tree\\tools\\c\\build. Nothing about this computer goes into the program: it finds Zygote
    through the `zygote` command on the PATH when it runs. Raises ZygoteError with the compiler's own words."""
    windows = (os.name == 'nt') if target is None else ('windows' in target)
    out = Path(out) if out else LAUNCHER_BUILD / LAUNCHER_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'ziglang', 'cc', str(LAUNCHER_C), '-O2', '-g0', '-o', str(out)]
    if windows:
        command += [str(LAUNCHER_RC), '-Wl,--subsystem,windows']
    if target:
        command += ['-target', target]
    return run_compiler(command, out, 'Launch Zygote')


# ---- the setup program: one file = a small C program with a ZIP attached to its end -------------------------------------------------
# Make ZIP > EXE (or both) joins .zygote\tools\c\setup_stub.c (compiled once for that press) and the ZIP. Run on another computer it unpacks the ZIP
# into a new folder beside itself and, for a Zygote program folder, finds Python (asks once to download it), builds the environment and starts Zygote.
SETUP_C = LAUNCHER_DIR / 'setup_stub.c'
PACKAGE_KINDS = ('zip', 'exe', 'both')


SETUP_ICON_RC = LAUNCHER_DIR / 'setup_icon.rc'                 # hand-written: `1 ICON "program.ico"`; the project's icon is copied beside a copy of it, nothing is generated


def compile_setup_stub(out, target=None, icon=None):
    """Compile setup_stub.c (one compiler run) to `out`. Returns the path of the program. `icon` (an .ico file) is the program's own icon on Windows
    (Zygote's when none is given); an icon the compiler refuses is said, not replaced."""
    import tempfile
    windows = (os.name == 'nt') if target is None else ('windows' in target)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        resource = LAUNCHER_RC
        if windows and icon and Path(icon).is_file() and Path(icon).suffix.lower() == '.ico':
            resource = Path(tmp) / 'setup_icon.rc'
            shutil.copyfile(SETUP_ICON_RC, resource)
            shutil.copyfile(icon, Path(tmp) / 'program.ico')
        command = [sys.executable, '-m', 'ziglang', 'cc', str(SETUP_C), '-O2', '-g0', '-o', str(out)]
        if windows:
            command += [str(resource), '-lurlmon', '-ladvapi32', '-luser32', '-Wl,--subsystem,windows']
        if target:
            command += ['-target', target]
        return run_compiler(command, out, 'Setup')


def make_setup_exe(zip_path, exe_path, target=None, icon=None):
    """Write exe_path = the setup program followed by the ZIP (the ZIP is read, never changed). Returns exe_path."""
    import tempfile
    exe_path = Path(exe_path)
    windows = (os.name == 'nt') if target is None else ('windows' in target)
    with tempfile.TemporaryDirectory() as tmp:
        stub = compile_setup_stub(Path(tmp) / ('stub.exe' if windows else 'stub'), target, icon)
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        with open(exe_path, 'wb') as out, open(stub, 'rb') as head, open(zip_path, 'rb') as payload:
            shutil.copyfileobj(head, out)
            shutil.copyfileobj(payload, out)
    exe_path.chmod(0o755)
    return exe_path


def package_paths(zip_dest, kind):
    """The files a Make ZIP choice writes: the ZIP, the setup program (the same name with .exe) or both."""
    if kind not in PACKAGE_KINDS:
        raise ZygoteError(f'Unknown choice for Make ZIP: {kind}')
    zip_dest = Path(zip_dest)
    return [path for wanted, path in (('zip' if kind != 'exe' else None, zip_dest), ('exe' if kind != 'zip' else None, zip_dest.with_suffix('.exe'))) if wanted]


def make_package(project, zip_dest, kind, include_user=False, include_credentials=False, target=None):
    """Make ZIP's three choices: 'zip' (the ZIP), 'exe' (the setup program only; the ZIP inside is a temporary file) or 'both'.
    The ZIP holds ONE top folder named like the project (drag it out, open it, run Setup.bat). The ZIP inside the EXE has no top folder: the program
    unpacks into a new folder beside itself, and that folder is the project. Returns (the number of files in the ZIP, the paths written)."""
    import tempfile
    written = package_paths(zip_dest, kind)
    choices = dict(include_user=include_user, include_credentials=include_credentials)
    count = None
    if kind != 'exe':
        count = make_zip(project, zip_dest, top=project_name(project), **choices)
    if kind != 'zip':
        with tempfile.TemporaryDirectory() as tmp:
            inside = Path(tmp) / Path(zip_dest).name
            flat = make_zip(project, inside, **choices)
            make_setup_exe(inside, written[-1], target)
        count = flat if count is None else count
    return count, written


RINGS_FILE = zpath(ZYGOTE_ROOT, 'assets', 'icons', 'project-rings.png')    # Zygote's double ring with the middle blanked (data)


def launcher_icon(project):
    """The icon file of the project's launcher: the double ring with the project's own program icon inside (empty rings when it has none), made again each
    time into .zygote\\user\\launcher.ico. A project without an icon of its own shows Zygote's in the rings. Zygote itself (the core, not a project) shows its
    own icon alone, no rings. A program icon that is gone is said, not replaced."""
    from functional import launcher_icon as maker
    out = clean_path(project) / DOT / 'user' / 'launcher.ico'
    try:
        if clean_path(project) == clean_path(ZYGOTE_ROOT):
            return str(maker.write_plain(ICON_FILE, out))
        return str(maker.write_icon(RINGS_FILE, program_icon_file(project), out))
    except ValueError as error:
        raise ZygoteError(str(error)) from error


def notify_icons():
    """Tell Windows that icons changed (SHCNE_ASSOCCHANGED), so a new launcher icon shows instead of the cached one. An API call in this process.
    False where there is no Windows shell."""
    if not hasattr(ctypes, 'windll'):
        return False
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    return True


def make_launcher(project, force=False):
    """Put the project's launcher (<project>_Zide.lnk on Windows) at the root of the project. It is made here for this computer and never shipped (Make ZIP
    leaves it out). An older name (Launch Zygote.exe, or the name before the project was renamed) is renamed to the new one first.
    WINDOWS: the launcher is a shortcut to this Zygote's own windowless Python with the project, carrying the project's program icon (Zygote's when it has
    none). Nothing is compiled, so there is nothing for an antivirus to call a virus, and a new icon is only a rewrite of the shortcut. It is written again
    each time (it is quick), so a moved project gets a launcher that points at where it is now. Dragged out of the workbench, a copy of it is a shortcut.
    OTHER SYSTEMS: the compiled C program, as before; `force` compiles it again. Returns the path in the project."""
    rename_launcher(project)
    if LAUNCHER_IS_SHORTCUT:
        dest = clean_path(project) / launcher_name(project)
        link = stamp_link(dest, zygote_python(), shortcut_arguments(clean_path(project)), clean_path(project), launcher_icon(project))
        notify_icons()                                                       # Windows keeps old icons in a cache: it is told that icons changed
        return link
    built = LAUNCHER_BUILD / LAUNCHER_NAME
    if force or not launcher_is_current(built):
        compile_launcher()
    dest = clean_path(project) / launcher_name(project)
    if force or not launcher_is_current(dest):
        shutil.copyfile(built, dest)
        dest.chmod(0o755)
    return dest


# ---- the project's own copy of Zygote (.zygote\core) -----------------------------------------------------------------------------
CORE_REL = DOT + '/core'


def installed_version():
    return (ZYGOTE_ROOT / DOT / 'VERSION.txt').read_text(encoding='utf-8').strip()


def core_version(project):
    """The Zygote version copied into the project's .zygote\\core, or None when none was copied."""
    path = clean_path(project) / DOT / 'core' / 'VERSION.txt'
    return path.read_text(encoding='utf-8').strip() if path.is_file() else None


def update_core(project):
    """Copy the installed Zygote's app folder and version into the project's .zygote\\core, replacing the earlier copy. Returns the number of files."""
    project = clean_path(project)
    if project == ZYGOTE_ROOT:
        raise ZygoteError('This is the installed Zygote itself: there is nothing to copy it into.')
    if not (project / DOT).is_dir():
        raise ZygoteError(f'{project} has no .zygote folder.')
    core_dir = project / DOT / 'core'
    core_dir.mkdir(exist_ok=True)
    fresh, old = core_dir / 'app.new', core_dir / 'app'
    if fresh.exists():
        shutil.rmtree(fresh)
    shutil.copytree(ZYGOTE_ROOT / 'app', fresh, ignore=shutil.ignore_patterns('__pycache__'))
    if old.exists():
        shutil.rmtree(old)
    fresh.rename(old)
    (core_dir / 'VERSION.txt').write_text(installed_version() + '\n', encoding='utf-8')
    return sum(1 for item in old.rglob('*') if item.is_file())


def remember_update(project, what):
    """The last real update of the project's core, kept as data in the computer's record (never zipped): when, and what it did."""
    state = load_state(project)
    state['last_update'] = {'when': now().isoformat(timespec='seconds'), 'what': what}
    save_state(project, state)


def last_update_text(project):
    """'Updated at 14:52, 46 new icons added' (the date first when it was not today) for the last real update, or '' when there was none."""
    found = load_state(project).get('last_update')
    if not isinstance(found, dict) or not found.get('when'):
        return ''
    when = datetime.datetime.fromisoformat(found['when'])
    stamp = f'{when:%H:%M}' if when.date() == now().date() else f'{when:%Y-%m-%d %H:%M}'
    return f'Updated at {stamp}' + (f', {found["what"]}' if found.get('what') else '')


def zygote_python():
    """Zygote's own windowless Python (pythonw.exe in .zygote\\env). A shortcut starts it directly: no batch file, no console."""
    env = ZYGOTE_ROOT / '.venv' if (ZYGOTE_ROOT / 'deploy.json').is_file() else ZYGOTE_ROOT / DOT / 'env'      # a deployed folder's start script built .venv (bootstrap.py says the same)
    path = env / 'Scripts' / 'pythonw.exe'
    if not path.is_file():
        raise ZygoteError(f'{path} was not found. Run app_tree\\bat\\RUN.bat once so that Zygote builds its environment, then make the shortcut again.')
    return path


def shortcut_arguments(project):
    """What a project's shortcut hands to pythonw.exe: Zygote's main.py and the project to open."""
    return f'"{ZYGOTE_ROOT / "app" / "main.py"}" --project "{project}"'


def read_link(link):
    """(target, arguments, start-in folder) of a .lnk, or None when it is not there (or this is not Windows)."""
    if os.name != 'nt' or not Path(link).is_file():
        return None
    import win32com.client
    shortcut = win32com.client.Dispatch('WScript.Shell').CreateShortCut(str(link))
    return shortcut.TargetPath, shortcut.Arguments, shortcut.WorkingDirectory


def link_matches(found, target, arguments, start_in):
    """True when what read_link found is what a fresh stamp would write (case and slash direction do not count in a path)."""
    if found is None:
        return False
    same = lambda one, two: os.path.normcase(os.path.normpath(str(one))) == os.path.normcase(os.path.normpath(str(two)))
    return same(found[0], target) and found[1].replace('/', '\\').lower() == arguments.replace('/', '\\').lower() and same(found[2], start_in)


def shortcuts_wrong(project):
    """The shortcuts of a project that are missing or hold another place (the project was moved, renamed, or came from a ZIP): [file name, ...]. Windows only
    (elsewhere there is nothing to check and the list is empty). Nothing is written here."""
    if not LAUNCHER_IS_SHORTCUT:
        return []
    root, wrong = clean_path(project), []
    arguments = shortcut_arguments(root)
    launcher = root / launcher_name(root)
    if not link_matches(read_link(launcher), zygote_python(), arguments, root):
        wrong.append(launcher.name)
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', project_name(root)).strip(' .') or 'project'
    user = root / DOT / 'user' / f'{safe} (Zygote).lnk'
    if not link_matches(read_link(user), zygote_python(), arguments, root):
        wrong.append(user.name)
    return wrong


def create_shortcut(project, name):
    """Stamp the shortcut that starts THIS Zygote on that project: .zygote\\user\\<name> (Zygote).lnk, always with Zygote's own icon. Needs Windows and
    pywin32 (no extra process). It runs pythonw.exe directly and holds this computer's paths, so it stays in the private user folder. The launcher at
    the project root is `Launch Zygote.exe` (make_launcher), no longer a shortcut. Returns the list of shortcuts made."""
    project = Path(project)
    python = zygote_python()
    folder = project / DOT / 'user'
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob('* (Zygote).lnk'):
        old.unlink()
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .') or 'project'
    arguments = shortcut_arguments(project)
    return [stamp_link(folder / f'{safe} (Zygote).lnk', python, arguments, project, ICON_FILE)]   # always Zygote's own icon: the shortcut runs Zygote


# ---- the program icon of a project (Project settings > Assets) ------------------------------------------------------------------------


def icons_dir(project):
    return zpath(clean_path(project), 'assets', 'icons')


ICON_SET = zpath(ZYGOTE_ROOT, 'assets', 'icons')                   # Zygote's icon set: the program icons, the folder pictures and CREDITS.txt (data: add a file to add an icon)


def copy_icon_set(project):
    """A new project starts with the whole icon set in its own icons folder (so Browse shows them and CREDITS.txt travels with them). A file the project has already is
    never replaced. Returns the number of files copied. Zygote's own folder is not a target (it already is the set)."""
    target = icons_dir(project)
    if target == ICON_SET:
        return 0
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for source in sorted(ICON_SET.iterdir()):
        if source.is_file() and source.name != 'README.md' and not (target / source.name).exists():
            shutil.copy2(source, target / source.name)
            count += 1
    return count


def icon_changes(project):
    """(missing, differing): the names in Zygote's icon set that this project's icons folder lacks, and those it has with other contents (compared by contents, never by date).
    Zygote's own folder is not compared with itself."""
    target = icons_dir(project)
    if target == ICON_SET:
        return [], []
    missing, differing = [], []
    for source in sorted(ICON_SET.iterdir()):
        if not source.is_file() or source.name == 'README.md':
            continue
        mine = target / source.name
        if not mine.exists():
            missing.append(source.name)
        elif not filecmp.cmp(source, mine, shallow=False):
            differing.append(source.name)
    return missing, differing


def refresh_icons(project, replace=()):
    """The core refresh of the icon set: every missing icon is added; the names in `replace` (the ones the person ticked) are replaced. Returns (added, replaced) counts."""
    missing, differing = icon_changes(project)
    target = icons_dir(project)
    target.mkdir(parents=True, exist_ok=True)
    for name in missing:
        shutil.copy2(ICON_SET / name, target / name)
    chosen = [name for name in replace if name in differing]
    for name in chosen:
        shutil.copy2(ICON_SET / name, target / name)
    return len(missing), len(chosen)


def program_icon(project):
    """The saved program icon (a .ico inside the project's icons folder) or None. Raises when the saved file is gone: shown, never replaced silently."""
    rel = load_state(project).get('icon')
    if not rel:
        return None
    path = clean_path(project) / rel
    if not path.is_file():
        raise ZygoteError(f'The program icon {rel} is not in the project any more. Choose it again in Settings > Project settings… > Assets.')
    return path


def program_icon_file(project):
    """The icon file to show: the project's own, else Zygote's."""
    return program_icon(project) or ICON_FILE


def free_icon_path(project, name):
    """A path in the icons folder for this file name that no other file uses (name.ico, then name (2).ico, name (3).ico …)."""
    folder = icons_dir(project)
    stem, suffix = Path(name).stem, Path(name).suffix
    path = folder / name
    number = 2
    while path.exists():
        path = folder / f'{stem} ({number}){suffix}'
        number += 1
    return path


def safe_file_name(name, default):
    """A name that is fine as a Windows file name (no forbidden characters, no trailing dots or spaces); `default` when nothing is left."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or '').strip(' .') or default


def icon_target(project, name):
    """Where the icon of a project named `name` goes: the icons folder, <project name>.ico (the default name of a new icon)."""
    return icons_dir(project) / (safe_file_name(name, 'icon') + '.ico')


def plan_icon(project, text, current):
    """What the icon line asks for, checked without changing anything. `current` is the icon file the line showed last (or None).
    ('none', None, None): an empty line. ('file', path, None): an existing .ico file. ('rename', current, target): the line holds a name that
    is not a file, so the current icon is renamed to it (the file stays in the icons folder; no .ico typed = .ico added)."""
    text = (text or '').strip().strip('"')
    if not text:
        return ('none', None, None)
    path = Path(text)
    path = clean_path(path if path.is_absolute() else clean_path(project) / path)
    if path.is_file():
        return ('file', check_icon(project, text), None)
    folder = icons_dir(project)
    if current is None or not Path(current).is_file() or clean_path(current).parent != folder:
        raise ZygoteError(f'The program icon is not a file: {path}')
    typed = Path(text)
    if typed.parent != Path('.') and clean_path(typed if typed.is_absolute() else clean_path(project) / typed).parent != folder:
        raise ZygoteError(f'The program icon is not a file: {path}. To rename the current icon, type a name only. The file stays in {folder}')
    name = typed.name.rstrip('. ')
    if not name:
        raise ZygoteError('The icon needs a name.')
    if Path(name).suffix == '':
        name += '.ico'
    if Path(name).suffix.lower() != '.ico':
        raise ZygoteError(f'The program icon must be a .ico file: {name}')
    return ('rename', clean_path(current), folder / safe_file_name(name, 'icon.ico'))


def rename_icon(project, current, target):
    """Rename the current icon file to the target (replacing a file there: the caller has asked first). Returns the path relative to the project."""
    current, target = clean_path(current), clean_path(target)
    if current != target:
        os.replace(current, target)
    return target.relative_to(clean_path(project)).as_posix()


def check_icon(project, text):
    """Check a typed or dropped program icon without changing anything: a .ico file. Returns its path, or None for an empty text (no icon)."""
    text = (text or '').strip().strip('"')
    if not text:
        return None
    path = Path(text)
    path = clean_path(path if path.is_absolute() else clean_path(project) / path)
    if not path.is_file():
        raise ZygoteError(f'The program icon is not a file: {path}')
    if path.suffix.lower() != '.ico':
        raise ZygoteError(f'The program icon must be a .ico file: {path.name}. Drop a picture (.png, .bmp, .jpg …) on the icon line to make an icon from it.')
    return path


def icon_relative(project, text):
    """Take the program icon: a .ico file. One outside the project's icons folder is COPIED there (the project carries it). The same file already
    there is used as it is. Returns the path relative to the project ('' for an empty text = no icon)."""
    path = check_icon(project, text)
    if path is None:
        return ''
    root = clean_path(project)
    folder = icons_dir(project)
    if path.parent == folder:
        return path.relative_to(root).as_posix()
    existing = folder / path.name
    if existing.is_file() and existing.read_bytes() == path.read_bytes():
        return existing.relative_to(root).as_posix()
    target = free_icon_path(project, path.name)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target.relative_to(root).as_posix()


def set_program_icon(project, text):
    """Save the program icon (copying it into the project when it comes from elsewhere). An empty text clears it. Returns the saved relative path."""
    rel = icon_relative(project, text)
    state = load_state(project)
    if rel:
        state['icon'] = rel
    else:
        state.pop('icon', None)
    save_state(project, state)
    return rel


# ---- adopting a plain folder: add the .zygote tree to it ---------------------------------------------------------------
BASELINE = zpath(ZYGOTE_ROOT, 'assets', 'baseline')      # the files a folder gets (data: Zygote copies from here and never changes it)
ROOT_GITIGNORE = zpath(ZYGOTE_ROOT, 'assets', 'root_gitignore.txt')       # the project's top-level .gitignore, written by adopt only when the project has none
STARTING_VERSION = '0.0.1'


def baseline_files():
    """The files of the baseline, as paths relative to .zygote (forward slashes)."""
    return sorted(p.relative_to(BASELINE).as_posix() for p in BASELINE.rglob('*') if p.is_file())


def missing_baseline(project):
    """The baseline files this project does not have yet."""
    return [rel for rel in baseline_files() if not zpath(project, rel).exists()]


def adopt_declined(project):
    return str(clean_path(project)).lower() in [str(p).lower() for p in load_settings().get('adopt_declined', [])]


def decline_adoption(project):
    declined = list(load_settings().get('adopt_declined', []))
    declined.append(str(clean_path(project)))
    save_setting('adopt_declined', declined)


def should_offer_adoption(project):
    """True when the folder lacks part of the baseline, is not Zygote's own folder, and the person did not already say no here."""
    project = clean_path(project)
    return project != ZYGOTE_ROOT and not is_legacy_layout(project) and bool(missing_baseline(project)) and not adopt_declined(project)


def version_prefix(name):
    """The first part of a starting version: the project name in capitals with only letters, digits and underscores (Z_test -> Z_TEST)."""
    prefix = re.sub(r'[^A-Z0-9_]+', '_', name.upper()).strip('_') or 'P'
    return prefix if prefix[0].isalpha() else 'P_' + prefix


def start_here_text(project, name, version):
    today = now().date().isoformat()
    return (f'# START HERE \u2014 {name}\n\n'
            f'> **Project:** {name}. **Version:** read `.zygote\\VERSION.txt` (first line). This file is the running build log; '
            f'started from the folder {Path(project).name} on {today}.\n\n'
            f'## State\n- {version}: the Zygote tree (`.zygote`) was added to the folder on {today}. Nothing that was already there was changed.\n')


ZYGOTE_OUTER_HUE = 285            # the hue of Zygote's own purple (#1e052b): a new project never gets a colour near it
NEW_LOOK_LIGHTNESS = 0.28         # dark enough for white text (contrast with white is at least 4.5 : 1 for every hue at this lightness and saturation)
NEW_LOOK_SATURATION = 0.55


def random_outer(chooser=random):
    """A colour for a new project's outer container: any hue except Zygote's own band (+-30 degrees), saturation and lightness fixed so that white text
    stays readable. `chooser` is the random module (tests hand in a fixed one). Returns '#rrggbb'."""
    while True:
        hue = chooser.randrange(360)
        gap = abs(hue - ZYGOTE_OUTER_HUE)
        if min(gap, 360 - gap) > 30:
            break
    red, green, blue = colorsys.hls_to_rgb(hue / 360, NEW_LOOK_LIGHTNESS, NEW_LOOK_SATURATION)
    return '#%02x%02x%02x' % (round(red * 255), round(green * 255), round(blue * 255))


def give_new_look(project):
    """A new project gets its own colour (dark theme) unless it already saved a look. Returns the colour, or None when the project had one."""
    state = load_state(project)
    if 'outer_color' in state or 'theme' in state:
        return None
    outer = random_outer()
    save_look(project, False, outer)
    return outer


def adopt_project(project, name):
    """Add the baseline to a plain folder. Only what is missing is written; nothing that exists is replaced or changed.
    Also writes .zygote\\VERSION.txt (<NAME>_0.0.1) when the project has no version, and START_HERE.md when there is none.
    Also writes the top-level .gitignore (ignore rules for .zygote, zip, deploy) when the project has none; .zygote itself holds no .gitignore.
    Returns {'added': [...], 'version': str, 'version_written': bool, 'start_here': 'written' or 'kept'}."""
    project = clean_path(project)
    if not project.is_dir():
        raise ZygoteError(f'Project folder not found: {project}')
    if project == ZYGOTE_ROOT:
        raise ZygoteError('This is Zygote\'s own folder: it already has the tree.')
    added = []
    for rel in missing_baseline(project):
        target = zpath(project, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((BASELINE / rel).read_bytes())
        added.append(rel)
    top_ignore = project / '.gitignore'
    ignore_written = not top_ignore.exists()
    if ignore_written:
        top_ignore.write_bytes(ROOT_GITIGNORE.read_bytes())
    version = read_version(project)
    version_written = version is None
    if version_written:
        version = f'{version_prefix(name)}_{STARTING_VERSION}'
        (project / DOT / 'VERSION.txt').write_text(version + '\n', encoding='utf-8')
    start_here = project / 'START_HERE.md'
    kept = start_here.exists()
    if not kept:
        start_here.write_text(start_here_text(project, name, version), encoding='utf-8')
    outer = give_new_look(project)
    return {'outer': outer, 'added': added, 'gitignore_written': ignore_written, 'version': version, 'version_written': version_written, 'start_here': 'kept' if kept else 'written'}


# ---- The standard layout: what Update project's core offers when a project lacks it (data in assets/standard_layout.json) ----------------
LAYOUT_FILE = zpath(ZYGOTE_ROOT, 'assets', 'standard_layout.json')
LAYOUT_NOTES = zpath(ZYGOTE_ROOT, 'assets', 'layout')


def standard_layout():
    """The items of assets/standard_layout.json. Raises with the plain reason when the file is not usable."""
    try:
        items = json.loads(LAYOUT_FILE.read_text(encoding='utf-8'))['items']
        for one in items:
            one['key'], one['kind'], one['default']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ZygoteError(f'{LAYOUT_FILE} is missing or damaged ({error}). Unpack the build ZIP again.') from error
    return items


def tree_files_missing(project):
    """The baseline files that belong in the app tree and are not in this project yet."""
    return [rel for rel in missing_baseline(project) if rel.replace('\\', '/').split('/')[0] in TREE_FOLDERS]


def layout_missing(project):
    """The standard items this project lacks, as the layout file's entries plus 'picture' (the file) and 'count' (files, for the tree). [] for Zygote's own folder and for a
    project that still keeps the older layout (that one is moved first). A folder or file counts as there in any letter case."""
    project = clean_path(project)
    if project == ZYGOTE_ROOT or is_legacy_layout(project):
        return []
    names = {path.name.lower() for path in project.iterdir()}
    out = []
    for one in standard_layout():
        count = 0
        if one['kind'] == 'tree':
            count = len(tree_files_missing(project))
            if not count:
                continue
        elif one['key'].lower() in names:
            continue
        out.append(dict(one, count=count, picture=layout_picture(one['key'])))
    return out


def add_layout(project, keys):
    """Add the standard items named in `keys` (only what is missing; nothing that exists is changed). Returns one sentence per item added."""
    project = clean_path(project)
    wanted = set(keys)
    done = []
    for one in layout_missing(project):
        if one['key'] not in wanted:
            continue
        if one['kind'] == 'tree':
            files = tree_files_missing(project)
            for rel in files:
                target = zpath(project, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((BASELINE / rel).read_bytes())
            done.append(f'{TREE}: {len(files)} file{"s" if len(files) != 1 else ""} added')
        elif one['kind'] == 'file':
            (project / one['key']).write_text(start_here_text(project, project_name(project), read_version(project) or ''), encoding='utf-8')
            done.append(f'{one["key"]} added')
        else:
            folder = project / one['key']
            folder.mkdir()
            note = LAYOUT_NOTES / f'{one["key"]}.README.md'
            if note.is_file():
                (folder / 'README.md').write_bytes(note.read_bytes())
            done.append(f'{one["key"]}\\ added')
    return done


# ---- Contents: read and edit a text file inside Zygote (no process); every Save keeps what was there in zip\edits ----------------
MAX_TEXT_BYTES = 2_000_000
EDIT_NAME = re.compile(r'^edit_(\d{4,})\.zip$')


def edits_dir(project):
    return zip_folder(project) / 'edits'


def read_text_file(path):
    """{'text', 'bom', 'newline'} of a text file (UTF-8, no NUL bytes, up to 2 MB). Anything else raises: it is not offered as text."""
    path = Path(path)
    if not path.is_file():
        raise ZygoteError(f'Not a file: {path}')
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise ZygoteError(f'{path.name} is larger than {MAX_TEXT_BYTES // 1_000_000} MB: not shown as text.')
    data = path.read_bytes()
    if b'\x00' in data:
        raise ZygoteError(f'{path.name} holds binary data: not shown as text.')
    bom = data.startswith(b'\xef\xbb\xbf')
    try:
        text = data[3:].decode('utf-8') if bom else data.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ZygoteError(f'{path.name} is not UTF-8 text: not shown as text.') from error
    newline = '\r\n' if b'\r\n' in data else '\n'
    return {'text': text.replace('\r\n', '\n'), 'bom': bom, 'newline': newline}


def is_text_file(path):
    try:
        read_text_file(path)
    except ZygoteError:
        return False
    return True


def editable_in(project, path):
    """True when the file is inside the project and not in a sacred folder (.git, zip, .zygote\\user, credentials, logs, env)."""
    if project is None:
        return False
    try:
        rel = Path(path).resolve().relative_to(Path(project).resolve()).as_posix()
    except ValueError:
        return False
    return not is_sacred(rel)


def next_edit_name(project):
    folder = edits_dir(project)
    numbers = [int(m.group(1)) for m in (EDIT_NAME.match(p.name) for p in folder.glob('*.zip')) if m] if folder.is_dir() else []
    return f'edit_{max(numbers, default=0) + 1:04d}.zip'


def save_text_file(project, path, text, bom, newline):
    """Write the edited text back (same BOM and line endings as before). First the old file goes into zip\\edits\\edit_NNNN.zip
    (manifest.json holds the file and the moment; files\\<file> holds what was there). Returns the snapshot name."""
    project, path = Path(project), Path(path)
    if not editable_in(project, path):
        raise ZygoteError(f'{path.name} is read-only here (outside the project, or in a folder that belongs to this computer).')
    rel = path.resolve().relative_to(project.resolve()).as_posix()
    before = path.read_bytes()
    name = next_edit_name(project)
    edits_dir(project).mkdir(parents=True, exist_ok=True)
    manifest = {'file': rel, 'saved': now().isoformat(timespec='seconds'), 'bytes_before': len(before)}
    with zipfile.ZipFile(edits_dir(project) / name, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', json.dumps(manifest, indent=2))
        zf.writestr('files/' + rel, before)
    data = text.replace('\n', newline).encode('utf-8')
    path.write_bytes((b'\xef\xbb\xbf' if bom else b'') + data)
    return name


# ---- what Run does: the entry point of the mode (Project settings), else a real RUN.bat, else the settings panel opens -------------------
RUN_MODES = ('debug', 'runtime')           # a project keeps one run configuration per mode: runner, entry point, command line arguments
RUNNER_HINTS = {'.py': {'debug': 'ipython -i', 'runtime': 'python'}}     # suggestions put in an EMPTY runner field when an entry file of that type is chosen; nothing is saved by them


def check_mode(mode):
    if mode not in RUN_MODES:
        raise ZygoteError(f'unknown run mode: {mode} (use debug or runtime)')
    return mode


def run_settings(project, mode):
    """{'runner', 'entry', 'args'} of one mode ('' for what is not set). A project from before Z 2.5 has one entry point: it counts for runtime."""
    check_mode(mode)
    state = load_state(project)
    saved = dict(state.get('run', {}).get(mode, {}))
    if mode == 'runtime' and 'runtime' not in state.get('run', {}) and state.get('entry'):
        saved['entry'] = state['entry']
    return {'runner': saved.get('runner', ''), 'entry': saved.get('entry', ''), 'args': saved.get('args', '')}


ZYGOTE_ENTRY = 'app/main.py'                                    # where Zygote itself starts: the one special case (Run starts Zygote its own way; Deploy supplies this, saving nothing)


def own_entry(project):
    """The entry point Zygote knows for the project without being told: Zygote's own folder only ('' for every other project). Run and Deploy both ask here."""
    return ZYGOTE_ENTRY if clean_path(project) == ZYGOTE_ROOT else ''


ENTRY_NAMES = ('main.py', '__main__.py', 'app.py', 'run.py')
ENTRY_FOLDERS = ('', 'app', 'app_tree')


def entry_candidates(project):
    """The files that may be the program's start, for the person to pick from: ENTRY_NAMES at the top of the project and in app and app_tree (never .zygote, deploy, zip
    or an environment). Relative paths with forward slashes. Zygote only lists; nothing is chosen or saved here."""
    root = clean_path(project)
    return [(folder + '/' if folder else '') + name for folder in ENTRY_FOLDERS for name in ENTRY_NAMES if (root / folder / name).is_file()]


def run_all(project):
    return {mode: run_settings(project, mode) for mode in RUN_MODES}


def runner_hint(entry, mode):
    """The runner suggested for an entry file ('' when the file type has no suggestion)."""
    return RUNNER_HINTS.get(Path(entry).suffix.lower(), {}).get(check_mode(mode), '')


def entry_relative(project, text):
    """Check a typed or dropped entry point: a file inside the project. Returns the relative path ('' for an empty text = no entry point)."""
    text = (text or '').strip().strip('"')
    if not text:
        return ''
    root = clean_path(project)
    path = Path(text)
    path = clean_path(path if path.is_absolute() else root / path)
    try:
        rel = path.relative_to(root)
    except ValueError:
        raise ZygoteError(f'{path} is outside the project folder {root}. The entry point must be a file inside the project.') from None
    if not path.is_file():
        raise ZygoteError(f'The entry point is not a file: {path}')
    return rel.as_posix()


def set_run_settings(project, mode, runner, entry, args):
    """Save one mode's runner, entry point (checked: a file inside the project) and command line arguments. Returns what was saved."""
    check_mode(mode)
    saved = {'runner': (runner or '').strip(), 'entry': entry_relative(project, entry), 'args': (args or '').strip()}
    state = load_state(project)
    state.setdefault('run', {})[mode] = saved
    if mode == 'runtime':
        state.pop('entry', None)                                 # the single entry point of Z 2.4 lives in 'runtime' now
    save_state(project, state)
    return saved


def entry_point(project, mode='runtime'):
    return run_settings(project, mode)['entry'] or None


def set_entry_point(project, text, mode='runtime'):
    """Save only the entry point of a mode (an empty text clears it). Returns what was saved."""
    current = run_settings(project, mode)
    return set_run_settings(project, mode, current['runner'], text, current['args'])['entry']


def current_mode(project):
    return run_mode(project)


def run_choice(project, mode=None):
    """('entry', rel) when the project has an entry point for its current mode (debug or runtime); ('bat', rel) when its RUN.bat is a real one;
    ('panel', reason) when there is nothing to run yet (no RUN.bat, or the placeholder RUN.bat Zygote adds to a plain folder)."""
    mode = check_mode(mode) if mode else current_mode(project)          # mode: ask about one mode whatever the project is set to
    entry = entry_point(project, mode)
    if entry:
        if not (Path(project) / entry).is_file():
            raise ZygoteError(f'The {mode} entry point {entry} is not in the project any more. Set it again in Settings > Project settings….')
        return 'entry', entry
    try:
        rel = run_bat_in(project)
    except ZygoteError:
        return 'panel', f'no {mode} entry point is set, and the project has no RUN.bat'
    if (Path(project) / rel).read_bytes() == (BASELINE / 'bat' / 'RUN.bat').read_bytes():
        return 'panel', f'no {mode} entry point is set, and RUN.bat is still the placeholder'
    return 'bat', rel


def split_words(text):
    """A command line typed by a person, cut into words. Quotes group words and are removed; backslashes stay (Windows paths)."""
    import shlex
    lexer = shlex.shlex(text or '', posix=False)
    lexer.whitespace_split = True
    return [word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in '"\'' else word for word in lexer]


def find_runner(project, program):
    """The file of a runner word: the project's own environment first (.zygote\\env\\Scripts or bin), then the PATH. Raises when it is nowhere."""
    for rel in (DOT + '/env/Scripts', DOT + '/env/bin'):
        for name in (program, program + '.exe'):
            candidate = Path(project) / rel / name
            if candidate.is_file():
                return str(candidate)
    found = program if Path(program).is_file() else shutil.which(program)
    if not found:
        raise ZygoteError(f'The runner "{program}" was not found in the project environment (.zygote\\env) or on the PATH. '
                          f'Install it there, or change the runner in Settings > Project settings….')
    return found


def command_text(runner, entry, args):
    """The command as the settings panel shows it (not looked up, not started)."""
    words = [(runner or '').strip() or '(opened by Windows)', entry or '(no entry point)', (args or '').strip()]
    return ' '.join(word for word in words if word)


def refresh_path():
    """Windows: add to this program's own PATH the folders Windows has now and this program lacks (a program installed after Zygote started, such as Ollama,
    is otherwise not found by the shells and runs started from here). Nothing is removed. Other systems: nothing."""
    if os.name != 'nt':
        return
    import pathsetup
    current = [entry for entry in os.environ.get('PATH', '').split(os.pathsep) if entry]
    known = {os.path.normcase(os.path.normpath(entry)) for entry in current}
    added = [entry for entry in pathsetup.registry_entries() if os.path.normcase(os.path.normpath(entry)) not in known]
    if added:
        os.environ['PATH'] = os.pathsep.join(current + added)


def shell_command():
    """The words that start a command prompt (for the Console's Shell button): the Windows command interpreter, or the user's shell elsewhere.
    On Windows the PATH is refreshed first (refresh_path), so a program installed a moment ago is found in the new shell."""
    refresh_path()
    if os.name == 'nt':
        return [os.environ.get('COMSPEC', 'cmd.exe')]
    return [os.environ.get('SHELL', '/bin/sh')]


def arguments_for(project, paths):
    """Dropped files as the text of a command line: a path inside the project relative to it, any other whole; a path with spaces in quotes."""
    words = []
    for path in paths:
        path = Path(path)
        try:
            shown = path.relative_to(Path(project)).as_posix() or '.'
        except ValueError:
            shown = str(path)
        words.append(f'"{shown}"' if ' ' in shown else shown)
    return ' '.join(words)


def entry_command(project, mode, args=None):
    """The words that run the entry point of a mode with its runner (nothing is started). None when the mode has no runner: Windows opens the file.
    args: the arguments for this one run instead of the saved ones (files dropped on the run icon); nothing is saved."""
    saved = run_settings(project, check_mode(mode))
    if not saved['runner']:
        return None
    words = split_words(saved['runner'])
    words[0] = find_runner(project, words[0])
    return words + [str(Path(project) / saved['entry'])] + split_words(saved['args'] if args is None else args)


def run_entry_command(project, mode, args=None):
    """Start the entry point of a mode with its runner and arguments. 1 process per press of Run, and only when the console box is NOT ticked
    (ticked: the window runs the same words in its Console tab, see entry_command).
    With no runner the file goes to Windows (its own program for the type), with the arguments when there are any. Returns the command text."""
    saved = run_settings(project, check_mode(mode))
    saved['args'] = saved['args'] if args is None else args
    path = Path(project) / saved['entry']
    command = entry_command(project, mode, args)
    if command is None:
        if not hasattr(os, 'startfile'):
            raise ZygoteError(f'Opening {path} needs Windows (os.startfile is missing on this system)')
        try:
            os.startfile(str(path), arguments=saved['args'], cwd=str(project))
        except OSError as error:
            raise ZygoteError(f'{path.name} could not be started: {plain_os_error(error)}') from error
        return command_text('', saved['entry'], saved['args'])
    subprocess.Popen(command, cwd=str(project))
    return ' '.join(command)


# ---- the look of a project (Project preferences: kept with the project, never global) -------------------------------------------------
def look(project):
    """(light, outer colour or None) saved for this project. A project that has none looks like the default: dark, the theme's own colour."""
    state = load_state(project)
    return state.get('theme', 'dark') == 'light', state.get('outer_color') or None


def save_look(project, light, outer):
    state = load_state(project)
    state['theme'] = 'light' if light else 'dark'
    if outer:
        state['outer_color'] = outer
    else:
        state.pop('outer_color', None)
    save_state(project, state)


# ---- Developer, organization and license of a project (Project > License settings…, Project > New…); the record travels in the project's config ------------------
LICENSE_DEFAULTS_FILE = Path(__file__).resolve().parents[1] / 'data' / 'license_defaults.json'
LICENSE_TEXTS = zpath(ZYGOTE_ROOT, 'assets', 'licenses')              # the standard license texts, as data (Apache, GPL and MPL word for word)
LICENSE_TYPES = ('MIT', 'Apache-2.0', 'BSD-3-Clause', 'GPL-3.0', 'MPL-2.0', 'Custom')
LICENSE_FILE = 'LICENSE'
LICENSE_KEYS = ('developer', 'developer_copyright', 'organization', 'organization_copyright', 'year', 'type', 'file')


def license_defaults():
    """What a project starts with: the names Luis declared in data/license_defaults.json, this year, no license type yet."""
    try:
        data = json.loads(LICENSE_DEFAULTS_FILE.read_text(encoding='utf-8'))
        return {'developer': str(data['developer']), 'developer_copyright': bool(data['developer_copyright']), 'organization': str(data['organization']),
                'organization_copyright': bool(data['organization_copyright']), 'year': str(now().year), 'type': str(data.get('type', '')), 'file': LICENSE_FILE}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ZygoteError(f'The license defaults cannot be read ({LICENSE_DEFAULTS_FILE}): {error}') from error


def check_license(record):
    """The record as it is saved (every key, the right kinds). A wrong type or an unsafe file path is refused, never repaired."""
    if not isinstance(record, dict):
        raise ZygoteError('The license record must be a table of settings.')
    out = {'developer': str(record.get('developer', '')).strip(), 'developer_copyright': bool(record.get('developer_copyright', False)),
           'organization': str(record.get('organization', '')).strip(), 'organization_copyright': bool(record.get('organization_copyright', False)),
           'year': str(record.get('year', '')).strip(), 'type': str(record.get('type', '')).strip(), 'file': str(record.get('file', '') or LICENSE_FILE).strip().replace('\\', '/')}
    if out['type'] and out['type'] not in LICENSE_TYPES:
        raise ZygoteError(f'The license type {out["type"]!r} is not one of: {", ".join(LICENSE_TYPES)}.')
    if out['year'] and not re.fullmatch(r'\d{4}(\s*[-,]\s*\d{4})*', out['year']):
        raise ZygoteError(f'The year {out["year"]!r} is not a year (write 2026 or 2024-2026).')
    if out['file'].startswith('/') or re.match(r'^[A-Za-z]:', out['file']) or '..' in out['file'].split('/'):
        raise ZygoteError(f'The license file {out["file"]!r} must be a path inside the project.')
    return out


def license_record(project):
    """The saved record, or None when the project has none yet."""
    saved = load_state(project).get('license')
    return check_license(saved) if saved else None


def save_license(project, record):
    state = load_state(project)
    state['license'] = check_license(record)
    save_state(project, state)
    return state['license']


def copyright_names(record):
    return ', '.join(name for name, ticked in ((record['developer'], record['developer_copyright']), (record['organization'], record['organization_copyright'])) if ticked and name)


def license_notice(project):
    """The one line a project shows (About box, deploy.json): "© 2026 Luis R. Lopez, RedHorseVR. Licensed under MIT (see LICENSE)." A missing part is left out; '' when
    the project has no record or nothing to say."""
    record = license_record(project)
    if not record:
        return ''
    parts = []
    names = copyright_names(record)
    if names:
        parts.append(f'\u00a9 {record["year"] + " " if record["year"] else ""}{names}.')
    if record['type']:
        if record['type'] == 'Custom':
            parts.append(f'License: see {record["file"]}.')
        else:
            parts.append(f'Licensed under {record["type"]}' + (f' (see {record["file"]}).' if (Path(project) / record['file']).is_file() else '.'))
    return ' '.join(parts)


def license_text(record):
    """The text of a standard license for this record (the copyright line filled in where the license has one). Custom has no standard text: raises."""
    if record['type'] not in LICENSE_TYPES or record['type'] == 'Custom':
        raise ZygoteError('A custom license has no standard text: put your own file in the project and choose it.')
    text = (LICENSE_TEXTS / f'{record["type"]}.txt').read_text(encoding='utf-8')
    line = f'Copyright (c) {record["year"] + " " if record["year"] else ""}{copyright_names(record) or "the authors"}'
    return text.replace('{copyright}', line)


def own_license_file(project, record=None):
    """The project's license file as the License settings box shows it: the file's relative name when the project has a license file that is its own (the record says
    Custom, or the record has no type and the LICENSE file is there), else ''. A LICENSE that Zygote wrote for a standard type is not "its own"."""
    record = record or license_record(project) or {'type': '', 'file': LICENSE_FILE}
    if record['type'] not in ('', 'Custom'):
        return ''
    return record['file'] if (clean_path(project) / record['file']).is_file() else ''


def license_file_in_the_way(project, record):
    """True when a standard type would be written and the project's file of that name holds something else (so the person is asked first)."""
    record = check_license(record)
    target = clean_path(project) / record['file']
    if record['type'] in ('', 'Custom') or not target.is_file():
        return False
    return target.read_text(encoding='utf-8', errors='replace') != license_text(record)


def backup_license(project, rel):
    """Rename a license file to <name>.old (never a delete); when that name is taken, to <name>.<date time>.old, then with a number. Returns the new name."""
    root = clean_path(project)
    source = root / rel
    stamp = now().strftime('%Y%m%d-%H%M%S')
    target, number = root / f'{rel}.old', 1
    if target.exists():
        target = root / f'{rel}.{stamp}.old'
    while target.exists():
        number += 1
        target = root / f'{rel}.{stamp}-{number}.old'
    source.rename(target)
    return target.name


def write_license_file(project, record, replace=False):
    """Put the license file in the project: 'written' (there was none), 'replaced' (replace=True: the old one was renamed to LICENSE.old first), 'kept' (a file of that
    name exists and replace is False: never replaced), 'none' (no type, or Custom)."""
    record = check_license(record)
    if not record['type'] or record['type'] == 'Custom':
        return 'none'
    target = clean_path(project) / record['file']
    status = 'written'
    if target.exists():
        if not replace:
            return 'kept'
        if target.read_text(encoding='utf-8', errors='replace') == license_text(record):
            return 'kept'                                          # the same text is there already: nothing to back up
        backup_license(project, record['file'])
        status = 'replaced'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(license_text(record), encoding='utf-8')
    return status


def adopt_license_file(project, source):
    """Browse in the License settings box: a license file the person found. One inside the project is used where it is; one outside is copied to LICENSE (an old LICENSE
    is renamed to LICENSE.old first). Returns the relative name the record takes (type Custom)."""
    root, source = clean_path(project), clean_path(source)
    if not source.is_file():
        raise ZygoteError(f'The license file is not a file: {source}')
    rel = project_relative(root, source)
    if rel:
        return rel
    target = root / LICENSE_FILE
    if target.exists():
        backup_license(root, LICENSE_FILE)
    shutil.copy2(source, target)
    return LICENSE_FILE


def check_new_project(parent, name):
    """The folder a new project would be: parent/name. The name must be a plain folder name and the folder must not be there already (nothing is ever overwritten)."""
    parent = Path(parent)
    if not parent.is_dir():
        raise ZygoteError(f'The folder {parent} is not there.')
    check_item_name((name or '').strip())
    folder = parent / name.strip()
    if folder.exists():
        raise ZygoteError(f'{folder} is there already. Pick another name or another folder (a new project never replaces a folder).')
    return folder


def create_project(parent, name, record):
    """Project > New…: make the folder, give it the Zygote baseline, the license record and (for a standard license) its file. Returns the folder."""
    folder = check_new_project(parent, name)
    record = dict(record)
    source = record.pop('source', '')                          # a license file found with Browse… in the dialog
    record = check_license(record)
    folder.mkdir()
    try:
        adopt_project(folder, name.strip())
        set_project_name(folder, name.strip())
        if source:
            record.update(type='Custom', file=adopt_license_file(folder, source))
        save_license(folder, record)
        write_license_file(folder, record)
        copy_icon_set(folder)
        update_core(folder)                                        # the project starts with its own copy of this Zygote: its first open asks nothing
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)                  # a half-made project is not left behind
        raise
    return clean_path(folder)


# ---- Project history: .zygote\notes\PROJECT_HISTORY.json (travels with the project; dates are inside the data) ---------------------
HISTORY_REL = TREE + '/notes/PROJECT_HISTORY.json'


def history_path(project):
    return Path(project) / HISTORY_REL


def load_history(project):
    path = history_path(project)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise ZygoteError(f'{path} is damaged ({error}). Fix or delete it.') from error


def save_history(project, data):
    path = history_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def record_event(project, what, drop=None):
    """Add one dated line to the project's history. Only a project that has an app tree keeps a history (a plain folder is left alone).
    The first line also records the Zygote version the history started with. True when written."""
    if not (Path(project) / TREE).is_dir():
        return False
    data = load_history(project)
    tool = tool_version()
    if not data:
        data = {'started_with': tool, 'last_upgraded_to': tool, 'events': []}
    event = {'when': now().isoformat(timespec='seconds'), 'zygote': tool, 'what': what}
    if drop:
        event['drop'] = drop                                   # {zip, before, after, changed, kept, overridden}: what a dropped ZIP did, for the history window
    data['events'].append(event)
    save_history(project, data)
    return True


def note_tool_version(project):
    """When a project is opened: the first time it starts the history; later, a line only when the running Zygote differs from the last one
    that opened it. Returns the line written, or None."""
    if not (Path(project) / TREE).is_dir():
        return None
    data = load_history(project)
    tool = tool_version()
    if not data:
        line = f'History started: first opened with Zygote {tool}'
    elif data.get('last_upgraded_to') != tool:
        before = data.get('last_upgraded_to')
        line = f'Opened with Zygote {tool} (before: {before}; {version_direction(before, tool)})'
    else:
        return None
    record_event(project, line)
    data = load_history(project)
    data['last_upgraded_to'] = tool
    save_history(project, data)
    return line


# ---- History archive: the entries up to a chosen one are packed into a ZIP in the notes folder and replaced by one line ------------------
ARCHIVE_PREFIX = 'HISTORY_ARCHIVE_'


def entry_count(event):
    """How many real entries an event stands for (an archive line stands for the ones inside it)."""
    return event['archive']['count'] if event.get('archive') else 1


def archive_history(project, last_index):
    """Pack events 0..last_index into HISTORY_ARCHIVE_<number>.zip (events.json inside) and put one archive line in their place. The ZIP is written and read back
    before the history changes. Returns the archive line (a dict with 'archive': zip, count, first, last)."""
    data = load_history(project)
    events = data.get('events', [])
    if not 0 <= last_index < len(events):
        raise ZygoteError('There is no such history entry to archive up to.')
    packed = events[:last_index + 1]
    folder = history_path(project).parent
    number = 1
    while (folder / f'{ARCHIVE_PREFIX}{number:03d}.zip').exists():
        number += 1
    name = f'{ARCHIVE_PREFIX}{number:03d}.zip'
    with zipfile.ZipFile(folder / name, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('events.json', json.dumps(packed, indent=2))
    if len(read_archive(project, name)) != len(packed):
        raise ZygoteError(f'{name} could not be read back: the history was not changed.')
    count = sum(entry_count(one) for one in packed)
    line = {'when': packed[0]['when'], 'zygote': tool_version(), 'what': f'Archived {count} entries', 'archive': {'zip': name, 'count': count, 'first': packed[0]['when'], 'last': packed[-1]['when']}}
    data['events'] = [line] + events[last_index + 1:]
    save_history(project, data)
    return line


def read_archive(project, name):
    """The events inside an archive ZIP of this project's notes folder."""
    path = history_path(project).parent / name
    if not path.is_file():
        raise ZygoteError(f'The archive {name} was not found in {path.parent}.')
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('events.json').decode('utf-8'))


def unpack_archive(project, name):
    """Put the entries of an archive back into the history for good (the archive line is replaced by them). The ZIP stays on disk."""
    data = load_history(project)
    events = data.get('events', [])
    for index, event in enumerate(events):
        if event.get('archive', {}).get('zip') == name:
            data['events'] = events[:index] + read_archive(project, name) + events[index + 1:]
            save_history(project, data)
            return
    raise ZygoteError(f'The history has no line for the archive {name}.')


def history_text(project):
    """The history as plain text for the Project history window."""
    data = load_history(project)
    if not data:
        raise ZygoteError('This project has no history yet. It starts when the project is opened with a .zygote folder in it.')
    lines = [f'Started with Zygote:       {data.get("started_with", "?")}',
             f'Last opened with Zygote:   {data.get("last_upgraded_to", "?")}', '', 'Events (oldest first):']
    for event in data.get('events', []):
        lines.append(f'  {datetime.datetime.fromisoformat(event["when"]):%Y-%m-%d %H:%M}   [Zygote {event.get("zygote", "?")}]   {event.get("what", "")}')
    return '\n'.join(lines) + '\n'


# ---- Edit button of Project help ------------------------------------------------------------------------------------------
def edit_file(path):
    """Open a file in a text editor: the program chosen for its type in Settings > Tools, else Notepad. 1 process per press."""
    path = Path(path)
    if not path.is_file():
        raise ZygoteError(f'The file was not found: {path}')
    run_program(program_for(path) or NOTEPAD, path)


# ---- the test dialog: list the tests, run them once per press, follow the output line by line ---------------------------------------
TESTS_REL = TREE + '/tests'


def list_tests(project):
    """The tests found in app_tree\\tests\\test*.py as ids 'module.Class.test_name', read from the source (no process)."""
    import ast
    folder = Path(project) / TESTS_REL
    if not folder.is_dir():
        raise ZygoteError(f'This project has no tests folder ({TESTS_REL.replace("/", chr(92))}).')
    ids = []
    for path in sorted(folder.glob('test*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except SyntaxError as error:
            raise ZygoteError(f'{path.name} cannot be read: {error}') from error
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                ids.extend(f'{path.stem}.{node.name}.{item.name}' for item in node.body
                           if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith('test'))
    if not ids:
        raise ZygoteError(f'No tests were found in {folder}.')
    return ids


def test_python(project):
    """The project's own Python (its .zygote\\env). Raises when it has none: a test run never borrows another interpreter."""
    for rel in (DOT + '/env/Scripts/python.exe', DOT + '/env/bin/python'):
        if (Path(project) / rel).is_file():
            return str(Path(project) / rel)
    raise ZygoteError(f'This project has no environment ({DOT}\\env), so its tests cannot run. Run the project once so its environment is built.')


def test_command(project):
    return [test_python(project), '-m', 'unittest', 'discover', '-s', TESTS_REL, '-v']


class TestStream:
    """Reads the verbose output of `python -m unittest -v` as it arrives and says which test started and how each ended.
    feed(text) returns events: ('start', id) and ('done', id, status). Output that is not a test line is ignored here."""
    __test__ = False
    HEAD = re.compile(r'^(\w+) \(([\w.]+)\)(.*)$')
    PARTIAL = re.compile(r'^(\w+) \(([\w.]+)\) \.\.\.')
    STATUSES = ('ok', 'FAIL', 'ERROR', 'expected failure', 'unexpected success')

    def __init__(self):
        self.buffer = ''
        self.pending = None             # a test whose line has been seen but whose result has not
        self.announced = None           # the test already announced from a half-written line

    @staticmethod
    def test_id(name, dotted):
        return dotted if dotted.endswith('.' + name) else f'{dotted}.{name}'

    @classmethod
    def status_of(cls, text):
        text = text.strip()
        return text if text in cls.STATUSES or text.startswith('skipped') else None

    def feed(self, text):
        self.buffer += text
        lines = self.buffer.split('\n')
        self.buffer = lines.pop()
        events = []
        for line in lines:
            events.extend(self.line(line.rstrip('\r')))
        match = self.PARTIAL.match(self.buffer)
        if match:
            found = self.test_id(match.group(1), match.group(2))
            if found != self.announced:
                self.announced = found
                self.pending = found
                events.append(('start', found))
        return events

    def line(self, line):
        events = []
        head = self.HEAD.match(line)
        if head:
            found = self.test_id(head.group(1), head.group(2))
            if found != self.announced:
                events.append(('start', found))
            self.announced = None
            self.pending = found
            rest = head.group(3)
            status = self.status_of(rest[5:]) if rest.startswith(' ... ') else None
        elif self.pending is not None:
            status = self.status_of(line.rsplit(' ... ', 1)[1] if ' ... ' in line else line)
        else:
            return events
        if status is not None:
            events.append(('done', self.pending, status))
            self.pending = None
        return events


# ---- the folder view's own file operations (no Qt in here: a window, or later a web page, calls these) ---------------------
TRASH_REL = '.zygote/user/trash'
PROTECTED_FILES = ('START_HERE.md',)                       # blue files at the project's top, next to zip: never thrown away by accident (a build ZIP still updates them)
EDITABLE_SYSTEM_FILES = ('.gitignore', '.gitmodules')       # right after the blue files, shown green: the person may open and edit them (.gitignore is never deleted)
SYSTEM_TOP = ('.zygote', '.git', 'zip', '.gitignore') + PROTECTED_FILES      # what belongs to Zygote's own structure, not to the person's work


def project_relative(project, path):
    """The path inside the project as 'a/b' (posix), '' for the project itself, None when it lies outside the project."""
    try:
        rel = Path(path).relative_to(Path(project)).as_posix()
    except ValueError:
        return None
    return '' if rel == '.' else rel


def system_block(project=None):
    """The top-level names of what the person cannot change as work, in the order the workbench shows them after the recycle bin: the launcher (the project's
    own name for it, Zygote's shortcut), then the blue folders (.git, .zygote, zip), then the blue files (START_HERE.md), then the green editable ones (.gitignore, .gitmodules), then the other system files."""
    blue = [name for name in SACRED if '/' not in name]
    launchers = [path.name for path in find_launchers(project)] if project is not None else [LAUNCHER_NAME]
    return (launchers + ['.git', '.zygote', 'zip'] + list(PROTECTED_FILES) + list(EDITABLE_SYSTEM_FILES) + [name for name in blue if name not in ('.git', 'zip')]
            + [name for name in SYSTEM_TOP if name not in blue and name != '.zygote' and name not in PROTECTED_FILES + EDITABLE_SYSTEM_FILES])


def is_working(project, path):
    """True for what the person works on: inside the project, and not Zygote's own structure (.zygote, .git, zip, .gitignore, the launcher)."""
    rel = project_relative(project, path)
    if not rel:
        return False
    return not any(under(rel, name) for name in SYSTEM_TOP) and not ('/' not in rel and is_live_launcher_name(rel))      # an older "Run project.exe" is the person's to throw away


def is_app_tree(project, path):
    """True for the app_tree folder itself (it is green and wears Zygote's stamp, though it cannot be thrown away)."""
    return project_relative(project, path) == TREE


def folder_picture(project, path):
    """The picture file that stands for a folder of the project's top level by its name (app_tree: the tree, app: source, Libs: bricks, extras: blocks, deploy: the rocket; START_HERE.md: the brain and book; any letter case), else None."""
    rel = project_relative(project, path)
    return None if rel is None else layout_picture(rel)


def layout_picture(name):
    """The picture that stands for a top-level name (any letter case), else None. The one table: the Workbench and the standard-layout panel use it."""
    names = {TREE: APP_TREE_ICON, 'app': SOURCE_ICON, 'libs': BRICKS_ICON, 'extras': EXTRAS_ICON, 'deploy': DEPLOY_ICON, 'start_here.md': START_HERE_ICON}
    return names.get(str(name).lower())


def is_yellow(project, path):
    """True for a FILE inside the zip folder (the snapshots, undo files and ZIPs, which grow large): zip itself is blue, the files in it are the person's to clear.
    Everything else the person may throw away is plain work (the app tree and the rest of the project), see can_trash."""
    rel = project_relative(project, path)
    return bool(rel) and rel != 'zip' and under(rel, 'zip') and Path(path).is_file()


def can_trash(project, path):
    """What goes to the trash: working items (the app tree's folders and files too, but not the app_tree folder itself) and the files in zip. The project itself and
    the blue (sacred and frozen) items never do."""
    if is_yellow(project, path):
        return True
    rel = project_relative(project, path)
    return rel != TREE and is_working(project, path) and not is_sacred(rel)


def trash_path(project, path, leftover=False):
    """Move one item into .zygote\\user\\trash (one slot folder per item, with from.json saying where it came from). Returns the slot.
    leftover: a folder the update's own cleanup list names (app_tree\\assets\\cleanup.json, asked once): the one way into the recycle bin for something inside .zygote."""
    project, path = Path(project), Path(path)
    if not leftover and not can_trash(project, path):
        raise ZygoteError(f'{path.name} cannot be thrown away: only the files and folders you work on can (not the project itself, .zygote, .git, zip, START_HERE.md or the launcher).')
    if not path.exists():
        raise ZygoteError(f'{path} does not exist.')
    slot = project / TRASH_REL / uuid.uuid4().hex[:8]
    slot.mkdir(parents=True)
    (slot / 'from.json').write_text(json.dumps({'from': project_relative(project, path), 'when': now().isoformat(timespec='seconds')}, indent=2) + '\n', encoding='utf-8')
    shutil.move(str(path), str(slot / path.name))
    return slot


# ---- the workbench as a small operating system: new folder / text / bitmap, copy, paste, rename ------------------------------------
NEW_ITEMS = {'folder': 'New folder', 'text': 'New Text Document.txt', 'bitmap': 'New Bitmap Image.bmp'}
BAD_NAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {'con', 'prn', 'aux', 'nul'} | {f'com{n}' for n in range(1, 10)} | {f'lpt{n}' for n in range(1, 10)}


def can_create_in(project, folder):
    """True for a folder where the person may make things: the project's own folder, or a folder they work in (never .zygote, .git, zip or a blue folder)."""
    folder = Path(folder)
    if not folder.is_dir():
        return False
    if project_relative(project, folder) == '':
        return True
    return can_trash(project, folder)


def can_copy(project, path):
    """Only what the person works on is copied (the same set that may be thrown away: never the project, .zygote, .git, zip or a launcher)."""
    return can_trash(project, path)


def blank_bitmap():
    """The bytes of a valid, all-white 32 x 32 bitmap (24 bits): Paint opens it as a blank picture. Data, not code."""
    side, row = 32, 32 * 3
    pixels = b'\xff' * (row * side)
    header = b'BM' + (54 + len(pixels)).to_bytes(4, 'little') + bytes(4) + (54).to_bytes(4, 'little')
    info = (40).to_bytes(4, 'little') + side.to_bytes(4, 'little') + side.to_bytes(4, 'little') + (1).to_bytes(2, 'little') + (24).to_bytes(2, 'little') \
        + bytes(4) + len(pixels).to_bytes(4, 'little') + (2835).to_bytes(4, 'little') * 2 + bytes(8)
    return header + info + pixels


def free_name(folder, name, copy=False):
    """A name that is not taken in the folder: "New folder", "New folder (2)"; for a copy "a - Copy.txt", "a - Copy (2).txt" (the way Windows does it)."""
    folder = Path(folder)
    stem, suffix = (name, '') if (folder / name).is_dir() or '.' not in name.strip('.') else (Path(name).stem, Path(name).suffix)
    first = f'{stem} - Copy{suffix}' if copy else name
    candidate, number = first, 1
    while (folder / candidate).exists():
        number += 1
        base = f'{stem} - Copy' if copy else stem
        candidate = f'{base} ({number}){suffix}'
    return candidate


def new_item(project, folder, kind):
    """Make a new folder, an empty text document or a blank bitmap in a folder the person works in. Returns the new path."""
    if kind not in NEW_ITEMS:
        raise ZygoteError(f'Unknown new item "{kind}". Known: {", ".join(NEW_ITEMS)}.')
    folder = Path(folder)
    if not can_create_in(project, folder):
        raise ZygoteError(f'Nothing can be made in {folder.name}: it belongs to Zygote. Make it in the project folder or a folder you work in.')
    path = folder / free_name(folder, NEW_ITEMS[kind])
    if kind == 'folder':
        path.mkdir()
    elif kind == 'text':
        path.write_bytes(b'')
    else:
        path.write_bytes(blank_bitmap())
    return path


def check_item_name(name):
    """Fail loudly on a name Windows would refuse (the message says which rule)."""
    if not name or not name.strip():
        raise ZygoteError('The name is empty. Type a name.')
    if name != name.strip() or name.endswith('.'):
        raise ZygoteError(f'"{name}": a name cannot start or end with a space, or end with a dot.')
    if BAD_NAME_CHARACTERS.search(name):
        raise ZygoteError(f'"{name}": a name cannot hold any of  < > : " / \\ | ? *')
    if name.split('.')[0].lower() in RESERVED_NAMES:
        raise ZygoteError(f'"{name}" is a name Windows keeps for itself (CON, PRN, AUX, NUL, COM1-9, LPT1-9). Pick another one.')


def rename_item(project, path, new_name):
    """Rename one item the person works on, in the same folder. A name that is taken is refused (nothing is replaced). Returns the new path."""
    path = Path(path)
    if not can_copy(project, path):
        raise ZygoteError(f'{path.name} cannot be renamed: only the files and folders you work on can (not the project itself, .zygote, .git, zip or the launcher).')
    if not path.exists():
        raise ZygoteError(f'{path} does not exist.')
    check_item_name(new_name)
    target = path.with_name(new_name)
    if new_name == path.name:
        return path
    if target.exists() and new_name.casefold() != path.name.casefold():
        raise ZygoteError(f'Not renamed: {new_name} is there already in {path.parent.name}.')
    os.rename(path, target)
    return target


def can_move_into(project, folder):
    """True for a folder that green items may be moved into: any folder where the person may make things, and also the app_tree folder itself (it cannot be thrown away,
    but its contents are the person's)."""
    folder = Path(folder)
    if folder.is_dir() and project_relative(project, folder) == TREE:
        return True
    return can_create_in(project, folder)


def can_move(project, path):
    """True for what the person may move: the green items (working files and folders). Never the project, app_tree itself, .zygote, .git, zip, the blue items or a launcher;
    and not the files of the zip folder (they stay there)."""
    return is_working(project, path) and not is_yellow(project, path) and can_copy(project, path)


def move_into(project, sources, folder):
    """Move green files and folders into a folder where they may go. Everything is checked first: when one item is refused, nothing at all is moved and the error names it.
    Nothing is replaced (a name that is taken in the folder refuses the move). Returns the new paths."""
    folder = Path(folder)
    if not can_move_into(project, folder):
        raise ZygoteError(f'Nothing can be moved into {folder.name}: it belongs to Zygote.')
    plan = []
    for source in map(Path, sources):
        if not source.exists():
            raise ZygoteError(f'{source.name} is not there any more.')
        if not can_move(project, source):
            raise ZygoteError(f'{source.name} cannot be moved: only the green files and folders you work on can (not the project, app_tree itself, .zygote, .git, zip or the launcher).')
        if source.is_dir() and (folder == source or source in folder.parents):
            raise ZygoteError(f'A folder cannot be moved into itself: {source.name}.')
        target = folder / source.name
        if source.parent == folder:
            continue                                              # already there: nothing to do
        if target.exists():
            raise ZygoteError(f'Not moved: {source.name} is there already in {folder.name}.')
        if any(target == other for _, other in plan):
            raise ZygoteError(f'Not moved: two items are both called {source.name}.')
        plan.append((source, target))
    made = []
    for source, target in plan:
        try:
            shutil.move(str(source), str(target))
        except OSError as error:
            raise ZygoteError(f'Not moved: {source.name} ({error}). Moved before it: {len(made)}.')
        made.append(target)
    return made


def copy_into(project, sources, folder):
    """Copy the sources into a folder the person works in, each under a free name ("a - Copy.txt" when the name is taken). Returns the new paths.
    A folder cannot be copied into itself. Nothing is replaced."""
    folder = Path(folder)
    if not can_create_in(project, folder):
        raise ZygoteError(f'Nothing can be pasted into {folder.name}: it belongs to Zygote.')
    made = []
    for source in map(Path, sources):
        if not source.exists():
            raise ZygoteError(f'{source.name} is not there any more: it was moved or thrown away after it was copied.')
        if not can_copy(project, source):
            raise ZygoteError(f'{source.name} cannot be copied (only what you work on can).')
        if source.is_dir() and (folder == source or source in folder.parents):
            raise ZygoteError(f'A folder cannot be pasted into itself: {source.name}.')
        target = folder / free_name(folder, source.name, copy=(folder / source.name).exists())
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        made.append(target)
    return made


def copy_in_from_outside(project, sources, folder):
    """Things dropped from the desktop or Explorer, copied into the folder in view (a folder where the person works, never .zygote, .git, zip or a blue folder).
    Each goes under a free name; nothing is replaced and nothing is moved or removed at the source. Returns the new paths."""
    folder = Path(folder)
    if not can_create_in(project, folder):
        raise ZygoteError(f'Nothing can be copied into {folder.name}: it belongs to Zygote. Open a folder you work in first.')
    made = []
    for source in map(Path, sources):
        if not source.exists():
            raise ZygoteError(f'{source.name} is not there any more.')
        if source.is_dir() and (folder == source or source in folder.parents):
            raise ZygoteError(f'A folder cannot be copied into itself: {source.name}.')
        target = folder / free_name(folder, source.name, copy=(folder / source.name).exists())
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        made.append(target)
    return made


def fallback_folder(view, thrown):
    """The folder to show after items were thrown away: None when the folder in view is still there, else the nearest folder above the
    highest thrown item that holds it (plain path logic, no disk access)."""
    view = Path(view)
    gone = [Path(path) for path in thrown if Path(path) == view or Path(path) in view.parents]
    if not gone:
        return None
    return min(gone, key=lambda path: len(path.parts)).parent


def trash_folder(project):
    """The folder that holds the trash slots (it may not exist while nothing was thrown away)."""
    return Path(project) / TRASH_REL


def trash_items(project):
    """What is in the trash, newest first: dicts with slot, name, from (the place it came from) and when."""
    room = Path(project) / TRASH_REL
    found = []
    for slot in sorted(room.iterdir()) if room.is_dir() else []:
        record = slot / 'from.json'
        if slot.is_dir() and record.is_file():
            data = json.loads(record.read_text(encoding='utf-8'))
            names = [item.name for item in slot.iterdir() if item.name != 'from.json']
            found.append({'slot': slot, 'name': names[0] if names else '?', 'from': data['from'], 'when': data['when']})
    return sorted(found, key=lambda item: item['when'], reverse=True)


def restore_item(project, slot, folder=None):
    """Put a thrown-away item back: where it came from, or into `folder` (dragged out of the bin onto a folder). Raises when something with that
    name is there now (nothing is overwritten); the item then stays in the trash."""
    slot = Path(slot)
    data = json.loads((slot / 'from.json').read_text(encoding='utf-8'))
    name = Path(data['from']).name
    target = (Path(folder) / name) if folder is not None else Path(project) / data['from']
    if target.exists():
        raise ZygoteError(f'{target.name} exists in {target.parent.name or target.parent}; rename or throw that one away first. The trashed one stays in the trash.')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(slot / name), str(target))
    shutil.rmtree(slot)
    return target


def empty_trash(project, slots=None):
    """Delete thrown-away items for good (the window asks first): the given slots, or all of them. Returns how many went."""
    wanted = {str(slot) for slot in slots} if slots is not None else None
    count = 0
    for item in trash_items(project):
        if wanted is None or str(item['slot']) in wanted:
            shutil.rmtree(item['slot'])
            count += 1
    return count


def subfolders(path):
    """The names of the folders inside a folder (empty for one that cannot be read)."""
    try:
        with os.scandir(path) as entries:
            return sorted(entry.name for entry in entries if entry.is_dir(follow_symlinks=False))
    except OSError:
        return []


def list_folder(path):
    """What is in a folder, read without Qt: a list of (name, is_dir, size, modified). A folder that cannot be read gives an empty list."""
    found = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    info = entry.stat(follow_symlinks=False)
                    found.append((entry.name, is_dir, 0 if is_dir else info.st_size, info.st_mtime))
                except OSError:
                    found.append((entry.name, False, 0, 0.0))
    except OSError:
        return []
    return found


def read_ahead_plan(project, shown, limit=60):
    """The folders to read ahead of being asked, most likely first: the folder shown, the person's own folders (and their folders one level
    down), and only when the person is already inside .zygote: its folders, with env last. Nothing else is read before it is asked for."""
    project, shown = Path(project), Path(shown)
    shown_rel = project_relative(project, shown) or ''
    inside_system = any(under(shown_rel, name) for name in SYSTEM_TOP)          # the person is already in .zygote (or .git, zip): its folders may be read
    plan = [shown]
    plan += [shown / name for name in subfolders(shown) if inside_system or is_working(project, shown / name)]
    work = [project / name for name in subfolders(project) if is_working(project, project / name)]
    plan += work
    for folder in work:
        plan += [folder / name for name in subfolders(folder)]
    rel = project_relative(project, shown) or ''
    if under(rel, '.zygote'):
        names = subfolders(project / '.zygote')
        plan += [project / '.zygote' / name for name in names if name != 'env'] + ([project / '.zygote' / 'env'] if 'env' in names else [])
    seen, ordered = set(), []
    for folder in plan:
        if folder not in seen:
            seen.add(folder)
            ordered.append(folder)
    return ordered[:limit]


def is_editable_system_file(rel):
    """True for .gitignore and .gitmodules at the project's top: shown green, the person may edit them."""
    return rel in EDITABLE_SYSTEM_FILES
