"""FlowToPy - the rows of a flow code file as Python. This is the check's half of the round trip: the parser writes the rows, this reads them back and writes the code they stand for.
Taken from VFlow's Export (VFExport.code_text and VFCodeView.tree_items): the same tree of what is inside what, with one change that Python needs. VFlow's Export puts `else:`, `elif`, `except` and `finally` one level deeper than the `if` or `try` they belong to, which is not valid Python; here a path stands level with its branch, and its body is one level in.
When the parsers share a library this module moves into it, as it is.
	input / loop / branch     its line, then what is inside one level in; its closer (end, lend, bend) writes nothing
	path                      an empty path writes nothing; `else:`, `elif x:`, `except E:` stand level with the branch or loop; a `case` stands one level in from `match`
	generic                   the line exactly as it is (the lines of a string over several lines)
	any other row             its text, then two spaces and # and its comment; a row with no text is a comment line, or an empty line."""

from FlowFile import BEGIN_VAR, END_VAR, NOTE, FlowError

CLOSERS = {"end": "input", "bend": "branch", "lend": "loop"}
OPENERS = ("input", "loop", "branch")
INDENT = "    "


class Exporter:
    def __init__(self):
        self.lines = []
        self.stack = (
            []
        )  #   [kind, depth of the line that opened it, 1 for a match (its cases are one level in)]
        self.depth = 0  #   the depth of the lines being written
        self.box = False  #   inside a begin and end mark: the generic rows are code, indented from where the box stands

    def run(self, rows):
        for number, row in enumerate(rows, 1):
            self.one(number, row)
        if self.stack:
            raise FlowError("the rows end with a %s that is never closed" % self.stack[-1][0])
        return "".join(line + "\n" for line in self.lines)

    def one(self, number, row):
        if row.kind == NOTE:
            self.box = row.text == BEGIN_VAR
        elif row.kind in OPENERS:
            self.put(self.depth, row)
            self.stack.append([row.kind, self.depth, 1 if self.is_match(row) else 0])
            self.depth += 1
        elif row.kind == "path":
            self.path(number, row)
        elif row.kind in CLOSERS:
            self.close(number, row)
        else:
            self.put(self.depth, row)

    @staticmethod
    def is_match(row):
        return row.kind == "branch" and row.text.split(None, 1)[:1] == ["match"]

    def path(self, number, row):
        if not self.stack or self.stack[-1][0] not in ("branch", "loop"):
            raise FlowError("row %d: a path outside a branch or a loop" % number)
        kind, opened, extra = self.stack[-1]
        if row.text.strip():
            self.put(opened + extra, row)
        self.depth = opened + 1 + extra

    def close(self, number, row):
        if not self.stack or self.stack[-1][0] != CLOSERS[row.kind]:
            raise FlowError("row %d: %s closes nothing" % (number, row.kind))
        self.depth = self.stack.pop()[1]

    def put(self, depth, row):
        if row.kind == "generic" and self.box:
            level = len(row.text) - len(row.text.lstrip("\t"))  #   a tab in front of a row of a box is one level
            self.lines.append(INDENT * (depth + level) + row.text[level:] if row.text.strip() else "")
        elif row.kind == "generic":
            self.lines.append(row.text)
        elif not row.text and row.comment is None:
            self.lines.append("")
        elif not row.text:
            self.lines.append(INDENT * depth + "#" + row.comment)
        elif row.comment is None:
            self.lines.append(INDENT * depth + row.text)
        else:
            self.lines.append(INDENT * depth + row.text + "  #" + row.comment)


def export(rows):
    """The Python text of the rows."""
    return Exporter().run(rows)
