# PARSER_PYTHON_0.1.0

The parser is rebuilt. It no longer writes a commented copy of the source and reads that again; it walks the AST once and writes the flow rows.

- Entry point: `python app\parse_Python.py <file.py>`. No file name (or more than one): help, nothing else. The file is never changed; `<file.py>.vfc` is written next to it. `app_tree\bat\RUN.bat` runs it.
- Black first (in memory), then the AST. One statement is one row, so a signature Black cut over four lines is one `input` row (the old two-piece rows are gone). Black must be installed.
- The check (automatic, every run): read the `.vfc` back, export it (FlowToPy.py), run Black, compare with the Black source. Empty difference: PERFECT. Otherwise the diff is printed and the export is saved as `<file.py>.roundtrip.txt`; the next run removes it first.
- Standard of "the same": after Black, blank lines and the indentation of comment-only lines are not compared. Every comment, every string and every statement is.
- Results: the parser's own source, `test_files\*.py` and over 200 files of the Python standard library (checked here, not shipped) (decorators, async, match, f-strings, try/else/finally, loops with else) all come back perfect. The old parser's output for the same file had 557 rows with the doubled markers; this one has no markers.
- Rows: event (import), input/end (def, class), branch/path/bend (if, with, try, match), loop/lend (for, while). A string over several lines, or a statement with a comment inside it, is its first line then `generic` rows exactly as in the source.
- A row cannot hold the four characters that end it (a bracket, semicolon, two slashes). The parser stops and names the text. Its own source writes the mark in two parts.
- New files: `FlowFile.py`, `PyComments.py`, `PyToFlow.py`, `FlowToPy.py`, `RoundTrip.py`, `app_tree\dependencies.json`, `app_tree\bat\RUN_TESTS.bat`, `app_tree\tests\test_parser.py`. The old comment route is `app\extras\parse_Python_comment_route.py`.
- `SYNC_exporter_with_VFlow.md`: what VFlow must take from FlowToPy.py (its paths are one level too deep, so its Export is not valid Python for else/except), and the `VFObj.Extract` bug.
