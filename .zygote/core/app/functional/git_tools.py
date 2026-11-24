"""Git for the open project, in two ways the person chooses in Settings > Git settings…: TortoiseGit (its windows, the way Commit has always worked) or the command line git.
Everything here is one program started on one press of one menu entry (never by itself, never in a loop). No Qt. A missing program or a refused command raises
ZygoteError with the program's own words."""
import os
import re
import shutil
import subprocess
from pathlib import Path

from functional import core

PROGRAMS = ('tortoise', 'commandline')
DEFAULT_PROGRAM = 'tortoise'                                  # the way Commit worked before the choice existed
TORTOISE_PLACES = ('%ProgramFiles%', '%ProgramFiles(x86)%')
BAD_BRANCH = re.compile(r'[\s~^:?*\[\\]|\.\.|@\{|^-|^/|/$|\.$|\.lock$|//')


def program():
    """The chosen program ('tortoise' or 'commandline'); this computer's choice, kept in Zygote's own settings."""
    chosen = core.load_settings().get('git_program', DEFAULT_PROGRAM)
    if chosen not in PROGRAMS:
        raise core.ZygoteError(f'The saved Git program {chosen!r} is not one of {", ".join(PROGRAMS)}. Choose it again in Settings > Git settings….')
    return chosen


def set_program(chosen):
    if chosen not in PROGRAMS:
        raise core.ZygoteError(f'Git program must be one of {", ".join(PROGRAMS)}, not {chosen!r}.')
    core.save_setting('git_program', chosen)


def tortoise_path():
    found = shutil.which('TortoiseGitProc.exe')
    if found:
        return found
    for place in TORTOISE_PLACES:
        folder = os.path.expandvars(place)
        candidate = Path(folder) / 'TortoiseGit' / 'bin' / 'TortoiseGitProc.exe'
        if '%' not in folder and candidate.is_file():
            return str(candidate)
    raise core.ZygoteError('TortoiseGitProc.exe was not found. Install TortoiseGit, add its bin folder to PATH, or choose the command line git in Settings > Git settings….')


def git_path():
    found = shutil.which('git')
    if not found:
        raise core.ZygoteError('git was not found. Install Git for Windows (git-scm.com), or choose TortoiseGit in Settings > Git settings….')
    return found


def run(project, args, timeout=60):
    """One git command in the project. Returns its output; raises with git's own words when it refuses."""
    done = subprocess.run([git_path(), '-C', str(project)] + list(args), capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')
    text = (done.stdout + done.stderr).strip()
    if done.returncode != 0:
        raise core.ZygoteError(f'git {" ".join(args)} said (exit {done.returncode}): {text or "nothing"}')
    return text


def start_tortoise(project, command):
    """Open one TortoiseGit window (/command:NAME) on the project and let go of it: the window is the person's, Zygote does not wait for it."""
    subprocess.Popen([tortoise_path(), f'/command:{command}', f'/path:{project}'])


def check_branch_name(name):
    name = (name or '').strip()
    if not name or BAD_BRANCH.search(name):
        raise core.ZygoteError(f'{name!r} is not a usable branch name (no spaces, no ~ ^ : ? * [ \\ .., not starting with - or ending with / . or .lock).')
    return name


def new_branch(project, name):
    """Make the branch from where the project is now and switch to it. Command line git only (TortoiseGit opens its own Create Branch window instead)."""
    run(project, ['switch', '-c', check_branch_name(name)])


def commit_all(project, message):
    """Command line commit of everything in the project folder (new files too). Two git calls: add, then commit."""
    message = (message or '').strip()
    if not message:
        raise core.ZygoteError('A commit needs a message.')
    run(project, ['add', '-A', '--', '.'])
    return run(project, ['commit', '-m', message])


def last_step(project):
    """What the last git step was, from git's own record of where HEAD has been (the reflog): {'entry', 'kind', 'what'}. Raises when there is no earlier place to go back to."""
    lines = run(project, ['reflog', '-n', '2', '--format=%gd|%h|%gs']).splitlines()
    if len(lines) < 2:
        raise core.ZygoteError('There is no earlier step to go back to: this repository has only one entry in its record.')
    entry, short, what = lines[0].split('|', 2)
    kind = 'commit' if what.startswith('commit') else 'checkout' if what.startswith('checkout') else 'other'
    return {'entry': entry, 'short': short, 'kind': kind, 'what': what}


def undo_words(step):
    if step['kind'] == 'commit':
        return f'Undo the commit "{step["what"]}": the commit goes away and its changes stay in your files (nothing in your files is lost).'
    if step['kind'] == 'checkout':
        return f'Go back to the place you were before: "{step["what"]}".'
    return (f'Undo "{step["what"]}": the project goes back to how it was before that step. Changes in your files that are not committed are LOST; '
            'files Git does not track (new, never added) stay.')


def undo_step(project, step):
    """Go back one step. A commit: soft (the changes stay). A checkout: back to the earlier place. Any other step (a pull, a merge, a reset): hard, back to the earlier state."""
    if step['kind'] == 'commit':
        return run(project, ['reset', '--soft', 'HEAD@{1}'])
    if step['kind'] == 'checkout':
        return run(project, ['switch', '-'])
    return run(project, ['reset', '--hard', 'HEAD@{1}'])
