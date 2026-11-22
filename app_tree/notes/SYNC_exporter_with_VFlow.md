# The exporter: Parser_Python and VFlow carry one copy each (keep them the same)

Luis, 2026-11-21: VFlow is the ground truth exporter and must export correctly. Both projects carry their own copy of the export code for now and the copies are kept in step. Later both use one library (its own project).

## Where the copy is
- Parser_Python: `app/FlowToPy.py` (rows in, Python text out) with `app/FlowFile.py` (how a row is read and written).
- VFlow: `app/VFExport.py` and `VFCodeView.tree_items` / `tree_rows`.
FlowToPy.py was taken from those two and has no Tk and no AST, so it can move to VFlow or into the library as it is.

## What differs today (VFlow has to take these from FlowToPy.py)
1. **Paths are one level too deep in VFlow.** `branch(if a:)`, an empty path, the body, `path(else:)`: VFlow writes `else:` one level in from the `if`. Same for `elif`, `except`, `finally`, and the `else:` of a loop. That is not valid Python (Black refuses it). FlowToPy: an empty path writes nothing; a path with text stands level with its branch or loop; its body is one level in. A `case` of a `match` is one level in from the `match`.
2. **A string over several lines.** VFlow trims every label and puts the tabs of its depth in front, so the lines of a string lose their spaces. FlowToPy writes a `generic` row exactly as it is. The parser writes the lines after the first line of such a string as `generic` rows.
3. **Comment text.** VFlow collapses `#  two spaces` to one space. The parser writes the comment after the end mark with one space in front, so the text after the hash is kept exactly; FlowToPy writes the hash and that text.
4. **Indent.** VFlow writes tabs; FlowToPy writes four spaces. Black makes both the same, so only the check cares.

## A separate VFlow bug found on the way
`VFObj.Extract` does `s.replace(vfc_item + '(', '')` on the whole row, so every `set(` inside a row of kind `set` is removed from its text: `set(x = offset(1) + set(a))` shows and exports as `x = off1) + a)`. The same for `event(`, `input(` and the others inside their own row. The fix is to remove only the first one (`replace(..., '', 1)`). Not changed here (VFlow is another build).

## What the parser's check does not need from VFlow
The check exports the rows itself (FlowToPy), so it does not wait for the VFlow change. When VFlow takes FlowToPy's rules, the Export button and the parser's check say the same thing, and a perfect check means a perfect VFlow Export.

## Rule for the copies
When either copy changes, change the other in the same session and say so in the release notes. A test in each project should fix the same cases (the parser's: `ExportTests` and `RoundTripTests` in `app_tree/tests/test_parser.py`).

## 2026-11-22
VFlow 2.0.134 took point 1 (a way stands level with its branch) and the class-column rule (a branch with no text adds no level) into `VFExport.code_depths`. Point 2 (a string over several lines) is still to take.
