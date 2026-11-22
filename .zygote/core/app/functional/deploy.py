"""Deploy (Z 2.19.4): one self-extracting program that holds the project's program files. Run on another computer it unpacks a folder named
<project>_home beside itself and starts the program from there (it builds the folder's own Python environment first when the project names a
requirements file). The exe is named like the project (VFlow.exe) and written to the deploy folder at the project's top. Make ZIP stays what it was: a snapshot of the project.
What goes in: ONLY what app_tree/dependencies.json (hand-written by the project: name, path, type, kind required/optional, why) lists: its required entries and the optional ones ticked in the dialog, each at its own path (app_tree and .zygote pieces included). No such file: Deploy refuses. Plus deploy.json (data:
name, entry, args, requirements, window) and deploy_run.py (the hand-written start script of app_tree\\tools\\deploy, copied, never generated).
A project that cannot be deployed this way (no Python entry point) is refused with the reason: no fallback."""
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from functional import core
from functional.core import ZygoteError

RUN_SCRIPT = core.zpath(core.ZYGOTE_ROOT, 'tools', 'deploy', 'deploy_run.py')
OUTPUT_REL = 'deploy'                                       # at the project's top, easy to see (not inside zip)


def settings(project):
    """What this project saved for Deploy: requirements (relative path or ''), window (bool), args (text; empty = none: the arguments of the Runtime settings are for
    testing and never travel), include / exclude (the optional entries the person ticked / unticked)."""
    saved = core.load_state(project).get('deploy', {})
    return {'requirements': saved.get('requirements', ''), 'window': bool(saved.get('window', True)), 'args': saved.get('args', ''),
            'include': list(saved.get('include', [])), 'exclude': list(saved.get('exclude', []))}


DEPENDENCIES = 'app_tree/dependencies.json'   # written by hand by the project: what a deployed program cannot run without
ALWAYS_LEFT_OUT = ('.zygote/user', '.zygote/credentials', '.zygote/logs', '.zygote/env', '.git', 'zip',
                   'app_tree/tests', 'app_tree/notes', 'START_HERE.md')   # the machine's own and the build side's (tests, notes, the hand-over file): never carried and never offered, whatever a list says
KINDS, TYPES = ('required', 'optional'), ('folder', 'file', 'runtime')


