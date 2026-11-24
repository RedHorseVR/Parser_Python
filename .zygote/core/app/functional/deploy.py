"""Deploy (Z 2.19.4): one self-extracting program that holds the project's program files. Run on another computer it unpacks a folder named
<project>_home beside itself and starts the program from there (it builds the folder's own Python environment first when the project names a
requirements file). The exe is named like the project (VFlow.exe) and written to the deploy folder at the project's top. Make ZIP stays what it was: a snapshot of the project.
What goes in: ONLY what app_tree/dependencies.json (hand-written by the project: name, path, type, kind required/optional, why) lists: its required entries and the optional ones ticked in the dialog, each at its own path (app_tree and .zygote pieces included). No such file: Deploy refuses. Plus deploy.json (data:
name, entry, args, requirements, window) and deploy_run.py (the hand-written start script of app_tree\\tools\\deploy, copied, never generated).
A project that cannot be deployed this way (no Python entry point) is refused with the reason: no fallback."""
import filecmp
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
    wanted = saved.get('requirements', '')
    if wanted == OWN_REQUIREMENTS and core.clean_path(project) != core.ZYGOTE_ROOT:
        wanted = ''                                                  # Zygote's own packages are not another project's (Z 2.19.24: a project's .zygote copy is never offered)
    return {'requirements': wanted, 'window': bool(saved.get('window', True)), 'args': saved.get('args', ''),
            'include': list(saved.get('include', [])), 'exclude': list(saved.get('exclude', [])), 'built_version': saved.get('built_version', ''),
            'target': saved.get('target', 'folder') if saved.get('target', 'folder') in TARGETS else 'folder'}


TARGETS = ('folder', 'exe')                  # folder: start files + program (no exe: Defender leaves it alone); exe: the self-extracting program
START_FILES = ('start.bat', 'start.sh', 'start.command')              # inside program\: they start the program (and say "Run setup first" when the environment is not there)
SETUP_FILES = ('setup.bat', 'setup.sh', 'setup.command')              # the only files at the top of the folder: each runs program\\deploy_setup.py
SETUP_SCRIPT = core.zpath(core.ZYGOTE_ROOT, 'tools', 'deploy', 'deploy_setup.py')
PACKAGE_README = core.zpath(core.ZYGOTE_ROOT, 'tools', 'deploy', 'PACKAGE_README.md')       # hand-written; Deploy copies it into program\README_RUNTIME.md
START_DIR = core.zpath(core.ZYGOTE_ROOT, 'tools', 'deploy')
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
OWN_REQUIREMENTS = '.zygote/config/requirements.txt'            # the packages of Zygote itself: offered for Zygote's own folder only


def requirements_offer(project):
    """The requirements file the dialog offers, as (relative path, ticked), or None when the project has none (then the dialog shows nothing about packages).
    The one saved earlier counts when it is still there; else requirements.txt at the top, in app or in app_tree. It starts ticked."""
    root = core.clean_path(project)
    saved = settings(project)['requirements']
    places = REQUIREMENTS_PLACES + ((OWN_REQUIREMENTS,) if core.clean_path(project) == core.ZYGOTE_ROOT else ())
    for rel in ([saved] if saved else []) + list(places):
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


def old_exe(project):
    """The exe an earlier Deploy left, or None."""
    exe = exe_path(project)
    return exe if exe.exists() else None


def old_home(project):
    """The folder that exe made when it was run (<project>_home), or None."""
    home = exe_path(project).parent / home_name(project)
    return home if home.exists() else None


def backup_folder(project):
    """Where the exe is backed up: zip\\deploy_old\\<exe name>_<version it was made from> (a name Windows accepts). When that folder holds a DIFFERENT exe (rebuilt
    without a new version) the next free _2, _3 ... is used, so a backup is never overwritten."""
    version = core.BAD_NAME_CHARACTERS.sub('_', settings(project)['built_version'] or 'unknown version').strip(' .') or 'unknown'
    base = core.zip_folder(project) / 'deploy_old' / f'{exe_path(project).stem}_{version}'
    exe = old_exe(project)
    number, folder = 1, base
    while exe is not None and (folder / exe.name).is_file() and not filecmp.cmp(exe, folder / exe.name, shallow=False):
        number += 1
        folder = base.with_name(f'{base.name}_{number}')
    return folder


def is_backed_up(project):
    return (backup_folder(project) / exe_path(project).name).is_file()


def backup_exe(project):
    """COPY the deployed exe (only the exe, not its home folder) into its backup folder; the exe stays where it is. When that backup is already there (an earlier Deploy made
    it and then could not delete the exe) nothing is copied again. Returns (folder, already_there)."""
    exe = old_exe(project)
    if exe is None:
        raise ZygoteError('There is no earlier deploy exe to back up.')
    target = backup_folder(project)
    if (target / exe.name).is_file():
        return target, True
    target.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(exe, target / exe.name)
    except OSError as error:
        raise ZygoteError(f'{exe} could not be copied to the backup {target} ({error.strerror or error}). Nothing was changed.') from error
    return target, False


def remove_exe(project):
    """Delete the exe at the root of the deploy folder. Raises (with the plain reason) when it cannot be deleted, usually because it is running."""
    exe = old_exe(project)
    if exe is not None:
        _remove(exe)


def remove_home(project):
    """Delete the home folder with everything in it (a home left behind would start stale files instead of the new build)."""
    home = old_home(project)
    if home is not None:
        _remove(home)


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
    state['deploy'] = {'requirements': rel, 'window': bool(window), 'args': (args or '').strip(), 'include': include, 'exclude': exclude, 'built_version': earlier['built_version'], 'target': earlier['target']}
    core.save_state(project, state)
    return settings(project)


