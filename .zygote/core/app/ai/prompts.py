"""The prompt of each agent, as DATA. The standard text of an agent is in data/agent_prompts.json (Zygote's own); what the person saved through the Realign panel
is kept per project, per agent, in the project's private record (.zygote\\user\\zygote.json, key "ai_prompts"). A project's text wins over the standard one.
A prompt holds the words {layout} {overview} {extra} {arrow} {items} where the program puts the facts of the run; {layout} and {items} must stay.
No Qt here. Everything is checked when it is read or written; a wrong record raises, it is never repaired silently."""
import json
from pathlib import Path

from functional import core

DEFAULTS_FILE = Path(__file__).resolve().parents[1] / 'data' / 'agent_prompts.json'
REQUIRED = ('{layout}', '{items}')
AFFIRMATIVE = 'AFFIRMATIVE'
CHANGE_HEAD = 'Also, from the person who owns this project:'


def defaults():
    found = json.loads(DEFAULTS_FILE.read_text(encoding='utf-8'))
    if not (isinstance(found, dict) and found and all(isinstance(key, str) and isinstance(text, str) and text.strip() for key, text in found.items())):
        raise core.ZygoteError(f'{DEFAULTS_FILE} must hold the prompt text of each agent.')
    return found


def default_text(agent):
    found = defaults()
    if agent not in found:
        raise core.ZygoteError(f'The agent {agent!r} has no prompt text.')
    return found[agent]


def check(text):
    if not isinstance(text, str) or not text.strip():
        raise core.ZygoteError('A prompt cannot be empty.')
    missing = [word for word in REQUIRED if word not in text]
    if missing:
        raise core.ZygoteError(f'The prompt must keep {" and ".join(missing)} (the program puts the layout and the items there).')


def saved(project):
    found = core.load_state(project).get('ai_prompts', {})
    if not (isinstance(found, dict) and all(isinstance(key, str) and isinstance(text, str) for key, text in found.items())):
        raise core.ZygoteError(f'The saved agent prompts are wrong: {found!r}.')
    return found


def read(project, agent):
    """The prompt this agent uses in this project: the saved one, else the standard one."""
    return saved(project).get(agent) or default_text(agent)


def is_changed(project, agent):
    return agent in saved(project)


def write(project, agent, text):
    default_text(agent)                                       # the agent must exist
    check(text)
    state = core.load_state(project)
    kept = dict(saved(project))
    kept[agent] = text
    state['ai_prompts'] = kept
    core.save_state(project, state)


def reset(project, agent):
    """Back to the standard text (the saved one is removed)."""
    state = core.load_state(project)
    kept = dict(saved(project))
    if kept.pop(agent, None) is not None:
        state['ai_prompts'] = kept
        if not kept:
            del state['ai_prompts']
        core.save_state(project, state)


def with_change(prompt, change):
    """The prompt and the person's new words together (what is sent to the model to check, and what Save keeps)."""
    if not change.strip():
        return prompt
    block = f'{CHANGE_HEAD}\n{change.strip()}\n\n'
    if '\nItems:\n{items}' in prompt:                          # the new words go before the list of items, which stays last
        return prompt.replace('\nItems:\n{items}', '\n' + block + 'Items:\n{items}', 1)
    return prompt.rstrip() + '\n\n' + block.rstrip() + '\n'


def realign_question(prompt, change):
    """What the connected model is asked: do the new words fight the instructions already there? It answers AFFIRMATIVE, or its questions and objections."""
    return ('Below is the prompt of an AI agent, then new words the owner wants added to it. Check them against each other.\n'
            f'If the new words fit, do not contradict an instruction already there and are clear, answer with the single word {AFFIRMATIVE}.\n'
            'Otherwise answer with short numbered questions or objections, one for each conflict or unclear point. No rewriting, no other text.\n\n'
            f'--- THE PROMPT ---\n{prompt.strip()}\n\n--- THE NEW WORDS ---\n{change.strip()}\n')


def is_affirmative(answer):
    return answer.strip().strip('.!"\'`* ').upper() == AFFIRMATIVE
