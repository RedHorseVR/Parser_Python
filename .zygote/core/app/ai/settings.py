"""What the AI panel remembers, per project, in the project's private record (.zygote\\user\\zygote.json, key "ai"). Everything is checked
when it is read; a wrong record raises, it is never repaired silently."""
from functional import core
from ai.ollama import LOCAL_URL, check_uses, check_url

TARGETS = ('local', 'worker')
KEYS = {'target', 'local_url', 'worker_url'}


def read(project):
    """The saved settings. A project that has none yet gets the standard ones (this computer's Ollama at its own address)."""
    saved = core.load_state(project).get('ai')
    if saved is None:
        return {'target': 'local', 'local_url': LOCAL_URL, 'worker_url': ''}
    if not (isinstance(saved, dict) and set(saved) == KEYS):
        raise core.ZygoteError(f'The saved AI settings are wrong: {saved!r}.')
    if saved['target'] not in TARGETS:
        raise core.ZygoteError(f'The saved AI target is wrong: {saved["target"]!r}.')
    return saved


def write(project, target, local_url, worker_url):
    """Remember the target and both addresses. The address of the chosen target must be a real one; the other may be empty."""
    if target not in TARGETS:
        raise core.ZygoteError(f'Unknown AI target: {target!r}.')
    check_url(local_url if target == 'local' else worker_url)
    settings = {'target': target, 'local_url': local_url.strip(), 'worker_url': worker_url.strip()}
    state = core.load_state(project)
    if state.get('ai') != settings:
        state['ai'] = settings
        core.save_state(project, state)


def read_uses(project):
    """What each model of this project is meant for (Text, Image, Analysis boxes), kept in the project's record under "ai_uses". {} when none."""
    return check_uses(core.load_state(project).get('ai_uses', {}))


def write_uses(project, uses):
    check_uses(uses)
    state = core.load_state(project)
    if state.get('ai_uses', {}) != uses:
        state['ai_uses'] = uses
        core.save_state(project, state)
