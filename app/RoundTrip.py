"""RoundTrip - the check. After the parser has written the flow code file, this reads that file back, writes the Python its rows stand for, and compares it with the source the parser started from.
Both sides are run through Black first, so the quotes, the commas, the splitting of long lines and the spacing of comments are the same on both, and only a real difference is left.
Not compared: blank lines (a flow code file does not carry them) and how far a line that holds only a comment is indented (a comment above an `elif` can stand level with it or with the code above, and Python does not care).
An empty difference is a perfect round trip. The export is kept in memory; it is written to a file only when it differs (see parse_Python.py)."""

import collections
import difflib

import black

import FlowFile
import FlowToPy

LINE_LENGTH = 100  #   the width Black uses on both sides of the check (and before the AST): a statement stays on one row until it is longer than this
Check = collections.namedtuple(
    "Check", "exported difference problem"
)  #   the export (Black's version of it when Black could read it), the unified diff lines, and what went wrong ('' when nothing)


def black_text(text):
    """The text as Black writes it (the one standard of the parser); black.InvalidInput when it is not Python."""
    return black.format_str(text, mode=black.Mode(line_length=LINE_LENGTH))


def squeeze(text):
    """The lines of a text for the comparison: no blank lines, no spaces at the end, and a line that holds only a comment without its indentation."""
    lines = [line.rstrip() for line in text.split("\n") if line.strip()]
    return [line.lstrip() if line.lstrip().startswith("#") else line for line in lines]


def difference(original, exported):
    """The unified diff between the two texts (blank lines and the indentation of comment lines left out); empty when they are the same."""
    return list(
        difflib.unified_diff(
            squeeze(original),
            squeeze(exported),
            "source (Black)",
            "from the flow file (Black)",
            lineterm="",
            n=2,
        )
    )


def check(formatted, flow_path):
    """Read the flow file again, export it, run Black on the export, and compare it with `formatted` (the source as Black wrote it)."""
    exported = FlowToPy.export(FlowFile.read_rows(flow_path, notes=True))
    try:
        exported = black_text(exported)
    except black.InvalidInput as problem:
        return Check(
            exported,
            difference(formatted, exported),
            "Black cannot read the export: %s" % problem,
        )
    return Check(exported, difference(formatted, exported), "")
