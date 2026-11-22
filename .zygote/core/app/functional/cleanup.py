"""What an update of the project's core takes away: the files and folders that an earlier Zygote made and this one does not need.
The list is DATA (app_tree\\assets\\cleanup.json, a list of {match, where, owner, why}): `where` is a folder inside the project, `match` a name pattern in it.
It grows with each release and is safe to run again (nothing found, nothing done). Nothing here runs because a file exists: the update asks for it.
  owner "system": inside Zygote's own structure, no one edits it: removed without a question, said in the Log.
  owner "user": something the person could use or edit: one question lists it, ticked, and the ticked ones go to the project's recycle bin (so they can come back)."""
import json
import shutil
from pathlib import Path

from functional import core

CLEANUP_FILE = core.zpath(core.ZYGOTE_ROOT, 'assets', 'cleanup.json')


class Found:
    """One thing the list names that is in this project."""

    def __init__(self, path, owner, why, leftover=False):
        self.path, self.owner, self.why, self.leftover = Path(path), owner, why, leftover


def entries():
    return json.loads(CLEANUP_FILE.read_text(encoding='utf-8'))


def kept(root, entry, path):
    """True when the entry has no `kept_in`, or the same-named folder in `kept_in` (a folder of the project) holds at least one file: a leftover is only
    thrown away when its twin is safe somewhere else."""
    where = entry.get('kept_in')
    if not where:
        return True
    twin = root / where / path.name
    return twin.is_dir() and any(one.is_file() for one in twin.rglob('*'))


def find(project):
    """What of the list is in the project now: the system ones, then the user ones. An entry with `kept_in` is only found while its twin is safe there."""
    root = core.clean_path(project)
    found = []
    for entry in entries():
        folder = root / entry['where'] if entry['where'] else root
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob(entry['match'])):
            if kept(root, entry, path):
                found.append(Found(path, entry['owner'], entry['why'], leftover=bool(entry.get('kept_in'))))
    return sorted(found, key=lambda one: (one.owner != 'system', str(one.path)))


def skipped(project):
    """The Log lines for leftovers that were NOT offered because their twin in `kept_in` is missing or empty."""
    root = core.clean_path(project)
    lines = []
    for entry in entries():
        folder = root / entry['where'] if entry['where'] else root
        if folder.is_dir() and entry.get('kept_in'):
            for path in sorted(folder.glob(entry['match'])):
                if not kept(root, entry, path):
                    lines.append(f'{entry["where"]}/{path.name} was left where it is: {entry["kept_in"]}/{path.name} has no files yet.')
    return lines


def remove_system(items):
    """Remove the system items (no one edits them). Returns the Log lines."""
    lines = []
    for one in items:
        if one.path.is_dir():
            shutil.rmtree(one.path)
        elif one.path.exists():
            one.path.unlink()
        lines.append(f'Cleaned up {one.path.name}: {one.why}.')
    return lines


def remove_user(project, items):
    """The ticked user items go to the project's recycle bin (a file that cannot go there is left alone and said). Returns the Log lines."""
    lines = []
    for one in items:
        if one.leftover or core.can_trash(project, one.path):
            core.trash_path(project, one.path, leftover=one.leftover)
            if one.path.exists():                                    # fail loud: it was moved, so it must be gone
                raise core.ZygoteError(f'{one.path} is still there after it went to the recycle bin. Close what may hold it and update again.')
            lines.append(f'{one.path.name} went to the recycle bin: {one.why}.')
        else:
            lines.append(f'{one.path.name} was left where it is: it cannot be thrown away from here.')
    return lines
