"""The AI interface of Zygote's core, for the programs of a project (VFlow first). Plain Python, no Qt: a Tk program calls it directly.
Import it from the project's copy of the core:  sys.path.insert(0, <project>/.zygote/core/app)  then  from ai import interface.

Three calls, nothing else:
  ask(project, prompt, code='')  - ask one question about a block of code. BLOCKS until the answer is in (up to several minutes for a model that has to load):
                                   call it from a worker thread, never from the window's own thread.
  set_model(project)             - tell the project's Zygote window to open its AI panel (the one place where Ollama is started, a model is chosen or loaded,
                                   and later the keys of the cloud providers are kept). Returns at once.
  questions()                    - the list of basic questions (data/ai_questions.json) for a menu.

The rules: nothing is started here. A model that is not loaded stays unloaded: `ask` only uses what is loaded and running, and otherwise says so and opens the panel.
There is no second answer from anywhere else, and every failure comes back as a plain message."""
import json
import os
import socket
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from ai import settings
from ai.ollama import LOAD_WAIT_MS
from functional import instance_name

ANSWERED, NEEDS_MODEL, NO_SERVER, FAILED = 'answered', 'needs_model', 'no_server', 'failed'
QUESTIONS_FILE = Path(__file__).resolve().parents[1] / 'data' / 'ai_questions.json'
LOOK_MS = 6000                                             # the wait for "what is loaded" (a plain question to a server that is there)
PANEL_MESSAGE = b'ai\n'                                    # what the window listens for (ui_ux/instance.py)


class InterfaceError(Exception):
    pass


def questions():
    """The basic questions, in the order of the file."""
    found = json.loads(QUESTIONS_FILE.read_text(encoding='utf-8'))
    if not (isinstance(found, list) and found and all(isinstance(one, str) and one.strip() for one in found)):
        raise InterfaceError(f'{QUESTIONS_FILE} must be a list of questions.')
    return found


def server_url(project):
    """The address of the Ollama the panel is set to (this computer's, or the LAN worker's)."""
    saved = settings.read(project)
    return (saved['local_url'] if saved['target'] == 'local' else saved['worker_url']).rstrip('/')


def call(url, body=None, wait_ms=LOOK_MS):
    """One HTTP call to Ollama; the answer as JSON. GET without a body, POST with one. Raises urllib.error.URLError / OSError when nothing answers."""
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=wait_ms / 1000) as answer:
        return json.loads(answer.read().decode('utf-8'))


def loaded_models(url):
    """The names of the models that are loaded and running now (Ollama's /api/ps)."""
    found = call(url + '/api/ps').get('models') or []
    return [one.get('name') or one.get('model') for one in found if one.get('name') or one.get('model')]


def prompt_text(prompt, code):
    return prompt.strip() if not code.strip() else f'{prompt.strip()}\n\n```\n{code.rstrip()}\n```'


def reply(status, message, model='', answer='', panel_opened=False):
    """What every call returns: status (answered | needs_model | no_server | failed), message (a short text to show in a toast or a line), model, answer, panel_opened."""
    return {'status': status, 'message': message, 'model': model, 'answer': answer, 'panel_opened': panel_opened}


def ask(project, prompt, code='', open_panel=True):
    """Ask `prompt` about `code`. With a model loaded and running: the answer comes back with a message saying which model ran it. With nothing loaded (or no
    server): status needs_model / no_server, and (open_panel=True) the project's AI panel is opened so the person can set the model up; ask again afterwards."""
    if not prompt or not prompt.strip():
        raise InterfaceError('There is no question to ask.')
    url = server_url(project)
    try:
        models = loaded_models(url)
    except (urllib.error.URLError, OSError, ValueError):
        return unready(project, NO_SERVER, f'The AI server at {url} does not answer. Open the AI panel: start Ollama or check the address.', open_panel)
    if not models:
        return unready(project, NEEDS_MODEL, 'No model is loaded. In the AI panel choose and load one (set the parameters there), then ask again.', open_panel)
    model = models[0]
    try:
        answer = call(url + '/api/generate', {'model': model, 'prompt': prompt_text(prompt, code), 'stream': False}, LOAD_WAIT_MS)
    except (urllib.error.URLError, OSError, ValueError) as error:
        return reply(FAILED, f'The model {model} did not answer: {error}', model)
    text = answer.get('response')
    if not isinstance(text, str):
        return reply(FAILED, f'The model {model} gave no answer text.', model)
    return reply(ANSWERED, f'Running with the model that was already loaded: {model}.', model, text)


def unready(project, status, message, open_panel):
    opened = False
    if open_panel:
        try:
            set_model(project)
            opened = True
            message += ' The AI panel was opened.'
        except InterfaceError as error:
            message += f' {error}'
    return reply(status, message, panel_opened=opened)


def set_model(project):
    """Ask the Zygote window that holds this project to open its AI panel. The message goes to the window's own named socket (the one a second start uses to bring it
    forward): no file, no process. Raises InterfaceError when no window holds the project."""
    name = instance_name.name_for(str(Path(project)))
    try:
        if os.name == 'nt':
            with open('\\\\.\\pipe\\' + name, 'wb', buffering=0) as pipe:
                pipe.write(PANEL_MESSAGE)
        else:
            link = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            link.settimeout(1.0)
            try:
                link.connect(os.path.join(tempfile.gettempdir(), name))
                link.sendall(PANEL_MESSAGE)
            finally:
                link.close()
    except OSError:
        raise InterfaceError("Zygote's window for this project is not open, so the AI panel could not be opened.") from None
