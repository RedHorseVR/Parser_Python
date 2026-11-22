# PARSER_PYTHON_0.1.5

SameProgram: are two Python files the same program with only things moved around? (`app/SameProgram.py`)
- Both files are read with Python's own parser. Classes, methods and functions are compared by name as trees without line numbers: spacing, blank lines and comments do not count.
- Order is free at the top of the file and inside a class (imports, constants, methods). Inside a function the order of the statements is compared as it is.
- The answer lists what is missing, extra or different, by name. Empty: the same program. Run: `python app\SameProgram.py first.py second.py` (exit code 1 when they differ).
- First use (2026-11-22): `test.py` against `_test.py`, the export of VFlow 2.0.134 of the restructured `test.py.vfc`: the same program.
- Tests: 42 in test_parser.py (6 new).
- SYNC note: VFlow's Export has taken the path-level and class-column rules (see SYNC_exporter_with_VFlow.md).
