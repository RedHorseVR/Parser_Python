"""Syntax colours for the code window. One Language per kind of file (its extensions and its token rules); a Highlighter paints a document with one.
Python and Windows batch are the baseline. More languages are added with register(Language(...)) - the rules are plain regular expressions per token
kind, and the colours are one table (COLOURS) that set_colour() changes, so VFlow's language and colour settings can feed both later."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

COLOURS = {                                                         # token kind -> colour (the dark theme's usual Python colours)
    'keyword': '#569cd6', 'builtin': '#4ec9b0', 'string': '#ce9178', 'comment': '#6a9955', 'number': '#b5cea8',
    'decorator': '#dcdcaa', 'label': '#c586c0', 'variable': '#9cdcfe',
}


@dataclass
class Language:
    name: str
    extensions: tuple
    rules: list                                                     # [(kind, regex)], the first rule that matches at a place wins
    blocks: list = field(default_factory=list)                      # [(start regex, end regex, kind)]: spans that run over several lines
    ignore_case: bool = False


PYTHON_WORDS = ('and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal '
                'not or pass raise return try while with yield match case').split()
PYTHON_BUILTINS = ('True False None self cls print len range int str float list dict set tuple bool bytes open super isinstance type object '
                   'Exception ValueError KeyError TypeError OSError').split()
BATCH_WORDS = ('if else not exist defined errorlevel goto call for in do set setlocal endlocal enabledelayedexpansion echo off on pause exit start cd '
               'md mkdir rd rmdir del copy xcopy move ren type cls title color path pushd popd shift choice timeout').split()
STRING_PREFIX = r'(?:[rRbBuUfF]{1,2})?'


def words(names):
    return r'\b(?:' + '|'.join(names) + r')\b'


PYTHON = Language(
    'Python', ('.py', '.pyw', '.pyi'),
    [('comment', r'#[^\n]*'),
     ('string', STRING_PREFIX + r'"(?:\\.|[^"\\\n])*"?'),
     ('string', STRING_PREFIX + r"'(?:\\.|[^'\\\n])*'?"),
     ('number', r'\b(?:0[xX][0-9a-fA-F_]+|\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?)\b'),
     ('decorator', r'^\s*@[\w.]+'),
     ('keyword', words(PYTHON_WORDS)),
     ('builtin', words(PYTHON_BUILTINS))],
    [(STRING_PREFIX + '"""', '"""', 'string'), (STRING_PREFIX + "'''", "'''", 'string')])

BATCH = Language(
    'Batch', ('.bat', '.cmd'),
    [('comment', r'^\s*(?:@?rem\b[^\n]*|::[^\n]*)'),
     ('label', r'^\s*:[\w.-]+'),
     ('string', r'"[^"\n]*"?'),
     ('variable', r'%~?[\w*]+%?|![\w]+!'),
     ('number', r'\b\d+\b'),
     ('keyword', words(BATCH_WORDS))],
    ignore_case=True)

LANGUAGES = {}                                                      # extension -> Language


def register(language):
    """Add a language (or replace the one that owns the same extensions)."""
    for extension in language.extensions:
        LANGUAGES[extension.lower()] = language
    return language


def language_for(path):
    """The Language of a file by its extension, or None (the file is shown in plain colours)."""
    return LANGUAGES.get(Path(str(path)).suffix.lower())


def set_colour(kind, colour):
    COLOURS[kind] = colour


class Scanner:
    """One regular expression made from a Language's rules and blocks: the leftmost match decides, so a # inside a string is not a comment."""

    def __init__(self, language):
        self.kinds = []
        parts = []
        for start, _, kind in language.blocks:
            parts.append(f'(?P<k{len(parts)}>{start})')
            self.kinds.append(kind)
        for kind, pattern in language.rules:
            parts.append(f'(?P<k{len(parts)}>{pattern})')
            self.kinds.append(kind)
        self.blocks = [re.compile(end, re.I if language.ignore_case else 0) for _, end, _ in language.blocks]
        self.regex = re.compile('|'.join(parts), re.M | (re.I if language.ignore_case else 0))

    def match_at(self, text, position):
        found = self.regex.search(text, position)
        if found is None:
            return None, None
        return found, int(found.lastgroup[1:])


class Highlighter(QSyntaxHighlighter):
    """Paints one document with one Language. The state of a block says which multi-line span it ends inside (0 = none)."""

    def __init__(self, document, language):
        super().__init__(document)
        self.language = language
        self.scanner = Scanner(language)
        self.formats = {}
        for kind, colour in COLOURS.items():
            self.formats[kind] = self.make_format(colour)

    @staticmethod
    def make_format(colour):
        one = QTextCharFormat()
        one.setForeground(QColor(colour))
        return one

    def paint(self, start, end, kind):
        if end > start and kind in self.formats:
            self.setFormat(start, end - start, self.formats[kind])

    def continue_block(self, text, index):
        """A line that starts inside a multi-line span: painted up to the end of the span. Returns where normal scanning goes on (None: the span goes on)."""
        found = self.scanner.blocks[index].search(text)
        kind = self.scanner.kinds[index]
        if found is None:
            self.paint(0, len(text), kind)
            return None
        self.paint(0, found.end(), kind)
        return found.end()

    def highlightBlock(self, text):
        self.setCurrentBlockState(0)
        position = 0
        inside = self.previousBlockState()
        if inside > 0:
            position = self.continue_block(text, inside - 1)
            if position is None:
                self.setCurrentBlockState(inside)
                return
        count = len(self.language.blocks)
        while position <= len(text):
            found, index = self.scanner.match_at(text, position)
            if found is None:
                return
            kind = self.scanner.kinds[index]
            if index < count:                                       # a multi-line span starts here
                end = self.scanner.blocks[index].search(text, found.end())
                if end is None:
                    self.paint(found.start(), len(text), kind)
                    self.setCurrentBlockState(index + 1)
                    return
                self.paint(found.start(), end.end(), kind)
                position = end.end()
                continue
            self.paint(found.start(), found.end(), kind)
            position = max(found.end(), position + 1)


register(PYTHON)
register(BATCH)


def attach(document, path):
    """The Highlighter of a file's language on this document, or None (no language known for the extension)."""
    language = language_for(path)
    return None if language is None else Highlighter(document, language)
