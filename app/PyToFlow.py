"""PyToFlow - the AST of a Python file as the rows of a flow code file. The parser's one pass: it walks the tree once and writes the rows. It writes no Python and no commented copy of the source.
One statement is one row, however many lines it takes in the source (a signature that Black cut over four lines is still one `input` row).
	import, from              event(...)
	def, class                input(def f(x):) ... end()        (a decorator is a set row above it)
	if / elif / else          branch(if a:) path() ... path(elif b:) ... path(else:) ... bend()
	for, while                loop(for x in y:) ... lend()      (`else:` is a path inside the loop)
	with                      branch(with a as b:) path() ... bend()
	try / except / finally    branch(try:) path() ... path(except E:) ... path(finally:) ... bend()
	match / case              branch(match x:) path(case 1:) ... bend()
	anything else             set(the statement)
	a comment on its own line a set row with no text and the comment           a comment after code: the comment of that row
A statement (or a header) that has a string over several lines, or a comment inside it, is its first line as a row, then every other line as a generic row, exactly as it is in the source: a string keeps its spaces, a comment stays where it is.
A list, dictionary, set or tuple assigned to a name over several lines is a var: a note line `;@beginvar`, one generic row for each of its lines exactly as in the source, a note line `;@endvar`. The notes start with ; so the legacy tool skips them; VFlow draws what is between them as one box.
A list, dictionary, set or tuple assigned to a name over several lines is a var: a note line `;@beginvar`, one generic row for each of its lines exactly as in the source, a note line `;@endvar`. The notes start with ; so the legacy tool skips them; VFlow draws what is between them as one box.
Not carried: blank lines."""

import ast

from FlowFile import BEGIN_VAR, END_VAR, NOTE, Row

TRY = tuple(getattr(ast, name) for name in ("Try", "TryStar") if hasattr(ast, name))
MATCH = getattr(ast, "Match", None)


