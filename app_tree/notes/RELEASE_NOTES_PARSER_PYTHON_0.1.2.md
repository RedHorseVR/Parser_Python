# PARSER_PYTHON_0.1.2

- Vars: the white space in front of the first line of a box is left off every row (`generic(ENDS = [);//`, not four spaces first). The export (FlowToPy) puts the indentation back from the depth where the box stands, the way VFlow's Export does for any row. Strings over several lines are not boxes: their rows stay exactly as written (the spaces are part of the string).
- FlowFile.read_rows(path, notes=True) also returns the begin and end marks as rows (kind note); the check uses it so the export knows where a box is. The default is as before.
- Test: 36 (new: an indented var in a function round trips).
- Corpus checked here: the parser's own files, test_files and 150 standard library files, all PERFECT.
- Pairs with VFlow 2.0.123 (box text has no leading white space, double click edit).
