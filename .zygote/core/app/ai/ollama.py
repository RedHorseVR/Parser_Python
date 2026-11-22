"""Ollama's API, as spoken to a local Ollama or to a LAN GPU worker (the worker passes /api/* through to its Ollama and adds /worker/health).
Pure data in, pure data out: the rows the panel shows are made here, so they can be tested without a window."""
import functools
from urllib.parse import urlsplit

from functional.core import ZygoteError

LOCAL_URL = 'http://127.0.0.1:11434'                        # Ollama's own address on this computer
LOAD_WAIT_MS = 300000                                       # loading a big model into the GPU can take minutes


def check_url(text):
    """A base address like http://host:port. Raises ZygoteError for anything else."""
    text = (text or '').strip().rstrip('/')
    parts = urlsplit(text)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ZygoteError(f'"{text}" is not an address. Write it like http://192.168.1.20:11435')
    return text


def human_bytes(count):
    if not isinstance(count, (int, float)) or count < 0:
        return '?'
    value = float(count)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024


def inventory_rows(tags, ps, shown):
    """The model table. tags: /api/tags, ps: /api/ps (what sits in the GPU now), shown: {model name: /api/show answer} (may miss models).
    A value the server did not give is None (the panel shows ?), never a made-up one."""
    resident = {entry.get('name') or entry.get('model'): entry for entry in (ps or {}).get('models') or []}
    rows = []
    for entry in (tags or {}).get('models') or []:
        name = entry.get('name') or entry.get('model')
        if not name:
            continue
        details = entry.get('details') or {}
        info = shown.get(name)
        loaded = resident.get(name)
        rows.append({'name': name,
                     'params': details.get('parameter_size'),
                     'disk': entry.get('size'),
                     'capabilities': list(info.get('capabilities') or []) if isinstance(info, dict) and 'capabilities' in info else None,
                     'resident': loaded is not None,
                     'vram': loaded.get('size_vram') if loaded else None,
                     'spill': spill_bytes(loaded)})
    return sorted(rows, key=lambda row: row['name'].lower())


SPILL_TOLERANCE = 0.05                                     # up to 5% of a model outside the GPU is rounding, not a spill
LOAD_LIMIT_PERCENT = 80                                    # loading another model when more of the GPU memory than this is used asks first


def spill_bytes(loaded):
    """How many bytes of a loaded model sit outside the GPU (in CPU memory), or 0. `loaded`: its /api/ps entry (None: not loaded)."""
    if not loaded or not isinstance(loaded.get('size'), (int, float)) or not isinstance(loaded.get('size_vram'), (int, float)):
        return 0
    outside = loaded['size'] - loaded['size_vram']
    return outside if outside > SPILL_TOLERANCE * loaded['size'] else 0


def load_risks(row, total_mib, used_mib):
    """The reasons loading this model into the GPU is risky now (a list of texts; empty = no reason). total_mib / used_mib: the GPU memory
    (None when not known: then nothing can be judged and nothing is claimed)."""
    reasons = []
    if not total_mib or used_mib is None:
        return reasons
    percent = used_mib * 100 / total_mib
    if percent > LOAD_LIMIT_PERCENT:
        reasons.append(f'the GPU memory is already {percent:.0f}% used')
    free = total_mib - used_mib
    if isinstance(row.get('disk'), (int, float)) and row['disk'] / 2 ** 20 > free:
        reasons.append(f'the model is {human_bytes(row["disk"])} and only {free / 1024:.1f} GB of GPU memory is free: the part that does not fit '
                       'goes into CPU memory, which can freeze the computer')
    return reasons


def check_uses(uses):
    """What a project keeps of what each model is used for: {model name: {text, image, analysis: true/false}}. Raises ZygoteError otherwise."""
    if not isinstance(uses, dict):
        raise ZygoteError(f'The saved model uses are wrong: {uses!r}.')
    for name, kinds in uses.items():
        if not (isinstance(name, str) and isinstance(kinds, dict) and set(kinds) == {'text', 'image', 'analysis'}
                and all(isinstance(value, bool) for value in kinds.values())):
            raise ZygoteError(f'The saved uses of model {name!r} are wrong: {kinds!r}.')
    return uses


def worker_gpu(health):
    """(names, total MiB, used MiB) from a LAN worker's /worker/health. Used is None when the worker gave no numbers."""
    gpu = health.get('gpu') or []
    mib = health.get('gpu_mib') or {}
    names = [line.split(',')[0].strip() for line in gpu if isinstance(line, str)]
    return names, mib.get('total'), mib.get('used')


DEFAULT_MODEL = 'qwen2.5-coder'                              # the code model Zygote recommends first
CODER_SIZES = ((24, '32b'), (12, '14b'), (6, '7b'), (3, '3b'))     # (GB of video memory at least, the size that fits it)


def recommend_model(total_mib):
    """(the model tag, the sentence that says why) for a video card of total_mib MiB (None: no card was read). One model at a time must fit the card."""
    if not total_mib:
        return f'{DEFAULT_MODEL}:1.5b', 'No video card was read: a small model that can run on the processor.'
    gigabytes = total_mib / 1024
    for need, size in CODER_SIZES:
        if gigabytes >= need:
            return f'{DEFAULT_MODEL}:{size}', f'Fits the {gigabytes:.0f} GB of video memory, one model at a time.'
    return f'{DEFAULT_MODEL}:1.5b', f'Only {gigabytes:.0f} GB of video memory: a small model.'