def dependencies(project):
    """The project's app_tree/dependencies.json as a dict. Deploy reads this file and nothing else to decide what is packaged: a project without it, or with a
    wrong one, is refused with the reason (no guessing, no fallback)."""
    path = core.clean_path(project) / DEPENDENCIES
    if not path.is_file():
        raise ZygoteError(f'Deploy needs {DEPENDENCIES}: the list of what the deployed program cannot run without (DOCTRINE, Builds and releases). The project has none.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise ZygoteError(f'{DEPENDENCIES} is not valid JSON: {error}') from error
    entries = data.get('dependencies') if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ZygoteError(f'{DEPENDENCIES} has no "dependencies" list.')
    for one in entries:
        if not isinstance(one, dict) or not one.get('name') or not one.get('path') or one.get('kind') not in KINDS or one.get('type') not in TYPES:
            raise ZygoteError(f'{DEPENDENCIES}: every entry needs name, path, type (folder, file or runtime) and kind (required or optional): {one}')
    return data


def _clean(rel):
    return str(rel).replace('\\', '/').strip('/')


def section_of(key, need):
    """The group a dialog item belongs to, by where it sits: optional ones are their own group; of the required ones the version files, the assets folder,
    the Zygote core pieces (.zygote/core) and the rest (the program itself)."""
    if not need:
        return 'Optional (your choice)'
    if key.rsplit('/', 1)[-1] == 'VERSION.txt':
        return 'Versions'
    if key == 'app_tree/assets' or key.startswith('app_tree/assets/'):
        return 'Assets'
    if key.startswith('.zygote/core/'):
        return 'Zygote core components'
    return 'Program (required)'


SECTION_ORDER = ('Optional (your choice)', 'Program (required)', 'Assets', 'Versions', 'Zygote core components')


def choices(project):
    """The list the dialog shows: [{'key', 'label', 'why', 'required', 'ticked', 'section'}], the optional ones first and the required ones last. Required entries
    are locked on, optional ones start unticked; the project says why each is there. Entries of type runtime are not here (see runtime_needs). What Deploy never
    carries (ALWAYS_LEFT_OUT: tests, notes, START_HERE.md ...) is not offered; a project that lists such a path as required is told so."""
    saved, out = settings(project), []
    never = _never(project)
    for one in dependencies(project)['dependencies']:
        if one['type'] == 'runtime':
            continue
        key, need = _clean(one['path']), one['kind'] == 'required'
        if _left_out(key, never):
            if need:
                raise ZygoteError(f'{DEPENDENCIES} lists {key} as required, but Deploy never carries it (tests, notes and the hand-over file are not part of a program).')
            continue
        out.append({'key': key, 'label': f"{one['name']}  ({key})", 'why': one.get('why', ''), 'required': need, 'ticked': need or key in saved['include'],
                    'section': section_of(key, need)})
    return sorted(out, key=lambda one: one['required'])        # stable: optional first, required last


def sections(project):
    """The dialog's groups in the order shown: [(title, [choice, ...])]; an empty group is left out."""
    items = choices(project)
    return [(title, [one for one in items if one['section'] == title]) for title in SECTION_ORDER if any(one['section'] == title for one in items)]


REQUIREMENTS_PLACES = ('requirements.txt', 'app/requirements.txt', 'app_tree/requirements.txt')


def requirements_offer(project):
    """The requirements file the dialog offers, as (relative path, ticked), or None when the project has none (then the dialog shows nothing about packages).
    The one saved earlier counts when it is still there; else requirements.txt at the top, in app or in app_tree. It starts ticked."""
    root = core.clean_path(project)
    saved = settings(project)['requirements']
    for rel in ([saved] if saved else []) + list(REQUIREMENTS_PLACES):
        if (root / rel).is_file():
            return rel, True
    return None


def _never(project):
    return tuple(_clean(one) for one in dependencies(project).get('never_copied', []) if '/' in _clean(one))


def old_output(project):
    """What an earlier Deploy left in the deploy folder: the exe and the home folder it made when it was run there (both, whichever are there)."""
    exe = exe_path(project)
    return [path for path in (exe, exe.parent / home_name(project)) if path.exists()]


def _unlock(function, path, _error):
    """rmtree's hand for a read-only file (Windows): make it writable and try again; a second failure is raised."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove(path):
    try:
        if path.is_dir():
            shutil.rmtree(path, onerror=_unlock)
        else:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
    except OSError as error:
        raise ZygoteError(f'{path} could not be removed ({error.strerror or error}). Close the program that runs from it (and any window showing it), then try again. Nothing was built.') from error


def remove_old(project):
    """Wipe the earlier Deploy output completely: the exe AND its home folder, with everything in it (a home left behind would start stale files instead of the new build).
    Returns the names removed."""
    gone = old_output(project)
    for path in gone:
        _remove(path)
    return [path.name for path in gone]


def backup_old(project):
    """Move the earlier Deploy output (exe and home folder) into zip\\deploy_old\\<date-time>\\ and return that folder. The deploy folder is then empty of it."""
    found = old_output(project)
    if not found:
        raise ZygoteError('There is no earlier deploy output to back up.')
    stamp = core.now().strftime('%Y-%m-%d_%H%M%S')
    target = core.zip_folder(project) / 'deploy_old' / stamp
    target.mkdir(parents=True, exist_ok=True)
    for path in found:
        try:
            shutil.move(str(path), str(target / path.name))
        except OSError as error:
            raise ZygoteError(f'{path} could not be moved to the backup ({error.strerror or error}). Close the program that runs from it, then try again. Nothing was built.') from error
    return target


def runtime_needs(project):
    """The dependencies that are not copied but checked on the computer (Python with Tk, a pip package ...): [(name, what, kind, why)]. Shown in the dialog."""
    return [(one['name'], one['path'], one['kind'], one.get('why', '')) for one in dependencies(project)['dependencies'] if one['type'] == 'runtime']


def save_settings(project, requirements, window, args='', ticked=None):
    """Keep the Deploy choices. A requirements file must be a file inside the project (relative path saved); '' means none. `ticked` = the items of choices the
    person left ticked (None keeps the earlier choice). Returns the saved settings."""
    root = core.clean_path(project)
    text = (requirements or '').strip().strip('"')
    rel = ''
    if text:
        path = Path(text)
        path = path if path.is_absolute() else root / path
        if not path.is_file():
            raise ZygoteError(f'The requirements file {text} was not found.')
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as error:
            raise ZygoteError(f'The requirements file must be inside the project: {path}') from error
    earlier = settings(project)
    include, exclude = earlier['include'], earlier['exclude']
    if ticked is not None:
        shown = [one['key'] for one in choices(project)]
        include = [name for name in shown if name in ticked]
        exclude = [name for name in shown if name not in ticked]
    state = core.load_state(project)
    state['deploy'] = {'requirements': rel, 'window': bool(window), 'args': (args or '').strip(), 'include': include, 'exclude': exclude}
    core.save_state(project, state)
    return settings(project)


def home_name(project):
    """The folder the package unpacks: <project>_home (a name with characters Windows refuses is cleaned)."""
    name = core.BAD_NAME_CHARACTERS.sub('_', core.project_name(project)).strip(' .') or 'project'
    return f'{name}_home'


def exe_path(project):
    """deploy\\<project>.exe (the plain name; the version and date live inside the package)."""
    name = core.BAD_NAME_CHARACTERS.sub('_', core.project_name(project)).strip(' .') or 'project'
    return core.clean_path(project) / OUTPUT_REL / f'{name}.exe'


def plan(project):
    """What the package will say: {'name', 'version', 'entry', 'args', 'requirements', 'window'}. Raises with the plain reason when it cannot be made."""
    root = core.clean_path(project)
    run = core.run_settings(project, 'runtime')
    entry = run['entry']
    if not entry:
        raise ZygoteError('Deploy needs the program to start: set the entry point (Project settings > Runtime) first.')
    if not (root / entry).is_file():
        raise ZygoteError(f'The entry point {entry} is not in the project.')
    if Path(entry).suffix.lower() != '.py':
        raise ZygoteError(f'Deploy starts Python programs for now; {entry} is not a .py file.')
    chosen = settings(project)
    carried = {name for _, name in files(project)}
    if entry not in carried:
        raise ZygoteError(f'The entry point {entry} is not among the files Deploy carries: add the folder that holds it to {DEPENDENCIES} as required.')
    return {'name': core.project_name(project), 'version': core.read_version(project) or '', 'entry': entry,
            'args': core.split_words(chosen['args']), 'requirements': chosen['requirements'], 'window': chosen['window'],
            'built_with': {'zygote': core.read_version(core.ZYGOTE_ROOT) or ''}}


def _left_out(rel, never):
    """True for a path that is never carried: the machine's own, the project's never_copied list, a .vfc recovery journal."""
    parts = rel.split('/')
    return '.vfc' in parts or any(rel == gone or rel.startswith(gone + '/') for gone in ALWAYS_LEFT_OUT + never)


def files(project):
    """The project's files that go into the package, as (path, name inside the package): every required entry of dependencies.json and every ticked optional
    one, at the same path as in the project (so the program's own paths still work). An entry that is not there is refused with its name."""
    root = core.clean_path(project)
    found = dependencies(project)
    never = _never(project)
    ticked = {one['key'] for one in choices(project) if one['ticked']}
    wanted = [(_clean(one['path']), one['name']) for one in found['dependencies'] if one['type'] != 'runtime' and _clean(one['path']) in ticked]
    seen, out = set(), []
    for rel, reason in wanted:
        start = root / rel
        if not start.exists():
            raise ZygoteError(f'Deploy needs {rel} ({reason}) and it is not in the project.')
        if start.is_file():
            if rel not in seen and not _left_out(rel, never):
                seen.add(rel)
                out.append((start, rel))
            continue
        for folder, dirs, names in os.walk(start):
            here = Path(folder).relative_to(root).as_posix()
            dirs[:] = sorted(one for one in dirs if one != '__pycache__' and not _left_out(f'{here}/{one}', never))
            for name in sorted(names):
                inside = f'{here}/{name}'
                if inside in seen or _left_out(inside, never) or name.lower().endswith('.pyc'):
                    continue
                seen.add(inside)
                out.append((Path(folder) / name, inside))
    return out


def build(project, dest=None, target=None):
    """Make the package exe (its icon is the project's program icon when it has one). Returns (the path of the exe, the number of project files in it). An exe that is there is replaced only after the caller asked."""
    wanted = plan(project)
    if not RUN_SCRIPT.is_file():
        raise ZygoteError(f'The start script is missing: {RUN_SCRIPT}. Unpack the build ZIP again.')
    taken = [name for _, name in files(project) if name in ('deploy.json', 'deploy_run.py')]
    if taken:
        raise ZygoteError(f'The project already has {taken[0]} at its top: Deploy writes a file of that name. Rename yours first.')
    dest = Path(dest) if dest else exe_path(project)
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        payload = Path(tmp) / 'package.zip'
        with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.comment = f'{home_name(project)}\ndeploy_run.py'.encode('utf-8')
            for path, name in files(project):
                zf.write(path, name)
                count += 1
            zf.writestr('deploy.json', json.dumps(wanted, indent=2) + '\n')
            zf.write(RUN_SCRIPT, 'deploy_run.py')
        dest.parent.mkdir(parents=True, exist_ok=True)
        core.make_setup_exe(payload, dest, target, icon=core.program_icon(project))
    return dest, count
