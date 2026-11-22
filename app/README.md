# app

The program. Start: `python parse_Python.py <file.py>`.

| file | job |
|---|---|
| parse_Python.py | the entry: Black, the AST pass, the file, the check |
| PyComments.py | reads the comments and strings the AST does not keep |
| PyToFlow.py | the AST as flow rows (the parser) |
| FlowFile.py | how a row is written and read, and the footer |
| FlowToPy.py | the rows as Python (the check's half; VFlow carries a copy of these rules) |
| RoundTrip.py | Black on both sides, and the difference |

`extras` holds older versions (the comment route).