class Walker:
    def __init__(self, scan):
        self.scan = scan
        self.rows = []
        self.pending = sorted(
            scan.standalone
        )  #   the lines of the comments that are on a line of their own and are not written yet

    def walk(self, tree):
        """The rows of a module."""
        if tree.body:
            self.block(tree.body, None)
        else:
            self.tail(0, None)
        return self.rows

    def add(self, kind, text, comment=None):
        self.rows.append(Row(kind, text, comment))

    # ---- comments ---------------------------------------------------------------------------------
    def comments_before(self, line):
        """The comments on a line of their own, above `line`, are rows."""
        while self.pending and self.pending[0] < line:
            self.add("set", "", self.scan.standalone[self.pending.pop(0)][1])

    def tail(self, col, before):
        """The comments after the last statement of a block that stand as far in as the block (and above line `before`, when there is one) belong to the block."""
        while self.pending:
            line = self.pending[0]
            if (before is not None and line >= before) or self.scan.standalone[line][0] < col:
                break
            self.add("set", "", self.scan.standalone[self.pending.pop(0)][1])

    # ---- statements -------------------------------------------------------------------------------
    @staticmethod
    def first_line(node):
        """The first line of a statement: its first decorator, when it has them."""
        return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])

    def block(self, body, after):
        """The statements of a body, with the comments between them. `after` is the first line that is not in this body (None: the end of the file)."""
        col = self.scan.char_col(body[0].lineno, body[0].col_offset)
        for index, node in enumerate(body):
            self.comments_before(self.first_line(node))
            following = self.first_line(body[index + 1]) if index + 1 < len(body) else after
            self.statement(node, following)
        self.tail(col, after)

    def statement(self, node, after):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.definition(node, after)
        elif isinstance(node, ast.If):
            self.if_statement(node, after)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            self.loop_statement(node, after)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            self.with_statement(node, after)
        elif TRY and isinstance(node, TRY):
            self.try_statement(node, after)
        elif MATCH and isinstance(node, MATCH):
            self.match_statement(node, after)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            self.simple(node, "event")
        else:
            self.simple(node, "set")

    def span(self, node, first=None):
        """((line, column) of the start, (line, column) after the end) of a node; the start can be given."""
        scan = self.scan
        start = first or (node.lineno, scan.char_col(node.lineno, node.col_offset))
        return start, (
            node.end_lineno,
            scan.char_col(node.end_lineno, node.end_col_offset),
        )

    def simple(self, node, kind, first=None):
        """A statement that holds no other statements: one row."""
        scan = self.scan
        start, end = self.span(node, first)
        if end[0] > start[0] and self.is_literal(node):
            self.var(start, end)
            return
        if scan.has_inside(start[0], end[0]):
            self.raw(kind, start, end)
            return
        text, inner = scan.join(start, end)
        if inner:
            self.raw(kind, start, end)
            return
        self.add(kind, text, scan.trailing.get(end[0]))

    @staticmethod
    def is_literal(node):
        """True for `name = [..]`, `name: T = {..}`: a list, dictionary, set or tuple given to a name."""
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            return False
        return isinstance(node.value, (ast.List, ast.Dict, ast.Set, ast.Tuple))

    def var(self, start, end):
        """A literal over several lines: the begin mark, each line as a generic row, the end mark. The white space in front of the first line is left off every row, and each level of four spaces inside is one tab (the export puts the indentation back from where the box stands)."""
        self.add(NOTE, BEGIN_VAR)
        lines = self.scan.lines
        base = lines[start[0] - 1][: self.scan.indent(start[0])]
        for number in range(start[0], end[0] + 1):
            line = lines[number - 1]
            line = line[len(base) :] if line.startswith(base) else line.lstrip()
            run = len(line) - len(line.lstrip(" "))
            self.add("generic", "\t" * (run // 4) + " " * (run % 4) + line[run:])  #   one tab for each level of four spaces
        self.add(NOTE, END_VAR)
        self.pending = [line for line in self.pending if not start[0] <= line <= end[0]]

    def raw(self, kind, start, end):
        """A statement with a string over several lines, or a comment inside it: its first line, then each line as it is."""
        lines = self.scan.lines
        self.add(kind, lines[start[0] - 1][start[1] :])
        for number in range(start[0] + 1, end[0] + 1):
            self.add("generic", lines[number - 1])
        self.pending = [line for line in self.pending if not start[0] <= line <= end[0]]

    def header(self, kind, line, body_first):
        """The row of a header (`def f(x):`, `else:`): from its first word to its colon, on one line. The comment after the colon is its comment unless a statement follows the colon on that line."""
        scan = self.scan
        start = (line, scan.indent(line))
        colon = scan.colon_after(*start)
        text, inner = scan.join(start, colon)
        if inner:
            self.raw(kind, start, colon)
            return
        self.add(kind, text, scan.trailing.get(colon[0]) if body_first > colon[0] else None)

    def definition(self, node, after):
        scan = self.scan
        for decorator in node.decorator_list:
            line = decorator.lineno
            at = scan.lines[line - 1].rfind("@", 0, scan.char_col(line, decorator.col_offset))
            self.simple(decorator, "set", (line, at))
        self.header("input", node.lineno, node.body[0].lineno)
        self.block(node.body, after)
        self.add("end", "")

    def if_statement(self, node, after):
        scan = self.scan
        self.header("branch", node.lineno, node.body[0].lineno)
        self.add("path", "")
        current = node
        while True:
            orelse = current.orelse
            if orelse and self.is_elif(orelse):
                self.block(current.body, orelse[0].lineno)
                self.comments_before(orelse[0].lineno)
                current = orelse[0]
                self.header("path", current.lineno, current.body[0].lineno)
                continue
            if not orelse:
                self.block(current.body, after)
                break
            line = scan.keyword_line(
                "else",
                scan.indent(current.lineno),
                current.body[-1].end_lineno,
                orelse[0].lineno,
            )
            self.block(current.body, line)
            self.comments_before(line)
            self.header("path", line, orelse[0].lineno)
            self.block(orelse, after)
            break
        self.add("bend", "")

    def is_elif(self, orelse):
        """True when the else of an if is one `elif` (the tree has it as an if inside the else, so the source line tells)."""
        if len(orelse) != 1 or not isinstance(orelse[0], ast.If):
            return False
        return self.scan.lines[orelse[0].lineno - 1].lstrip().startswith("elif")

    def loop_statement(self, node, after):
        scan = self.scan
        self.header("loop", node.lineno, node.body[0].lineno)
        if node.orelse:
            line = scan.keyword_line(
                "else",
                scan.indent(node.lineno),
                node.body[-1].end_lineno,
                node.orelse[0].lineno,
            )
            self.block(node.body, line)
            self.comments_before(line)
            self.header("path", line, node.orelse[0].lineno)
            self.block(node.orelse, after)
        else:
            self.block(node.body, after)
        self.add("lend", "")

    def with_statement(self, node, after):
        self.header("branch", node.lineno, node.body[0].lineno)
        self.add("path", "")
        self.block(node.body, after)
        self.add("bend", "")

    def try_statement(self, node, after):
        scan = self.scan
        col = scan.indent(node.lineno)
        sections = [(handler.lineno, handler.body) for handler in node.handlers]
        last = (node.handlers[-1].body if node.handlers else node.body)[-1].end_lineno
        if node.orelse:
            sections.append(
                (
                    scan.keyword_line("else", col, last, node.orelse[0].lineno),
                    node.orelse,
                )
            )
            last = node.orelse[-1].end_lineno
        if node.finalbody:
            sections.append(
                (
                    scan.keyword_line("finally", col, last, node.finalbody[0].lineno),
                    node.finalbody,
                )
            )
        self.header("branch", node.lineno, node.body[0].lineno)
        self.add("path", "")
        self.block(node.body, sections[0][0] if sections else after)
        for index, (line, body) in enumerate(sections):
            self.comments_before(line)
            self.header("path", line, body[0].lineno)
            self.block(body, sections[index + 1][0] if index + 1 < len(sections) else after)
        self.add("bend", "")

    def case_line(self, case, low):
        """The line of the word `case` of a case: the pattern can start on a later line when it is in brackets."""
        lines = self.scan.lines
        for line in range(case.pattern.lineno, low, -1):
            if lines[line - 1].lstrip().startswith("case") and line > low:
                return line
        raise ValueError("line %d: no `case` above this pattern" % case.pattern.lineno)

    def match_statement(self, node, after):
        starts, low = [], node.lineno
        for case in node.cases:
            starts.append(self.case_line(case, low))
            low = case.body[-1].end_lineno
        self.header("branch", node.lineno, node.cases[0].body[0].lineno)
        for index, case in enumerate(node.cases):
            self.comments_before(starts[index])
            self.header("path", starts[index], case.body[0].lineno)
            self.block(case.body, starts[index + 1] if index + 1 < len(starts) else after)
        self.add("bend", "")
