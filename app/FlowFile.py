"""FlowFile - the rows of a flow code file (.vfc): how a row is written, how it is read, and the footer at the bottom. No AST and no Tk in here.
A row is one line: the kind, then the text in round brackets, then the end mark (a bracket, a semicolon and two slashes), then the comment.
	kind    set, event, input, end, branch, path, bend, loop, lend (the ones the parser writes) and generic: a line that is written exactly as it is.
	text    the code of the row on one line
	comment what stands after the hash mark in the code, with no hash. One space is put in front of it in the file, so `#  two` and `# one` come back as they were.
Rows can only be written and read here, so the parser and its check agree on what a row is."""

import collections

Row = collections.namedtuple(
    "Row", "kind text comment"
)  #   comment is None when the code line has none

NOTE = "note"  #   not a row: a line that starts with ; and is written as it is (the begin var and end var marks). The file reader skips it, so nothing downstream sees it.
BEGIN_VAR = ";@beginvar"
END_VAR = ";@endvar"
KINDS = (
    "set",
    "generic",
    "input",
    "event",
    "process",
    "output",
    "loop",
    "lend",
    "branch",
    "path",
    "bend",
    "end",
)
DELIM = (
    ");" + "//"
)  #   written in two parts: a row cannot hold this text, and the parser reads its own source
FOOTER_HEAD = ";INSECTA"
LINE_END = "\r\n"  #   the legacy tool wrote rows this way; VFlow reads both


class FlowError(Exception):
    """A flow code file that cannot be read as rows, or rows that do not close."""


def row_line(row):
    """The row as the line of the file (no line ending). A row whose text holds the end mark cannot be read back, so it is refused."""
    if row.kind == NOTE:
        return row.text
    if DELIM in row.text:
        raise FlowError(
            "this text holds %s, which ends a row, so it cannot be written as a row: %s"
            % (DELIM, row.text)
        )
    field = "" if row.comment is None else " " + row.comment
    return "%s(%s%s%s" % (row.kind, row.text, DELIM, field)


def parse_line(line, number):
    """The Row of a line of the file; None for a line that holds no row (blank, or a note that starts with ;)."""
    line = line.rstrip("\r\n")
    if not line.strip() or line.startswith(";"):
        return None
    for kind in KINDS:
        if line.startswith(kind + "("):
            text, found, field = line[len(kind) + 1 :].partition(DELIM)
            if not found:
                raise FlowError("line %d: no %s in this row: %s" % (number, DELIM, line))
            if field == "":
                return Row(kind, text, None)
            return Row(kind, text, field[1:] if field.startswith(" ") else field)
    raise FlowError("line %d: not a flow row: %s" % (number, line))


def read_rows(path, notes=False):
    """The rows of the file, down to the footer (the first line that starts with ;INSECTA). With `notes`, the begin and end marks of a box are rows too (kind note): the export needs them."""
    rows = []
    with open(path, "r", encoding="utf-8", newline=None) as handle:
        for number, line in enumerate(handle, 1):
            if line.startswith(FOOTER_HEAD):
                break
            row = parse_line(line, number)
            if row is not None:
                rows.append(row)
            elif notes and line.strip() in (BEGIN_VAR, END_VAR):
                rows.append(Row(NOTE, line.strip(), None))
    return rows


def footer_lines(export_name):
    """The session lines at the bottom: colours, the language key (python.key), and the name VFlow's Export gives the code file (the Export name box)."""
    return [
        ";INSECTA EMBEDDED SESSION INFORMATION",
        "; 255 16777215 65280 16777088 16711680 32896 8421504 0 255 255 16777215 4227327 2097168",
        ";    %s   #   ." % export_name,
        "; notepad.exe",
        ";INSECTA EMBEDDED ALTSESSION INFORMATION",
        "; 1210 83 799 852 1 110   378   72    python.key  0",
        ";INSECTA EMBEDDED VIEW INFORMATION",
        "; comments 1",
        "; codetab Code tree",
        "; codeorder Code tree|Flow code|Objects",
        "; export %s" % export_name,
    ]


def file_text(rows, export_name):
    """The whole file: the rows, then the footer."""
    lines = [row_line(row) for row in rows] + [""] + footer_lines(export_name)
    return "".join(line + LINE_END for line in lines)


def write_file(path, rows, export_name):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(file_text(rows, export_name))
