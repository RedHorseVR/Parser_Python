# START HERE — Parser_Python

> **Project:** Parser_Python. **Version:** read `.zygote\VERSION.txt` (first line). This file is the running build log; started from the folder Parser_Python on 2026-11-21.

## State
- PARSER_PYTHON_0.0.1: the Zygote tree (`.zygote`) was added to the folder on 2026-11-21. Nothing that was already there was changed.
- PARSER_PYTHON_0.1.0 (2026-11-21): the parser is rebuilt. Black, then one AST pass writes the `.vfc`; the check reads it back, exports it, runs Black and compares. Entry: `python app\parse_Python.py <file.py>` (`app_tree\bat\RUN.bat`). Tests: `app_tree\bat\RUN_TESTS.bat`. The old comment route is in `app\extras`.

- PARSER_PYTHON_0.1.5: `app\SameProgram.py` compares two Python files as the same program in a different order (AST, order free at top and in a class). 42 tests.
- PARSER_PYTHON_0.1.4: a var box has one tab for each level of four spaces; FlowToPy reads a tab as one level.
- PARSER_PYTHON_0.1.3: RUN.bat has no pause (it was added in 0.1.1 at Luis's request, taken out at his request).
- PARSER_PYTHON_0.1.2: a var box has no white space in front of its rows; FlowToPy indents it from the depth where it stands (read_rows(path, notes=True) gives the marks). 36 tests.
- PARSER_PYTHON_0.1.1: vars (`;@beginvar` / `;@endvar` around a literal over several lines, each line a generic row), Black at 100, test_files\test1.py, RUN.bat pauses.

## Next
0. **VFlow draws a marked span as one box** (design below), right-click combine/split into an inline box (`;@begininline` / `;@endinline`), then two spacing fixes. See `app_tree\notes\SYNC_exporter_with_VFlow.md` and the VFlow START_HERE.
1. **VFlow takes the exporter** (Luis: VFlow is the ground truth; the two copies stay the same). Read `app_tree\notes\SYNC_exporter_with_VFlow.md`. That is a VFlow build, not this project.
2. Run the parser on the sample files in `test_files` and open the `.vfc` in VFlow: look at what the pictures show (class, decorators, generic rows for docstrings).
3. Decide what else belongs in the comparison (today: blank lines and the indentation of comment-only lines are not compared).

## The layout
`app\` the program: `parse_Python.py` (entry), `PyComments.py`, `PyToFlow.py`, `FlowFile.py`, `FlowToPy.py`, `RoundTrip.py`. `app\extras\` older versions. `test_files\` Python files to try it on. `app_tree\` bat, notes, tests, dependencies.json, architecture (the old parser's flow picture).
