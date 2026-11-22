r"""parse_Python - a Python file in, a flow code file out, and a check that the flow file says the same thing.
	python app\parse_Python.py <file.py>
1. Black writes the source in one shape (in memory: the file you give is never changed).
2. The AST of that text is walked once and written as rows: <file.py>.vfc, next to the file (PyToFlow).
3. The check reads the .vfc back, writes the Python it stands for, runs Black on that, and compares it with step 1. An empty difference is a perfect round trip; any difference is printed, and the export is saved as <file.py>.roundtrip.txt so it can be looked at.
With no file name, or more than one, it prints this help and stops: nothing is a default. Black is needed (pip install black)."""

import ast
import os
import sys

import FlowFile
import PyComments
import PyToFlow

HELP = """parse_Python: a Python file in, a flow code file (.vfc) out, and a check that the flow file says the same thing.

    python app\\parse_Python.py <file.py>

The file you give is never changed. The flow file is written next to it as <file.py>.vfc.
Black is needed: pip install black"""
LEFTOVER = ".roundtrip.txt"  #   the export of a run that was not perfect: written next to the source, removed when the next run starts


def clean_text(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def rows_of(text):
    """The flow rows of Python text (already as Black writes it)."""
    return PyToFlow.Walker(PyComments.Scan(text)).walk(ast.parse(text))


def export_name(path):
    """What VFlow's Export names the code file: an underscore in front of the name, so it never lands on the source."""
    return "_" + os.path.basename(path)


def say_difference(path, result):
    leftover = path + LEFTOVER
    with open(leftover, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(result.exported)
    print("  check      NOT PERFECT: the flow file does not say the same thing as the source")
    if result.problem:
        print("             " + result.problem)
    for line in result.difference:
        print(line)
    print("  the export is saved as %s (it is removed when the next run starts)" % leftover)


def run(path):
    """Parse the file and check it. True when the round trip is perfect."""
    import RoundTrip  #   needs Black: the import says so when it is missing

    leftover = path + LEFTOVER
    if os.path.exists(leftover):
        os.remove(leftover)
    with open(path, "r", encoding="utf-8", newline="") as handle:
        text = clean_text(handle.read())
    print("parse_Python  %s" % path)
    try:
        formatted = RoundTrip.black_text(text)
    except RoundTrip.black.InvalidInput as problem:
        print("  black      cannot read this file as Python: %s" % problem)
        return False
    rows = rows_of(formatted)
    flow_path = path + ".vfc"
    FlowFile.write_file(flow_path, rows, export_name(path))
    print(
        "  parse      %d rows  ->  %s"
        % (len([r for r in rows if r.kind != FlowFile.NOTE]), flow_path)
    )
    result = RoundTrip.check(formatted, flow_path)
    if result.difference or result.problem:
        say_difference(path, result)
        return False
    print(
        "  check      PERFECT: the flow file exports back to the same code (the same after Black, blank lines and comment indentation not compared)"
    )
    return True


def main(argv):
    if len(argv) != 2:
        print(HELP)
        return 0
    if not os.path.isfile(argv[1]):
        print("parse_Python: no such file: %s" % argv[1])
        return 1
    try:
        return 0 if run(argv[1]) else 1
    except ImportError as problem:
        if getattr(problem, "name", "") != "black":
            raise
        print("parse_Python needs Black and it is not installed. Run: pip install black")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
