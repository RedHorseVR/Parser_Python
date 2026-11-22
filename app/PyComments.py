"""PyComments - what the AST does not keep, and how a piece of the source becomes one line of text.
The AST has no comments, and it counts columns in bytes. This reads the source once with the tokenizer and keeps: every comment (alone on its line, or after code), the lines that continue a string that began on an earlier line, and the tokens (to find the colon that ends a header, and the line of an `else:`).
Lines and columns: lines count from 1, columns are characters (not bytes), a column of the AST is turned into one here with char_col.
No flow rows in here; it only reads the source."""

import io
import re
import tokenize

NEWLINES = re.compile(r"\r\n|\r|\n")
OPEN, CLOSE = "([{", ")]}"
FSTRING_START = getattr(
    tokenize, "FSTRING_START", None
)  #   Python 3.12 and later cut an f-string into tokens
FSTRING_END = getattr(tokenize, "FSTRING_END", None)


class Scan:
    def __init__(self, text):
        self.lines = NEWLINES.split(text)
        self.tokens = []  #   (type, string, (line, col), (line, col)) of every token
        self.standalone = (
            {}
        )  #   line -> (column of the hash, text after the hash) of a line that holds only a comment
        self.trailing = {}  #   line -> text after the hash of a comment after code
        self.comment_col = {}  #   line -> column of the hash, of both kinds
        self.inside = set()  #   the lines that continue a string begun on an earlier line
        self.read(text)

    def read(self, text):
        opened = []
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            self.tokens.append((tok.type, tok.string, tok.start, tok.end))
            if tok.type == tokenize.COMMENT:
                self.note_comment(tok)
            elif tok.type == tokenize.STRING:
                self.mark_inside(tok.start[0], tok.end[0])
            elif tok.type == FSTRING_START:
                opened.append(tok.start[0])
            elif tok.type == FSTRING_END and opened:
                self.mark_inside(opened.pop(), tok.end[0])

    def note_comment(self, tok):
        line, col = tok.start
        raw = tok.string[1:].rstrip()
        self.comment_col[line] = col
        if self.lines[line - 1][:col].strip():
            self.trailing[line] = raw
        else:
            self.standalone[line] = (col, raw)

    def mark_inside(self, first, last):
        self.inside.update(range(first + 1, last + 1))

    # ---- positions ----------------------------------------------------------------------------------
    def char_col(self, line, byte_col):
        """The AST counts a column in bytes of UTF-8; this is the column in characters."""
        return len(self.lines[line - 1].encode("utf-8")[:byte_col].decode("utf-8", "ignore"))

    def indent(self, line):
        text = self.lines[line - 1]
        return len(text) - len(text.lstrip())

    def has_inside(self, first, last):
        """True when a line after `first`, up to `last`, continues a string: the statement has a string over several lines."""
        return any(line in self.inside for line in range(first + 1, last + 1))

    def colon_after(self, line, col):
        """(line, column after it) of the colon that ends the header that starts at (line, col): the first colon outside any brackets."""
        depth = 0
        for kind, string, start, end in self.tokens:
            if start < (line, col) or kind != tokenize.OP:
                continue
            if string in OPEN:
                depth += 1
            elif string in CLOSE:
                depth -= 1
            elif string == ":" and depth == 0:
                return end
        raise ValueError("line %d: no colon ends this header" % line)

    def keyword_line(self, word, col, low, high):
        """The line of the last `word` (else, finally) that stands at column `col`, after line `low` and not after line `high`."""
        found = None
        for kind, string, start, end in self.tokens:
            if (
                kind == tokenize.NAME
                and string == word
                and start[1] == col
                and low < start[0] <= high
            ):
                found = start[0]
        if found is None:
            raise ValueError("lines %d to %d: no `%s` at column %d" % (low, high, word, col))
        return found

    # ---- text ---------------------------------------------------------------------------------------
    def join(self, start, end):
        """The source from `start` to `end` ((line, col) each, `end` not included) as one line: each line trimmed, joined with one space, the comments taken out.
        Returns (text, [(line, text after the hash) of the comments that were inside]).
        """
        first, last = start[0], end[0]
        parts, comments = [], []
        for number in range(first, last + 1):
            text = self.lines[number - 1]
            low = start[1] if number == first else 0
            high = end[1] if number == last else len(text)
            piece = text[low:high]
            cut = self.comment_col.get(number)
            if cut is not None and low <= cut < high:
                comments.append((number, text[cut + 1 :].rstrip()))
                piece = text[low:cut]
            piece = piece.strip()
            if piece.endswith("\\"):
                piece = piece[:-1].rstrip()
            if piece:
                parts.append(piece)
        return " ".join(parts), comments
