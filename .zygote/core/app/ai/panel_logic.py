"""The logic behind the AI panel, with no window in it: what each button does and what each part of the panel shows. Plain Python and the standard library
only (no Qt, no Tk), so a project that carries the core can use it with any toolkit. The panel's layout is data (data/ai_panel.json); a renderer for the
toolkit (ui_ux/panel_renderer.py for Qt) builds the parts, sends what the person did here and draws what `view()` says.

How a renderer uses it (the one path, for every button):
  quick(action, inputs)        - changes with no network (target, address, clear_answer). Returns at once.
  plan(action, inputs, arg)    - what the button needs first: {'go': True}, {'ask': text, 'risky': bool} (the renderer asks; No = nothing happens) or
                                 {'skip': True} (nothing to do; the status says why).
  begin(action, inputs, arg)   - the panel is busy now (call it in the window's thread; it raises when an address is wrong).
  run()                        - does the work. BLOCKS (a model can take minutes to load): call it from a worker thread. Ends by making the panel not busy.
  view()                       - what every part shows now, by id.
Nothing here starts Ollama or loads a model by itself: only `begin` + `run` of a button the person pressed."""
import urllib.error

from ai import interface, settings
from ai.ollama import LOAD_WAIT_MS, check_url, human_bytes, inventory_rows, load_risks, worker_gpu

TARGET_NAMES = {'local': 'This computer (Ollama)', 'worker': 'LAN GPU worker'}
LOOK_MS = 8000
UNLOAD_MS = 30000
NETWORK_ERRORS = (urllib.error.URLError, OSError, ValueError)
MODEL_COLUMNS = 5                                           # name, params, disk, capabilities, GPU memory (the layout names them; the button is its own column)


