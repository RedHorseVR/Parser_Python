"""Project > Remake launchers…: what of the open project (and, for Zygote's own folder, of Zygote) can be made again, how healthy each part looks now, and
doing exactly the parts the person ticked. The same steps as Setup (the launcher, the `zygote` command, the environment check), one code path.

`Rebuild(project).health()` is a list of Items; `Rebuild(project).run(keys)` does the ticked ones and returns the Log lines. Nothing runs until run().
Things that cannot be told from outside (a launcher's icon) are `unknown` and stay ticked by default: it is cheaper to make it again than to guess.
"""
import os
from pathlib import Path

import pathsetup
from functional import core
from functional.core import ZygoteError

LAUNCHER, SHORTCUT, COMMAND, ENVIRONMENT = 'launcher', 'shortcut', 'command', 'environment'


class Item:
    """One part: what it is called, its state ('ok', 'stale', 'unknown'), a plain sentence about it, whether it is ticked at first, and whether it can be ticked."""

    def __init__(self, key, label, state, text, ticked, tickable=True):
        self.key, self.label, self.state, self.text, self.ticked, self.tickable = key, label, state, text, ticked, tickable


class Rebuild:
    def __init__(self, project):
        self.project = core.clean_path(project)
        self.is_zygote = self.project == core.clean_path(core.ZYGOTE_ROOT)

    def launcher_item(self):
        name = core.launcher_name(self.project)
        path = self.project / name
        if not path.is_file():
            older = core.find_launchers(self.project)
            if older:
                return Item(LAUNCHER, name, 'stale', f'{older[0].name} will be renamed to it', True)
            return Item(LAUNCHER, name, 'stale', 'missing', True)
        if not core.launcher_is_current(path):
            return Item(LAUNCHER, name, 'stale', 'an older program', True)
        if core.LAUNCHER_IS_SHORTCUT:
            return Item(LAUNCHER, name, 'unknown', 'there (a shortcut with the project icon; making it again takes a moment)', True)
        return Item(LAUNCHER, name, 'unknown', 'there; Zygote cannot tell whether its icon is current', True)

    def shortcut_item(self):
        made = list((self.project / core.DOT / 'user').glob('* (Zygote).lnk'))
        text = 'there' if made else 'not made yet'
        return Item(SHORTCUT, 'Shortcut (in .zygote\\user)', 'ok' if made else 'unknown', text, False, tickable=os.name == 'nt')

    def command_item(self):
        found = pathsetup.find_command()
        if found is None:
            return Item(COMMAND, 'The "zygote" command on the PATH', 'stale', 'is not on the PATH', True)
        if not pathsetup.same(found, core.ZYGOTE_ROOT):
            return Item(COMMAND, 'The "zygote" command on the PATH', 'stale', f'starts the Zygote in {found}, not this one', True)
        return Item(COMMAND, 'The "zygote" command on the PATH', 'ok', 'starts this Zygote', False)

    def environment_item(self):
        """Information only: Zygote runs from this environment, so it cannot be rebuilt from inside Zygote (Setup.bat does it, with Zygote closed)."""
        import bootstrap
        reason = bootstrap.env_moved_reason() or bootstrap.stale_reason()
        if reason:
            return Item(ENVIRONMENT, 'The environment', 'stale', f'{reason} Close Zygote and run Setup.bat: Zygote is running from it now.', False, tickable=False)
        return Item(ENVIRONMENT, 'The environment', 'ok', 'healthy', False, tickable=False)

    def health(self):
        items = [self.launcher_item(), self.shortcut_item()]
        if self.is_zygote:
            items += [self.command_item(), self.environment_item()]
        return items

    def run(self, keys):
        """Do the parts named in `keys`. An unknown or untickable key is an error, never skipped. Returns the lines for the Log."""
        known = {item.key: item for item in self.health()}
        lines = []
        for key in keys:
            if key not in known or not known[key].tickable:
                raise ZygoteError(f'"{key}" cannot be rebuilt here.')
            if key == LAUNCHER:
                renamed = core.rename_launcher(self.project)
                if renamed:
                    lines.append(renamed)
                lines.append(f'{core.launcher_name(self.project)} rebuilt: {core.make_launcher(self.project, force=True)}')
            elif key == SHORTCUT:
                lines += [f'Shortcut stamped: {link}' for link in core.create_shortcut(self.project, core.project_name(self.project))]
            elif key == COMMAND:
                lines.append(pathsetup.add(core.ZYGOTE_ROOT))
        return lines or ['Nothing was ticked: nothing was rebuilt.']
