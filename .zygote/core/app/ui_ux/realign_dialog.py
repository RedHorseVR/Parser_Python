"""The Realign panel of an AI agent: a MODAL window (nothing else can be used until it is closed). It shows the agent's current prompt, a box for what the person wants
changed (typed or dictated), the connected model's reply (its questions, or AFFIRMATIVE), and Save, which makes the prompt of THAT agent in THAT project.
It holds no logic of its own: the window that opens it hands over what to do (ask the model, dictate, save, reset)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout

from ai import prompts


class RealignDialog(QDialog):
    def __init__(self, parent, agent, prompt, changed, ask, dictate, save, reset, microphone):
        super().__init__(parent)
        self.agent, self.ask, self.dictate, self.save_text, self.reset_text = agent, ask, dictate, save, reset
        self.setModal(True)
        self.setWindowTitle(f'Realign — {agent}')
        self.resize(820, 760)
        layout = QVBoxLayout(self)
        self.state = QLabel('')
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        layout.addWidget(QLabel('<b>The prompt this agent uses now</b>'))
        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        layout.addWidget(self.prompt_view, 3)
        row = QHBoxLayout()
        row.addWidget(QLabel('<b>What I want changed</b>'), 1)
        self.mic_button = QToolButton()
        self.mic_button.setIcon(microphone)
        self.mic_button.setToolTip('Dictate into this box: starts Windows voice typing (Win+H) with the cursor in the box')
        row.addWidget(self.mic_button)
        layout.addLayout(row)
        self.change = QPlainTextEdit()
        self.change.setPlaceholderText('Say what the agent should do differently. Nothing is changed until you press Save.')
        layout.addWidget(self.change, 2)
        self.send_button = QPushButton('Send to the model')
        self.send_button.setToolTip('The model checks your words against the prompt: it answers AFFIRMATIVE, or with its questions and objections.')
        layout.addWidget(self.send_button)
        layout.addWidget(QLabel('<b>The model says</b>'))
        self.reply = QPlainTextEdit()
        self.reply.setReadOnly(True)
        layout.addWidget(self.reply, 2)
        buttons = QHBoxLayout()
        self.save_button = QPushButton('Save')
        self.save_button.setToolTip('Your words become part of this agent\'s prompt, in this project only. (A reply from the model is not needed to save.)')
        self.reset_button = QPushButton('Back to the standard prompt')
        self.close_button = QPushButton('Close')
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.show_prompt(prompt, changed)
        self.mic_button.clicked.connect(self.dictating)
        self.send_button.clicked.connect(self.send)
        self.save_button.clicked.connect(self.save)
        self.reset_button.clicked.connect(self.back)
        self.close_button.clicked.connect(self.reject)

    def show_prompt(self, prompt, changed):
        self.prompt_view.setPlainText(prompt)
        self.state.setText('This agent uses the prompt <b>saved for this project</b>.' if changed else 'This agent uses the <b>standard</b> prompt (nothing saved for this project).')
        self.reset_button.setEnabled(changed)

    def say(self, text, bad=False):
        self.reply.setPlainText(text)
        self.reply.setStyleSheet('color: #c0392b;' if bad else '')

    def dictating(self):
        self.change.setFocus()
        self.dictate()

    def send(self):
        words = self.change.toPlainText().strip()
        if not words:
            self.say('Write or dictate what you want changed first.', bad=True)
            return
        self.send_button.setEnabled(False)
        self.say('Asking the model…')
        self.ask(self.prompt_view.toPlainText(), words, self.answered)

    def answered(self, ok, text):
        self.send_button.setEnabled(True)
        if not ok:
            self.say(text, bad=True)
        elif prompts.is_affirmative(text):
            self.say('AFFIRMATIVE: the model finds no conflict. Press Save to keep your words in the prompt.')
        else:
            self.say(text)

    def save(self):
        words = self.change.toPlainText().strip()
        if not words:
            self.say('There is nothing to save: write or dictate what you want changed first.', bad=True)
            return
        prompt, changed = self.save_text(self.prompt_view.toPlainText(), words)
        self.show_prompt(prompt, changed)
        self.change.clear()
        self.say('Saved. This is now the prompt of this agent in this project.')

    def back(self):
        prompt, changed = self.reset_text()
        self.show_prompt(prompt, changed)
        self.say('The standard prompt is back.')