class PanelLogic:
    def __init__(self, project):
        self.busy = False
        self.pending = None
        self.use_project(project)

    def use_project(self, project):
        """Show this project's remembered target and addresses; nothing has been looked at yet."""
        self.project = project
        saved = settings.read(project)
        self.target = saved['target']
        self.urls = {'local': saved['local_url'], 'worker': saved['worker_url']}
        self.looked = False
        self.clear_view('Press Load to look.')
        self.answer, self.last_answer = '', ''
        self.chosen = None

    def clear_view(self, status):
        self.rows, self.load_order, self.gpu = [], [], None
        self.status = status

    # ---- changes with no network
    def adopt(self, inputs):
        """Take what the person typed (the address of the chosen target, the chosen target)."""
        if inputs.get('target') in TARGET_NAMES:
            self.target = inputs['target']
        if 'address' in inputs:
            self.urls[self.target] = inputs['address'].strip()
        if inputs.get('model'):
            self.chosen = inputs['model']

    def keep_settings(self):
        """Remember the target and addresses (raises, loudly, when the chosen address is not an address)."""
        settings.write(self.project, self.target, self.urls['local'], self.urls['worker'])

    def quick(self, action, inputs):
        if action == 'target':                               # another place: its own address, nothing looked at yet
            previous = self.target
            self.adopt({'target': inputs['target'], 'model': inputs.get('model')})
            if self.target != previous:
                self.looked = False
                self.clear_view('Press Load to look.')
        elif action == 'address':
            self.adopt(inputs)
        elif action == 'clear_answer':
            self.answer, self.last_answer = '', ''
        else:
            raise ValueError(f'Unknown quick action: {action!r}')

    # ---- what a button needs first
    def row_named(self, name):
        return next((row for row in self.rows if row['name'] == name), None)

    def risks(self, row):
        state = self.gpu or {}
        return load_risks(row, state.get('total'), state.get('used'))

    def question_for_load(self, name):
        row = self.row_named(name)
        if row is None:
            return {'go': True}
        reasons = self.risks(row)
        if not reasons:
            return {'ask': f'{name} is not loaded.\nLoad it into the GPU first?', 'risky': False}
        return {'ask': f'RISK: loading {name}:\n  - ' + '\n  - '.join(reasons) + '\n\nUnload a model first, or load anyway and risk jamming the GPU?', 'risky': True}

    def plan(self, action, inputs, arg=None):
        self.adopt(inputs)
        if self.busy:
            return {'skip': True}
        if action == 'refresh':
            return {'go': True}
        if action == 'toggle':
            row = self.row_named(arg)
            return {'go': True} if row is None or row['resident'] else self.asked_or_skipped(self.question_for_load(arg), f'Not loaded: {arg}.')
        if action == 'unload_all':
            count = sum(1 for row in self.rows if row['resident'])
            if not count:
                self.status = 'Nothing is loaded.'
                return {'skip': True}
            return {'ask': f'Take all {count} loaded model(s) out of the GPU?', 'risky': False}
        if action == 'send':
            if not inputs.get('model') or not (inputs.get('prompt') or '').strip():
                return {'skip': True}
            row = self.row_named(inputs['model'])
            if row is None or row['resident']:
                return {'go': True}
            return self.asked_or_skipped(self.question_for_load(inputs['model']), f'Not asked: {inputs["model"]} is not loaded.')
        raise ValueError(f'Unknown action: {action!r}')

    @staticmethod
    def asked_or_skipped(question, declined):
        """The question for a Load that needs a Yes; `declined` is what the status says when the answer is No (the renderer calls `declined_status`)."""
        question['declined'] = declined
        return question

    def declined(self, text):
        self.status = text

    # ---- the work
    def begin(self, action, inputs, arg=None):
        """The panel is busy from here (raises, nothing started, when the address is wrong)."""
        self.adopt(inputs)
        check_url(self.urls[self.target])
        self.keep_settings()
        self.pending = (action, dict(inputs), arg)
        self.busy = True
        self.status = {'refresh': 'Asking…', 'unload_all': 'Unloading…', 'send': f'Asking {inputs.get("model")}…',
                       'toggle': f'{"Unloading" if (self.row_named(arg) or {}).get("resident") else "Loading"} {arg}… (a big model can take a minute or more)'}[action]

    def run(self):
        action, inputs, arg = self.pending
        try:
            if action == 'refresh':
                self.refresh()
            elif action == 'toggle':
                self.toggle(arg)
            elif action == 'unload_all':
                self.unload_all()
            elif action == 'send':
                self.send(inputs)
        finally:
            self.pending = None
            self.busy = False

    @property
    def url(self):
        return self.urls[self.target].rstrip('/')

    def get(self, path, body=None, wait=LOOK_MS):
        return interface.call(self.url + path, body, wait)

    def refresh(self):
        """Ask everything the panel shows: version, models, what is in the GPU, each model's capabilities (and a worker's health)."""
        snapshot = {'version': None, 'tags': None, 'ps': None, 'shown': {}, 'health': None, 'errors': []}
        paths = [('version', '/api/version'), ('tags', '/api/tags'), ('ps', '/api/ps')] + ([('health', '/worker/health')] if self.target == 'worker' else [])
        for key, path in paths:
            try:
                answer = self.get(path)
            except NETWORK_ERRORS as error:
                snapshot['errors'].append(f'{path}: {error}')
                continue
            snapshot['version' if key == 'version' else key] = answer.get('version') if key == 'version' else answer
        for entry in (snapshot['tags'] or {}).get('models') or []:        # capabilities: one question per model; a model without an answer shows ?
            name = entry.get('name') or entry.get('model')
            if name:
                try:
                    snapshot['shown'][name] = self.get('/api/show', {'model': name})
                except NETWORK_ERRORS:
                    pass
        self.refreshed(snapshot)

    def refreshed(self, snapshot):
        self.looked = True
        health = snapshot['health']
        if health:
            names, total, used = worker_gpu(health)
            self.gpu = {'names': names, 'total': total, 'used': used}
        if snapshot['tags'] is None:                         # nothing answered: say why, plainly
            self.clear_view(f'NOT REACHED: {"; ".join(snapshot["errors"])}')
            return
        self.rows = inventory_rows(snapshot['tags'], snapshot['ps'], snapshot['shown'])
        resident = [entry.get('name') or entry.get('model') for entry in (snapshot['ps'] or {}).get('models') or []]
        self.load_order = [name for name in self.load_order if name in resident] + [name for name in resident if name not in self.load_order]
        parts = [f'{TARGET_NAMES[self.target]}: READY', f'Ollama {snapshot["version"] or "?"}', f'{len(self.rows)} models']
        for row in self.rows:
            if row['spill']:
                parts.append(f'WARNING: {row["name"]} has {human_bytes(row["spill"])} in CPU memory (it did not fit the GPU): this slows and can freeze the computer')
        if snapshot['errors']:
            parts.append('PROBLEM: ' + '; '.join(snapshot['errors']))
        self.status = ' · '.join(parts)

    def toggle(self, name):
        row = self.row_named(name)
        loaded = bool(row and row['resident'])
        body = {'model': name, 'prompt': '', 'keep_alive': 0 if loaded else -1, 'stream': False}
        try:
            self.get('/api/generate', body, UNLOAD_MS if loaded else LOAD_WAIT_MS)
        except NETWORK_ERRORS as error:
            self.status = f'{"Unload" if loaded else "Load"} {name} FAILED: {error}'
            return
        self.refresh()                                       # the table is read again: it shows what really happened

    def unload_all(self):
        queue = [row['name'] for row in self.rows if row['resident']]
        for name in queue:
            try:
                self.get('/api/generate', {'model': name, 'prompt': '', 'keep_alive': 0, 'stream': False}, UNLOAD_MS)
            except NETWORK_ERRORS as error:
                self.status = f'Unload {name} FAILED: {error}'
                return
        self.refresh()

    def send(self, inputs):
        """Ask the chosen model. A model that is not loaded was asked about first (plan). With Recycle ticked the last answer goes along."""
        model, prompt = inputs['model'], inputs['prompt'].strip()
        recycled = bool(inputs.get('recycle')) and bool(self.last_answer)
        sent = f'{prompt}\n\n{self.last_answer}' if recycled else prompt
        try:
            answer = self.get('/api/generate', {'model': model, 'prompt': sent, 'stream': False}, LOAD_WAIT_MS)
        except NETWORK_ERRORS as error:
            self.status = f'The model did not answer: {error}'
            return
        text = str(answer.get('response', ''))
        banner = f'\n── {model}, answering "{prompt}" about the text above ──\n'
        self.answer = self.answer + banner + text if recycled else text
        self.last_answer = text
        self.status = 'Answered.'
        self.chosen = model

    # ---- what each part shows
    def memory_text(self, row):
        if not row['resident']:
            return '—'
        text = f'{human_bytes(row["vram"])} · #{self.load_order.index(row["name"]) + 1}'
        return text + (f' · ⚠ {human_bytes(row["spill"])} in CPU memory' if row['spill'] else '')

    def view(self):
        """What every part of the panel shows, by the id the layout gave it."""
        rows = []
        for row in self.rows:
            capabilities = '?' if row['capabilities'] is None else ', '.join(row['capabilities'])
            rows.append({'cells': [row['name'], row['params'] or '?', human_bytes(row['disk']), capabilities, self.memory_text(row)],
                         'key': row['name'], 'button': 'Unload' if row['resident'] else 'Load', 'enabled': not self.busy})
        order = sorted(self.rows, key=lambda r: (not r['resident'], self.load_order.index(r['name']) if r['resident'] else 0, r['name'].lower()))
        items = [(('● ' if row['resident'] else '') + row['name'], row['name']) for row in order]
        return {'target': {'items': [(name, key) for key, name in TARGET_NAMES.items()], 'value': self.target, 'enabled': not self.busy},
                'address': {'text': self.urls[self.target], 'enabled': not self.busy},
                'refresh': {'text': 'Refresh' if self.looked else 'Load', 'enabled': not self.busy},
                'unload_all': {'enabled': not self.busy},
                'status': {'text': self.status},
                'models': {'rows': rows},
                'model': {'items': items, 'value': self.chosen if any(value == self.chosen for _, value in items) else (items[0][1] if items else None)},
                'prompt': {'enabled': not self.busy},
                'send': {'enabled': not self.busy},
                'answer': {'text': self.answer},
                'clear_answer': {'enabled': not self.busy}}
