# PARSER_PYTHON_0.1.1

- **Vars.** A list, dictionary, set or tuple that is given to a name over several lines is written as a var: the note line `;@beginvar`, then one `generic` row for each of its lines exactly as in the source, then the note line `;@endvar`. The legacy tool skips a line that starts with `;`; VFlow (next build) draws what is between the notes as one box. A literal on one line stays a plain row. Two literals one after the other stay two vars. A chip note under any inner row is untouched.
- **Black at 100** (RoundTrip.LINE_LENGTH), before the AST and on both sides of the check. A statement stays on one row until it is longer than 100.
- **test_files\test1.py**: legal Python that runs by itself (python test_files\test1.py) and holds a class, a class decorator, a property, if/elif/else, for and while with else, try/except/else/finally, with, match, async, a string over lines, a signature Black cuts, and literals. It parses and round-trips perfectly.
- **RUN.bat** pauses at the end, so the window stays open on success too.
- The row count printed by a run does not count the note lines.
- 35 tests (7 new).