class PullProgress:
    """What the pull says as it goes: the step, the percent, the size, the speed and the time left. Ollama reports each file of the model in turn with
    `completed` and `total` bytes; the speed is measured on the file that is coming in now. `clock` is time.monotonic (a test gives its own)."""

    def __init__(self, model, clock=None):
        import time
        self.model = model
        self.clock = clock or time.monotonic
        self.digest = None
        self.mark = None                                     # (time, completed) at the start of the file in view
        self.percent = None                                  # None while there is no number to show
        self.error = None

    def feed(self, event):
        """One progress line from Ollama. Returns the sentence to show."""
        if event.get('error'):
            self.error = event['error']
            return f'{self.model}: {self.error}'
        total, completed = event.get('total'), event.get('completed')
        if not total:
            self.percent = None
            return f'{self.model}: {event.get("status", "working")}…'
        now = self.clock()
        digest = event.get('digest')
        if digest != self.digest or self.mark is None:
            self.digest, self.mark = digest, (now, completed or 0)
        self.percent = int((completed or 0) * 100 / total)
        text = f'{self.model}: {self.percent}% ({human_bytes(completed or 0)} of {human_bytes(total)})'
        seconds, start = now - self.mark[0], self.mark[1]
        if seconds >= 1 and (completed or 0) > start:
            speed = ((completed or 0) - start) / seconds
            left = int((total - (completed or 0)) / speed)
            text += f', {human_bytes(int(speed))}/s, about {left // 60} min {left % 60} s left' if left >= 60 else f', {human_bytes(int(speed))}/s, about {left} s left'
        return text


class Ollama:
    def __init__(self, http, url, worker=False):
        self.http = http
        self.url = check_url(url)
        self.worker = worker                                # True: a LAN GPU worker (it also has /worker/health)

    def get(self, path, done, timeout_ms=8000):
        self.http.call('GET', self.url + path, None, done, timeout_ms)

    def post(self, path, body, done, timeout_ms=15000):
        self.http.call('POST', self.url + path, body, done, timeout_ms)

    def load(self, model, done):
        """Put a model into the GPU and keep it there (until unloaded)."""
        self.post('/api/generate', {'model': model, 'prompt': '', 'keep_alive': -1, 'stream': False}, done, LOAD_WAIT_MS)

    def pull(self, model, on_event, done):
        """Download a model to the disk (an HTTP call to Ollama; nothing is loaded into memory). Its progress lines arrive one by one in on_event."""
        self.http.stream(self.url + '/api/pull', {'model': model, 'stream': True}, on_event, done)

    def unload(self, model, done):
        self.post('/api/generate', {'model': model, 'prompt': '', 'keep_alive': 0, 'stream': False}, done, 30000)

    def generate(self, model, prompt, done, images=None, options=None, keep_alive=None):
        """Ask one question. images: pictures as base64 text (only for a model that can see). options: Ollama's own (temperature, num_ctx...)."""
        body = {'model': model, 'prompt': prompt, 'stream': False}
        if options:
            body['options'] = dict(options)
        if keep_alive is not None:                           # -1: the model stays in the GPU after the answer (Ollama's own default unloads it after five minutes)
            body['keep_alive'] = keep_alive
        if images:
            body['images'] = list(images)
        self.post('/api/generate', body, done, LOAD_WAIT_MS)


class Refresh:
    """Ask everything the panel shows, all at once, and call `done(snapshot)` when the last answer is in. snapshot: version, tags, ps, shown,
    health (workers only), errors (a list of texts; an empty list means everything answered)."""

    def __init__(self, ollama, done):
        self.ollama = ollama
        self.done = done
        self.snapshot = {'version': None, 'tags': None, 'ps': None, 'shown': {}, 'health': None, 'errors': []}
        self.waiting = 0
        self.names = []

    def ask(self, path, key, post=None):
        self.waiting += 1
        callback = functools.partial(self.got, key)
        if post is None:
            self.ollama.get(path, callback)
        else:
            self.ollama.post(path, post, callback)

    def start(self):
        self.ask('/api/version', 'version')
        self.ask('/api/tags', 'tags')
        self.ask('/api/ps', 'ps')
        if self.ollama.worker:
            self.ask('/worker/health', 'health')

    def got(self, key, ok, data):
        self.waiting -= 1
        shown = isinstance(key, tuple)                      # ('show', model name): the answer about one model
        if not ok:
            if not shown:                            # a model without a /api/show answer is shown with ? capabilities; the rest is a real failure
                self.snapshot['errors'].append(data)
        elif key == 'version':
            self.snapshot['version'] = data.get('version')
        elif key == 'tags':
            self.snapshot['tags'] = data
            for entry in data.get('models') or []:          # capabilities need one question per model, asked as soon as the list is known
                name = entry.get('name') or entry.get('model')
                if name:
                    self.ask('/api/show', ('show', name), {'model': name})
        elif key in ('ps', 'health'):
            self.snapshot[key] = data
        elif shown:
            self.snapshot['shown'][key[1]] = data
        if self.waiting == 0:
            self.done(self.snapshot)