def save_target(project, target):
    """Keep which kind of package Deploy makes: 'folder' or 'exe'."""
    if target not in TARGETS:
        raise ZygoteError(f'Deploy target {target!r} is not one of {TARGETS}.')
    state = core.load_state(project)
    saved = state.setdefault('deploy', {})
    saved['target'] = target
    core.save_state(project, state)
    return target


def record_built(project):
    """Remember which project version the exe in the deploy folder was made from: the next Deploy names its backup folder by it."""
    state = core.load_state(project)
    state.setdefault('deploy', {})['built_version'] = core.read_version(project) or ''
    core.save_state(project, state)


def home_name(project):
    """The folder the package unpacks: <project>_runtime (the runtime form; a development form <project>_development comes later). A name with characters Windows refuses is cleaned."""
    name = core.BAD_NAME_CHARACTERS.sub('_', core.project_name(project)).strip(' .') or 'project'
    return f'{name}_runtime'


def exe_path(project):
    """deploy\\<project>.exe (the plain name; the version and date live inside the package)."""
    name = core.BAD_NAME_CHARACTERS.sub('_', core.project_name(project)).strip(' .') or 'project'
    return core.clean_path(project) / OUTPUT_REL / f'{name}.exe'


def plan(project):
    """What the package will say: {'name', 'version', 'entry', 'args', 'requirements', 'window'}. Raises with the plain reason when it cannot be made."""
    root = core.clean_path(project)
    run = core.run_settings(project, 'runtime')
    entry = run['entry'] or core.own_entry(project)             # Zygote's own folder supplies app/main.py for this deploy and saves nothing
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
    record = core.license_record(project)
    return {'name': core.project_name(project), 'version': core.read_version(project) or '', 'entry': entry,
            'args': core.split_words(chosen['args']), 'requirements': chosen['requirements'], 'window': chosen['window'],
            'notice': core.license_notice(project), 'license_type': record['type'] if record else '', 'license_file': record['file'] if record and record['type'] else '',
            'license': record or {},                                   # the whole record: a deployed program has no .zygote folder to read it from
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
    record = core.license_record(project)                          # Z 2.19.20: the project's license file always travels (it is not in dependencies.json)
    if record and record['type'] and record['file'] not in seen and (root / record['file']).is_file() and not _left_out(record['file'], never):
        out.append((root / record['file'], record['file']))
    chosen = settings(project)['requirements']                     # the packages file the package builds its environment from always travels (it may sit outside dependencies.json)
    if chosen and chosen not in seen and (root / chosen).is_file() and not _left_out(chosen, never):
        out.append((root / chosen, chosen))
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
    record_built(project)
    return dest, count


PROGRAM_DIR = 'program'                                       # inside the deploy folder: the project's files, deploy.json, deploy_run.py and the environment


def folder_path(project):
    """deploy\\<project>_home: the folder the folder target makes, named by home_name (the same name the exe target unpacks to; never the development project's own name)."""
    return core.clean_path(project) / OUTPUT_REL / home_name(project)


def old_folder(project):
    """The folder an earlier folder Deploy left, or None."""
    folder = folder_path(project)
    return folder if folder.exists() else None


def remove_folder(project):
    folder = old_folder(project)
    if folder is not None:
        _remove(folder)


def build_folder(project, dest=None):
    """Make the package as one folder, no exe: at its top only the three setup files (setup.bat, setup.sh, setup.command) and `program`; in `program` the project's files at
    their own paths, deploy.json, deploy_run.py, deploy_setup.py, the three start files and README_RUNTIME.md. The environment is built on the computer that runs it, when setup is run. Returns (the folder, the number of project files). The folder must not be there: the caller clears an earlier one after asking."""
    wanted = dict(plan(project), gate=True)                        # data for deploy_run.py: this package builds its environment only when setup is run
    sources = [RUN_SCRIPT, SETUP_SCRIPT, PACKAGE_README] + [START_DIR / name for name in START_FILES + SETUP_FILES]
    for source in sources:
        if not source.is_file():
            raise ZygoteError(f'The start file is missing: {source}. Unpack the build ZIP again.')
    carried_names = START_FILES + SETUP_FILES + ('deploy.json', 'deploy_run.py', 'deploy_setup.py', 'README_RUNTIME.md')
    taken = [name for _, name in files(project) if name in carried_names]
    if taken:
        raise ZygoteError(f'The project already has {taken[0]} at its top: Deploy writes a file of that name. Rename yours first.')
    folder = Path(dest) if dest else folder_path(project)
    if folder.exists():
        raise ZygoteError(f'{folder} is there already: it is cleared first (Deploy asks).')
    program = folder / PROGRAM_DIR
    count = 0
    program.mkdir(parents=True)
    for path, name in files(project):
        target = program / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    (program / 'deploy.json').write_text(json.dumps(wanted, indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(RUN_SCRIPT, program / 'deploy_run.py')
    shutil.copyfile(SETUP_SCRIPT, program / 'deploy_setup.py')
    shutil.copyfile(PACKAGE_README, program / 'README_RUNTIME.md')
    for name in START_FILES:                                       # the start files live inside program\\ (hidden from the top)
        shutil.copyfile(START_DIR / name, program / name)
        (program / name).chmod(0o755)
    for name in SETUP_FILES:                                       # the three setup files stay at the top: the person sees nothing else but program\\
        shutil.copyfile(START_DIR / name, folder / name)
        (folder / name).chmod(0o755)
    record_built(project)
    return folder, count
