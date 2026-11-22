"""The name a Zygote window listens under (one window per project, and one bare Zygote). Pure: no Qt, so a project's own program (VFlow) can find the window too."""
import hashlib
import os
from pathlib import Path

BARE = 'bare Zygote'


def name_for(key):
    """The socket name of a project folder (any spelling of the same folder gives the same name) or of the bare Zygote."""
    text = key if key == BARE else os.path.normcase(str(Path(key).resolve()))
    return 'zygote-' + hashlib.sha1(text.encode('utf-8')).hexdigest()[:20]
