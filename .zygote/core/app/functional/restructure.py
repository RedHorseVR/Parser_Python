"""Z 2.15: the one-time move of an older project's folders into the app tree. It runs only when the person says yes in Update project's Zygote.
The list is DATA (app_tree\\assets\\restructure.json: moves, files to replace when they are still the placeholder an earlier Zygote wrote, saved paths to
correct). Nothing is deleted and nothing is replaced: a folder that is not there yet is moved whole; a folder that is already there is filled with what it
lacks; anything with a name that is taken stays where it was and is said. Nothing here runs because a file exists: the update asks for it."""
import hashlib
import json
import shutil
from pathlib import Path

from functional import core

RESTRUCTURE_FILE = core.zpath(core.ZYGOTE_ROOT, 'assets', 'restructure.json')


def entries():
    return json.loads(RESTRUCTURE_FILE.read_text(encoding='utf-8'))


def plan(project):
    """The moves of the list whose source is in this project: [(from_rel, to_rel)]. A source whose target already holds files is an old copy, not a move:
    the cleanup list (app_tree\\assets\\cleanup.json) offers it for the recycle bin instead, so nothing is mixed into the new folder."""
    root = core.clean_path(project)
    return [(move['from'], move['to']) for move in entries()['moves'] if (root / move['from']).is_dir() and not holds_files(root / move['to'])]


def holds_files(folder):
    """True when the folder exists and has at least one file anywhere inside."""
    return folder.is_dir() and any(one.is_file() for one in folder.rglob('*'))


def move_one(root, source_rel, target_rel):
    """Move one folder. Returns the Log lines."""
    source, target = root / source_rel, root / target_rel
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return [f'Moved {source_rel} to {target_rel}']
    lines = []
    for child in sorted(source.iterdir()):
        if (target / child.name).exists():
            lines.append(f'{source_rel}/{child.name} stays: {target_rel}/{child.name} is already there')
        else:
            shutil.move(str(child), str(target / child.name))
    if not any(source.iterdir()):
        source.rmdir()
    return lines + [f'Moved what {source_rel} held into {target_rel}']


def sha1_of(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def replace_placeholders(root):
    """A launcher the project still has as the placeholder an earlier Zygote wrote is replaced with the new placeholder (it named the old folder).
    One the person changed is left alone. Returns the Log lines."""
    lines = []
    for item in entries()['replace_if_unchanged']:
        path = root / item['file']
        if path.is_file() and sha1_of(path) == item['was_sha1']:
            path.write_bytes((core.BASELINE / item['now']).read_bytes())
            lines.append(f'{item["file"]} is the new placeholder ({item["why"]})')
    return lines


def fix_saved_paths(project):
    """A path saved in the project's record that began in the old place is written with the new one. Returns the Log lines."""
    state = core.load_state(project)
    lines = []
    for item in entries()['state_paths']:
        value = state.get(item['key'])
        if isinstance(value, str) and value.startswith(item['from']):
            state[item['key']] = item['to'] + value[len(item['from']):]
            lines.append(f'The saved {item["key"]} is now {state[item["key"]]}')
    if lines:
        core.save_state(project, state)
    return lines


def run(project):
    """Do the moves of plan(project), then the placeholders and the saved paths. Returns the Log lines. A move that fails raises: what was moved before it stays moved."""
    root = core.clean_path(project)
    lines = []
    for source_rel, target_rel in plan(root):
        lines += move_one(root, source_rel, target_rel)
    return lines + replace_placeholders(root) + fix_saved_paths(root)
